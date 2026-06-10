# Overnight Runner

Overnight Runner is a Codex plugin for long autonomous todo runs. It combines
the previous Rizonetech repo-local overnight runners into one reusable workflow.

The plugin writes state to the active repository:

```text
.codex/state/overnight-runner.json
.codex/reports/overnight-todo-adversarial-review-*.json
```

Before `start` runs normal preflight, it adversarially reviews every todo item
in the file. The review looks for completion-accounting risks such as checked
items that still describe open work, broad/global claims without a bounded
coverage matrix, UI work without browser/visual evidence, deploy items without
rollback gates, destructive/cutover work without explicit approval, and
duplicates. Verified findings are reported to `.codex/reports/` and missing
guardrail items are added back into the todo as unchecked `Adversarial review:`
items so the run can implement them instead of rediscovering the gaps later.
This review is not a pause point: it reports, repairs the todo file, and the
runner continues into the first safe actionable slice unless the normal
destructive/safety blocker rules leave no safe work remaining.

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
~/.codex/tools/overnight-runner start todo/example.md --no-browser  # skip ChromeMCP probe for non-UI runs
~/.codex/tools/overnight-runner preflight todo/example.md
~/.codex/tools/overnight-runner todo-review todo/example.md --apply
~/.codex/tools/overnight-runner checked-review --line 12 --status passed --evidence "focused test passed"
~/.codex/tools/overnight-runner update --slice "Login flow" --gate implemented=passed
~/.codex/tools/overnight-runner finish-check
~/.codex/tools/overnight-runner handoff --write-todo
```

The `--no-browser` flag on `start` skips the ChromeMCP health probe and marks
`browser_verification` and `visual_qa` as not-applicable. Use it for todo runs
that contain no user-facing UI or browser work. If UI-looking items are
detected, a loud warning is printed and the waiver is recorded in state; the
`finish-check` command echoes it so completion claims remain honest.

The `browser_verification` gate was previously named `chromemcp_local`. State
files from older runs are migrated on load — the legacy name is normalized to
`browser_verification` automatically.
