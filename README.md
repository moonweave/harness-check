# harness-check

![Python](https://img.shields.io/badge/python-3.8%2B-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Claude%20Code-blueviolet)
![Status](https://img.shields.io/badge/status-active-brightgreen)

> A `/harness-check` slash command for Claude Code — **one-shot audit** of hooks, plugins, MCP processes, and usage stats. Writes a live snapshot to your `workspace_map.md` dashboard.

---

## Quick Start

```bash
# 1. Copy the command file
cp harness-check.md ~/.claude/commands/harness-check.md

# 2. Open any Claude Code session and run
/harness-check
```

That's it. Claude will audit your full configuration and update your `workspace_map.md` automatically.

---

## What it checks

| Section | Description |
|---------|-------------|
| Hook event pipeline | Mermaid diagram of all registered hooks from `settings.json` |
| Plugins & marketplaces | `enabledPlugins` table with marketplace sources |
| Hook pipeline detail | Per-script logic summary + orphan script detection |
| Skills / Agents / Commands | Filesystem scan of `~/.claude/` |
| Knowledge Base | `knowledge/index.md` entry count and load status |
| **Hook health** | Syntax check + dependency binaries + `guards/` import + live run test |
| **Plugin usage frequency** | 30-day JSONL scan — flags 0-call plugins with 🟡 |
| **MCP process count** | Detects duplicate MCP processes with 🔴 |
| **Project state top 5** | Largest accumulated project states by size |
| Diagnostics | Orphan scripts, dangerous flags, stale patterns |

---

## Sample Output

After running `/harness-check`, your `workspace_map.md` AUTO section is updated:

```
## Hook Health
✅ pre-commit.py   — OK (guards/ imported, binaries found)
✅ post-tool.py    — OK
🟡 unused-hook.py  — 0 calls in last 30 days

## MCP Processes
✅ No duplicate MCP processes detected

## Plugin Usage (30-day)
🟢 core-plugin       — 142 calls
🟡 legacy-formatter  — 0 calls (consider disabling)

## Project State Top 5
1. my-app/        — 4.2 MB
2. api-server/    — 2.1 MB
```

---

## Requirements

| Requirement | Purpose |
|-------------|---------|
| Claude Code | Runs the `/harness-check` command |
| `workspace_map.md` with `<!-- AUTO:START -->` / `<!-- AUTO:END -->` markers | Target file for the audit snapshot |
| `uv` | Python execution in hooks |
| git repo at `~/Vaults/workspace-map/` | Auto-commit after update (path is configurable) |

---

## Install

```bash
cp harness-check.md ~/.claude/commands/harness-check.md
```

Then run `/harness-check` in any Claude Code session.

---

## Usage

```
/harness-check
```

Claude will collect all settings, run the health checks, overwrite the AUTO section of `workspace_map.md`, commit, and regenerate the dashboard.

---

## License

MIT © moonweave
