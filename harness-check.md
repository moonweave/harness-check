# /harness-check

Run the collector script, then generate a formatted snapshot report.

## Step 1 — Collect

```bash
uv run python3 ~/.claude/scripts/harness_collect.py
```

Add `--skip-usage` to skip the slow 30-day JSONL scan.

The script outputs a single JSON object to stdout:
- `settings` — settings.json contents (env values masked)
- `settings_local` — settings.local.json if present, else null
- `hooks.registered` — list of {event, matcher, command, script, timeout}
- `hooks.scripts` — {filename: {exists, syntax_ok, orphan}}
- `hooks.orphans` — scripts in hooks/ not wired in settings.json
- `hooks.errors` — syntax errors detected
- `skills` — list of skill names in ~/.claude/skills/
- `agents` — list of {name, model, description, color}
- `commands` — list of {name, description}
- `kb` — {count, last_updated}
- `health.syntax` — {script: bool}
- `health.dependencies` — {binary: bool} for agent-notify / mempalace / ruff
- `health.guards_import` — bool
- `health.context_inject_live` — bool
- `health.errors` — list of health check failures
- `plugin_usage` — {skill_name: call_count} last 30 days (empty if --skip-usage)
- `mcp_processes` — {mcp_name: process_count}
- `project_state_top5` — [{dir, sessions, last_active, size_mb}]
- `errors` — top-level collector failures

## Step 2 — Generate report

Format the JSON into a readable markdown report and present it directly in the response. Structure:

```
## 🔀 Hook Event Pipeline

(mermaid flowchart LR — derive from hooks.registered)
- One node per unique event
- Each node: event name + script name(s) + [matcher if not empty]
- Colors: SessionStart=#4ade80, UserPromptSubmit=#60a5fa, PreToolUse=#f97316,
  PostToolUse=#a78bfa, Notification=#818cf8, Stop=#f43f5e,
  PreCompact=#fbbf24, PostCompact=#2dd4bf, SubagentStart=#d97706, SessionEnd=#94a3b8
- style fill/stroke/color (dark-theme fills)

## Harness Snapshot
_Last updated: {collected_at date} — /harness-check_

### ⚙️ Core Settings
Table of: model / advisorModel / effortLevel / language / defaultMode /
cleanupPeriodDays / fastModePerSessionOptIn / voiceEnabled / autoMemoryEnabled /
showThinkingSummaries / skipDangerousModePermissionPrompt

env: list key names only (values are masked in collected data).
permissions allow (one line summary). permissions deny (one line).
settings_local: "none ✅" if null.

### 🔌 Plugins & Marketplaces
Table: plugin | marketplace | status (✅/🚫) | 30-day calls
Cross-reference enabledPlugins with plugin_usage. Flag 0-call active plugins with 🟡.
extraKnownMarketplaces one line.

### 🪝 Hook Pipeline
Table: # | event | matcher | command | logic summary
Read each script file to write the logic summary (1–2 lines).
List hooks.orphans below the table.

### 📦 Skills
List all skills. Note symlinks and bundles (e.g. gstack).

### 🤖 Agents
Table: name | model | role summary

### 🌐 Commands
Table: name | description

### 📚 Knowledge Base
kb.count articles, kb.last_updated.

### 📋 CLAUDE.md Layers
Read ~/.claude/CLAUDE.md and ~/CLAUDE.md — list section headings for each.

### 🏥 Hook Health
Table: script | syntax | notes (✅/❌)
Dependencies: agent-notify / mempalace / ruff
guards/ import result. context_inject live test result.
If health.errors is non-empty, list each error with 🔴.

### 📊 Plugin Usage (30 days)
If skip_usage true: note skipped, suggest running without --skip-usage.
Otherwise: table of plugin | calls, sorted descending.
Flag active plugins with 0 calls as 🟡.

### 🔄 MCP Process Count
Table: MCP | count. Flag count > 1 with 🔴.

### 💾 Project State Top 5
Table: project (last 40 chars) | last active | sessions | size MB

### 🔍 Diagnostics
Table: item | type | detail

Types:
- 🔴 Error: syntax failure, missing dependency, collector crash (errors key non-empty)
- 🟠 Duplicate: MCP count > 1
- 🟡 Warning: active plugin 0 calls, dangerous flags, orphan scripts
- 🟢 Info: intentional design, deprecated items kept deliberately
- ✅ OK: nothing to flag
```

## Step 3 — Persist to workspace_map (opt-in)

Only run this step if the environment variable `HARNESS_CHECK_WORKSPACE_MAP` is set.

```bash
# Check if opt-in path is configured
WORKSPACE_MAP="${HARNESS_CHECK_WORKSPACE_MAP}"
```

If `HARNESS_CHECK_WORKSPACE_MAP` is not set, skip this step and tell the user:
> "To save this report to a workspace_map.md file, set HARNESS_CHECK_WORKSPACE_MAP=<path> and re-run."

If it is set:

1. Overwrite the `<!-- AUTO:START -->` … `<!-- AUTO:END -->` block in that file with the formatted report from Step 2. Only touch content inside the markers. If markers are missing, append them at the end.

2. Commit:
```bash
WORKSPACE_DIR="$(dirname "${HARNESS_CHECK_WORKSPACE_MAP}")"
git -C "${WORKSPACE_DIR}" diff --stat HEAD -- workspace_map.md
git -C "${WORKSPACE_DIR}" add workspace_map.md && \
  git -C "${WORKSPACE_DIR}" commit -m "harness-check: $(date +%Y-%m-%d) auto-update"
```
Show diff --stat. Skip commit if no changes.

3. Regenerate dashboard (only if gen_dashboard.py exists):
```bash
DASHBOARD="${WORKSPACE_DIR}/gen_dashboard.py"
if [ -f "${DASHBOARD}" ]; then
  uv run python3 "${DASHBOARD}"
fi
```
