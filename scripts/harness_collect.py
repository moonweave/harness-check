#!/usr/bin/env python3
"""Deterministic data collector for /harness-check.

Reads all harness configuration sources and outputs a single JSON object to
stdout. Claude reads this JSON and generates the formatted report.

Usage: uv run python3 ~/.claude/scripts/harness_collect.py [--skip-usage]
  --skip-usage  Skip the slow 30-day JSONL scan (plugin usage stats)
"""

import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home().resolve()
CLAUDE_DIR = HOME / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"
SKILLS_DIR = CLAUDE_DIR / "skills"
AGENTS_DIR = CLAUDE_DIR / "agents"
COMMANDS_DIR = CLAUDE_DIR / "commands"
PROJECTS_DIR = CLAUDE_DIR / "projects"
KNOWLEDGE_DIR = CLAUDE_DIR / "knowledge"
SKIP_USAGE = "--skip-usage" in sys.argv
VERSION = "harness_collect.py 1.0.0"

# Masked in JSON output to prevent leaking secrets into workspace_map.md / git
_MASKED = "<masked>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(cmd: list[str], timeout: int = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return -1, ""


def read_frontmatter(path: Path) -> dict[str, str]:
    """Parse YAML-style frontmatter from a markdown file."""
    text = path.read_text(errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip()
    result: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip().strip('"')
    return result


def _mask_settings(raw: dict) -> dict:
    """Return a copy of settings with env values masked."""
    out = dict(raw)
    if "env" in out and isinstance(out["env"], dict):
        out["env"] = {k: _MASKED for k in out["env"]}
    return out


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def collect_settings() -> dict:
    path = CLAUDE_DIR / "settings.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        return _mask_settings(raw)
    except Exception as exc:
        return {"_error": f"parse failed: {exc}"}


def collect_settings_local() -> dict | None:
    path = CLAUDE_DIR / "settings.local.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return _mask_settings(raw)
    except Exception as exc:
        return {"_error": f"parse failed: {exc}"}


def collect_hooks(settings: dict) -> dict:
    errors: list[str] = []
    registered: list[dict] = []

    if "_error" in settings:
        return {
            "registered": [],
            "scripts": {},
            "orphans": [],
            "errors": [settings["_error"]],
        }

    for event, blocks in settings.get("hooks", {}).items():
        for block in blocks:
            matcher = block.get("matcher", "")
            for hook in block.get("hooks", []):
                cmd = hook.get("command", "")
                # Q2 fix: find last .py token instead of last token
                parts = cmd.split()
                py_parts = [p for p in parts if p.endswith(".py")]
                script = Path(py_parts[-1]).name if py_parts else ""
                registered.append(
                    {
                        "event": event,
                        "matcher": matcher,
                        "command": cmd,
                        "script": script,
                        "timeout": hook.get("timeout"),
                    }
                )

    registered_scripts = {
        h["script"] for h in registered if h["script"].endswith(".py")
    }

    scripts: dict[str, dict] = {}
    for py in sorted(HOOKS_DIR.glob("*.py")):
        rc, msg = run(["python3", "-m", "py_compile", str(py)])
        ok = rc == 0
        if not ok:
            errors.append(f"syntax error in {py.name}: {msg}")
        scripts[py.name] = {
            "exists": True,
            "syntax_ok": ok,
            "orphan": py.name not in registered_scripts,
        }

    return {
        "registered": registered,
        "scripts": scripts,
        "orphans": [n for n, v in scripts.items() if v["orphan"]],
        "errors": errors,
    }


def collect_skills() -> list[str]:
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.name for p in SKILLS_DIR.iterdir() if not p.name.startswith("."))


def collect_agents() -> list[dict]:
    if not AGENTS_DIR.exists():
        return []
    agents = []
    for md in sorted(AGENTS_DIR.glob("*.md")):
        fm = read_frontmatter(md)
        agents.append(
            {
                "name": fm.get("name", md.stem),
                "model": fm.get("model", "inherit"),
                "description": fm.get("description", ""),
                "color": fm.get("color", ""),
            }
        )
    return agents


def collect_commands() -> list[dict]:
    if not COMMANDS_DIR.exists():
        return []
    cmds = []
    for md in sorted(COMMANDS_DIR.glob("*.md")):
        text = md.read_text(errors="replace")
        first_line = next(
            (ln.lstrip("# ").strip() for ln in text.splitlines() if ln.strip()),
            md.stem,
        )
        cmds.append({"name": md.stem, "description": first_line})
    return cmds


def collect_kb() -> dict:
    index = KNOWLEDGE_DIR / "index.md"
    if not index.exists():
        return {"count": 0, "last_updated": None}
    rows = [
        ln
        for ln in index.read_text().splitlines()
        if ln.startswith("|") and "---" not in ln and "Article" not in ln
    ]
    dates = [r.split("|")[-2].strip() for r in rows if len(r.split("|")) >= 3]
    dates = [d for d in dates if d and d != "Updated"]
    return {
        "count": len(rows),
        "last_updated": max(dates) if dates else None,
    }


def collect_health() -> dict:
    errors: list[str] = []

    # Syntax check (already done in collect_hooks, but kept independent)
    syntax: dict[str, bool] = {}
    for py in sorted(HOOKS_DIR.glob("*.py")):
        rc, msg = run(["python3", "-m", "py_compile", str(py)])
        ok = rc == 0
        syntax[py.name] = ok
        if not ok:
            errors.append(f"syntax: {py.name}: {msg}")

    # Dependency binaries
    deps: dict[str, bool] = {}
    for binary in ["agent-notify", "mempalace", "ruff"]:
        rc, _ = run(["which", binary])
        ok = rc == 0
        deps[binary] = ok
        if not ok:
            errors.append(f"missing binary: {binary}")

    # guards/ package import — use resolved HOOKS_DIR (S1 fix)
    hooks_dir_str = str(HOOKS_DIR.resolve())
    rc, msg = run(
        [
            "python3",
            "-c",
            f"import sys; sys.path.insert(0,'{hooks_dir_str}'); "
            "from guards import bash,files,mcp_github,mcp_playwright,web",
        ]
    )
    guards_ok = rc == 0
    if not guards_ok:
        errors.append(f"guards/ import failed: {msg}")

    # context_inject.py live run
    inject_ok = False
    try:
        r = subprocess.run(
            ["python3", str(HOOKS_DIR / "context_inject.py")],
            input="{}",
            capture_output=True,
            text=True,
            timeout=5,
        )
        inject_ok = r.returncode == 0 and r.stdout.strip().startswith("{")
        if not inject_ok:
            errors.append(f"context_inject live test failed: {r.stderr.strip()[:100]}")
    except Exception as exc:
        errors.append(f"context_inject live test exception: {exc}")

    return {
        "syntax": syntax,
        "dependencies": deps,
        "guards_import": guards_ok,
        "context_inject_live": inject_ok,
        "errors": errors,
    }


def collect_plugin_usage(settings: dict) -> dict[str, int]:
    if SKIP_USAGE:
        return {}
    cutoff = datetime.now() - timedelta(days=30)
    pattern = re.compile(r'"skill"\s*:\s*"([^"]+)"')
    counts: Counter = Counter()
    errors: list[str] = []

    for jsonl in glob.glob(str(PROJECTS_DIR / "**" / "*.jsonl"), recursive=True):
        try:
            if datetime.fromtimestamp(os.path.getmtime(jsonl)) < cutoff:
                continue
            # Q3 fix: line-by-line streaming instead of full read_text
            with open(jsonl, errors="replace") as fh:
                for line in fh:
                    for m in pattern.finditer(line):
                        counts[m.group(1)] += 1
        except Exception as exc:
            errors.append(f"{Path(jsonl).name}: {exc}")

    result = dict(counts.most_common(30))
    if errors:
        result["_errors"] = errors[:5]  # type: ignore[assignment]
    return result


def collect_mcp_processes() -> dict[str, int]:
    rc, out = run(["ps", "aux"])
    if rc != 0:
        return {}
    names = [
        "playwright",
        "firecrawl",
        "context7",
        "github",
        "mempalace",
        "brave",
        "duckdb",
    ]
    counts: Counter = Counter()
    # Q1 fix: count each name at most once per process line
    for line in out.splitlines():
        matched = {n for n in names if n in line}
        counts.update(matched)
    return dict(counts)


def collect_project_state(top_n: int = 5) -> list[dict]:
    if not PROJECTS_DIR.exists():
        return []
    rows = []
    for proj in PROJECTS_DIR.iterdir():
        if not proj.is_dir():
            continue
        jsonls = list(proj.glob("*.jsonl"))
        if not jsonls:
            continue
        mtimes = [j.stat().st_mtime for j in jsonls]
        size_mb = sum(j.stat().st_size for j in jsonls) / 1024 / 1024
        rows.append(
            {
                "dir": proj.name,
                "sessions": len(jsonls),
                "last_active": datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d"),
                "size_mb": round(size_mb, 1),
            }
        )
    rows.sort(key=lambda x: x["size_mb"], reverse=True)
    return rows[:top_n]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if "--version" in sys.argv:
        print(VERSION)
        sys.exit(0)

    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    errors: list[str] = []

    # D2 fix: wrap each collector — parse failure returns error dict, not crash
    def safe(fn, *args, fallback=None):
        try:
            return fn(*args)
        except Exception as exc:
            errors.append(f"{fn.__name__}: {exc}")
            return fallback() if callable(fallback) else fallback

    settings = safe(collect_settings, fallback=dict)
    settings_local = safe(collect_settings_local)
    hooks = safe(collect_hooks, settings, fallback=dict)
    skills = safe(collect_skills, fallback=list)
    agents = safe(collect_agents, fallback=list)
    commands = safe(collect_commands, fallback=list)
    kb = safe(collect_kb, fallback=dict)
    health = safe(collect_health, fallback=dict)
    plugin_usage = safe(collect_plugin_usage, settings, fallback=dict)
    mcp_processes = safe(collect_mcp_processes, fallback=dict)
    project_state = safe(collect_project_state, fallback=list)

    # D4 fix: surface collector-level errors in top-level "errors" key
    result = {
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "skip_usage": SKIP_USAGE,
        "errors": errors,
        "settings": settings,
        "settings_local": settings_local,
        "hooks": hooks,
        "skills": skills,
        "agents": agents,
        "commands": commands,
        "kb": kb,
        "health": health,
        "plugin_usage": plugin_usage,
        "mcp_processes": mcp_processes,
        "project_state_top5": project_state,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
