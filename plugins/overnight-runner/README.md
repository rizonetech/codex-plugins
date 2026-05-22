# Overnight Runner

Overnight Runner is a Codex plugin for long autonomous todo runs. It combines
the previous Rizonetech repo-local overnight runners into one reusable workflow.

The plugin writes state to the active repository:

```text
.codex/state/overnight-runner.json
```

Existing checked todo items are treated as claims. The runner requires each
current `[x]` item to be reviewed with current evidence before finish-check can
pass. If a checked item is partly true but missing work, use
`checked-review --status remediated --missing ... --add-missing` after fixing
the gap. The runner appends the remediated work back into the todo as checked
history so completion remains accurate without creating work to rediscover.

ChromeMCP is strongly preferred for user-facing verification. If ChromeMCP is
not installed, enabled, or running, the guard records a blocker and keeps the
run honest instead of failing with a hard dependency error.

For ChromeMCP evidence outside a chat-exposed MCP tool, use the installed MCP
safe runner:

```bash
~/.codex/tools/chromemcp-run --url "https://example.com" --required --handoff --screenshot
```

Raw CDP/WebSocket checks are diagnostic only and do not satisfy passed browser
or production smoke gates.

## Modules

The runner is project-agnostic. It detects modules from repository markers and
applies only the matching project rules:

- `laravel`: Laravel Cloud queue/deploy safety when `bin/cloud` exists.
- `wordpress`: plugin/theme cutover and rollback manifest safety.
- `node`: package manager build/test hints.
- `generic`: deploy gates remain active without assuming a framework.

Multiple modules can be active in one repository, such as Laravel plus Node.

## Helper

```bash
~/.codex/tools/overnight-runner start todo/example.md
~/.codex/tools/overnight-runner preflight todo/example.md
~/.codex/tools/overnight-runner checked-review --line 12 --status passed --evidence "focused test passed"
~/.codex/tools/overnight-runner update --slice "Login flow" --gate implemented=passed
~/.codex/tools/overnight-runner finish-check
~/.codex/tools/overnight-runner handoff --write-todo
```
