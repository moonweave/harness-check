# /harness-check

Run the collector script, then generate a formatted snapshot report.

## Step 1 — Collect

```bash
uv run python3 ~/.claude/scripts/harness_collect.py
```

If the JSONL scan is too slow, add `--skip-usage` to skip plugin usage stats.

The script outputs a single JSON object to stdout with these keys:
- `settings` — full settings.json contents
- `settings_local` — settings.local.json if present, else null
- `hooks.registered` — list of {event, matcher, command, script, timeout}
- `hooks.scripts` — {filename: {exists, syntax_ok, orphan}}
- `hooks.orphans` — script names in hooks/ not wired in settings.json
- `skills` — list of skill names in ~/.claude/skills/
- `agents` — list of {name, model, description, color}
- `commands` — list of {name, description}
- `kb` — {count, last_updated}
- `health.syntax` — {script: bool} syntax check results
- `health.dependencies` — {binary: bool} for agent-notify / mempalace / ruff
- `health.guards_import` — bool
- `health.context_inject_live` — bool
- `plugin_usage` — {skill_name: call_count} last 30 days (empty if --skip-usage)
- `mcp_processes` — {mcp_name: process_count}
- `project_state_top5` — [{dir, sessions, last_active, size_mb}]

## Step 2 — Generate the AUTO section

Read the JSON output and overwrite the `<!-- AUTO:START -->` … `<!-- AUTO:END -->` block in `~/Vaults/workspace-map/workspace_map.md` with the following structure:

```
## 🔀 Hook Event Pipeline

(mermaid flowchart LR — derive from hooks.registered)
- One node per unique event
- Each node: event name + script name(s) + [matcher if not empty]
- Colors: SessionStart=#4ade80, UserPromptSubmit=#60a5fa, PreToolUse=#f97316,
  PostToolUse=#a78bfa, Notification=#818cf8, Stop=#f43f5e,
  PreCompact=#fbbf24, PostCompact=#2dd4bf, SubagentStart=#d97706, SessionEnd=#94a3b8
- style fill/stroke/color (dark-theme fills)

## 🔬 Research Workflow Pipeline

(mermaid flowchart LR)
- /ingest → /solve → /visualize → /draft → /ppt
- Colors: ingest=#4ade80, solve=#60a5fa, visualize=#a78bfa, draft=#fbbf24, ppt=#f97316

## Harness Snapshot
_Last updated: {collected_at date} — /harness-check_

### ⚙️ Core Settings
Table of: model / advisorModel / effortLevel / language / defaultMode /
cleanupPeriodDays / fastModePerSessionOptIn / voiceEnabled / autoMemoryEnabled /
showThinkingSummaries / skipDangerousModePermissionPrompt

env variables one line.
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
List all skills. Note symlinks and bundles (gstack).

### 🤖 Agents
Table: name | model | role summary (from description)

### 🌐 Commands
Table: name | description

### 📚 Knowledge Base
kb.count articles, kb.last_updated. Note if session_capture.py is not wired (deprecated).

### 📋 CLAUDE.md Layers
Read ~/.claude/CLAUDE.md and ~/CLAUDE.md — list section headings for each.

### 🏥 Hook Health
Table: script | syntax | notes
Use health.syntax — ✅ if true, ❌ if false.
Dependencies row: agent-notify / mempalace / ruff — ✅/❌ from health.dependencies.
guards/ import: ✅/❌ from health.guards_import.
context_inject live test: ✅/❌ from health.context_inject_live.

### 📊 Plugin Usage (30 days)
If skip_usage is true: note that stats were skipped (run without --skip-usage for full data).
Otherwise: table of plugin | calls, sorted descending.
Flag active plugins with 0 calls as 🟡.

### 🔄 MCP Process Count
Table: MCP | count. Flag count > 1 with 🔴.

### 💾 Project State Top 5
Table: project (last 40 chars of dir) | last active | sessions | size MB

### 🔍 Diagnostics
Analyze all collected data. Output table: item | type | detail

Types:
- 🔴 Error: broken script path, syntax failure, missing dependency
- 🟠 Duplicate: MCP count > 1, overlapping skills/commands
- 🟡 Warning: active plugin with 0 calls, dangerous flags, orphan scripts
- 🟢 Info: intentional design, deprecated items kept on purpose
- ✅ OK: if nothing to flag
```

## Step 3 — Commit and regenerate dashboard

```bash
git -C ~/Vaults/workspace-map diff --stat HEAD -- workspace_map.md
git -C ~/Vaults/workspace-map add workspace_map.md && \
  git -C ~/Vaults/workspace-map commit -m "harness-check: $(date +%Y-%m-%d) auto-update"
uv run python3 ~/Vaults/workspace-map/gen_dashboard.py
```

Show the diff --stat to the user. Skip commit if no changes.

## Notes

- Only overwrite the AUTO section. Never touch content outside the markers.
- If markers are missing, append them at the end of the file.
- All diagnostics go inside the AUTO section — no separate sections.
