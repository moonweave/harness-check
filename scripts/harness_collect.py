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

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
HOOKS_DIR = CLAUDE_DIR / "hooks"
SKILLS_DIR = CLAUDE_DIR / "skills"
AGENTS_DIR = CLAUDE_DIR / "agents"
COMMANDS_DIR = CLAUDE_DIR / "commands"
PROJECTS_DIR = CLAUDE_DIR / "projects"
KNOWLEDGE_DIR = CLAUDE_DIR / "knowledge"
SKIP_USAGE = "--skip-usage" in sys.argv


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


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------


def collect_settings() -> dict:
    path = CLAUDE_DIR / "settings.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def collect_settings_local() -> dict | None:
    path = CLAUDE_DIR / "settings.local.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def collect_hooks(settings: dict) -> dict:
    registered: list[dict] = []
    for event, blocks in settings.get("hooks", {}).items():
        for block in blocks:
            matcher = block.get("matcher", "")
            for hook in block.get("hooks", []):
                cmd = hook.get("command", "")
                script = Path(cmd.split()[-1]).name if cmd else ""
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
        rc, _ = run(["python3", "-m", "py_compile", str(py)])
        scripts[py.name] = {
            "exists": True,
            "syntax_ok": rc == 0,
            "orphan": py.name not in registered_scripts,
        }

    return {
        "registered": registered,
        "scripts": scripts,
        "orphans": [n for n, v in scripts.items() if v["orphan"]],
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
    # Syntax check
    syntax: dict[str, bool] = {}
    for py in sorted(HOOKS_DIR.glob("*.py")):
        rc, _ = run(["python3", "-m", "py_compile", str(py)])
        syntax[py.name] = rc == 0

    # Dependency binaries
    deps: dict[str, bool] = {}
    for binary in ["agent-notify", "mempalace", "ruff"]:
        rc, _ = run(["which", binary])
        deps[binary] = rc == 0

    # guards/ package import
    guards_ok = False
    rc, _ = run(
        [
            "python3",
            "-c",
            f"import sys; sys.path.insert(0,'{HOOKS_DIR}'); "
            "from guards import bash,files,mcp_github,mcp_playwright,web",
        ]
    )
    guards_ok = rc == 0

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
    except Exception:
        pass

    return {
        "syntax": syntax,
        "dependencies": deps,
        "guards_import": guards_ok,
        "context_inject_live": inject_ok,
    }


def collect_plugin_usage(settings: dict) -> dict[str, int]:
    if SKIP_USAGE:
        return {}
    cutoff = datetime.now() - timedelta(days=30)
    pattern = re.compile(r'"skill"\s*:\s*"([^"]+)"')
    counts: Counter = Counter()
    for jsonl in glob.glob(str(PROJECTS_DIR / "**" / "*.jsonl"), recursive=True):
        try:
            if datetime.fromtimestamp(os.path.getmtime(jsonl)) < cutoff:
                continue
            content = Path(jsonl).read_text(errors="replace")
            for m in pattern.finditer(content):
                counts[m.group(1)] += 1
        except Exception:
            pass
    return dict(counts.most_common(30))


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
    pattern = re.compile("|".join(names))
    counts: Counter = Counter()
    for line in out.splitlines():
        if not any(n in line for n in names):
            continue
        for m in pattern.finditer(line):
            counts[m.group()] += 1
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
    settings = collect_settings()
    settings_local = collect_settings_local()

    result = {
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "skip_usage": SKIP_USAGE,
        "settings": settings,
        "settings_local": settings_local,
        "hooks": collect_hooks(settings),
        "skills": collect_skills(),
        "agents": collect_agents(),
        "commands": collect_commands(),
        "kb": collect_kb(),
        "health": collect_health(),
        "plugin_usage": collect_plugin_usage(settings),
        "mcp_processes": collect_mcp_processes(),
        "project_state_top5": collect_project_state(),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
