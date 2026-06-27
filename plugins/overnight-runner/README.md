# Overnight Runner

State guard for long autonomous todo runs. Before execution it adversarially
reviews the todo file, reports structural findings, and repairs missing guardrail
items in-place. During the run it tracks slice gates and keeps completion honest.

## Quick Start

The engine ships inside this plugin. Install it into the Codex runtime
(`~/.codex/tools/overnight-runner` wrapper + `~/.codex/overnight-runner/` engine):

```bash
bash scripts/install-codex-plugin.sh
```

Then use it:

```bash
# start a guarded run (with ChromeMCP browser probe)
overnight-runner start todo/example.md

# skip browser probe for non-UI runs
overnight-runner start todo/example.md --no-browser

# check status, finish, and hand off
overnight-runner status
overnight-runner finish-check
overnight-runner handoff --write-todo
```

Other commands:

```bash
overnight-runner preflight todo/example.md
overnight-runner todo-review todo/example.md --apply
overnight-runner checked-review --line 12 --status passed --evidence "..."
overnight-runner update --slice "Login flow" --gate implemented=passed
```

## Gate Model

| Gate | When required |
|---|---|
| `implemented` | Any slice with code changes |
| `automated_tests` | Slices with testable behavior |
| `browser_verification` | User-facing UI, CRUD/GRUD, navigation, production smoke |
| `visual_qa` | Visual/layout claims |
| `production_deploy` | Deploy or release work |
| `rollback_plan` | Any destructive or deploy slice |
| `todo_history_updated` | All slices — keep history accurate |

`browser_verification` was previously named `chromemcp_local`. State files from
older runs are migrated automatically on load.

## --no-browser Flag

Pass `--no-browser` to `start` when the run contains no user-facing UI or
browser work. This skips the ChromeMCP health probe and marks
`browser_verification` and `visual_qa` as not-applicable. If UI-looking items
are detected, a loud warning is printed and the waiver is recorded in state so
`finish-check` echoes it — completion claims stay honest.

## ChromeMCP

ChromeMCP is the expected browser path. If unavailable, the runner records a
blocker and continues non-browser work. UI, visual, CRUD/GRUD, and production
smoke items stay incomplete until real ChromeMCP evidence is captured.

For browser evidence outside a chat-exposed MCP tool:

```bash
~/.codex/tools/chromemcp-run --url "https://example.com" --required --handoff --screenshot
```

ChromeMCP is optional — the runner degrades gracefully when it is not installed.

## Modules

Detected automatically from repo markers: `laravel`, `wordpress`, `node`,
`generic`. Multiple modules can be active. See [SKILL.md](skills/overnight-runner/SKILL.md)
for per-module deploy and rollback rules.

## State Files

```text
.codex/state/overnight-runner.json
.codex/reports/overnight-todo-adversarial-review-*.json
```

The guard engine ships with this plugin at `.codex/scripts/overnight-runner.py`
and installs to `~/.codex/overnight-runner/` via `scripts/install-codex-plugin.sh`.
