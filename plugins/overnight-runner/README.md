# Overnight Runner

Overnight Runner is a Codex plugin for long autonomous todo runs. It combines
the previous Rizonetech repo-local overnight runners into one reusable workflow.

The plugin writes state to the active repository:

```text
.codex/state/overnight-runner.json
```

ChromeMCP is strongly preferred for user-facing verification. If ChromeMCP is
not installed, enabled, or running, the guard records a blocker and keeps the
run honest instead of failing with a hard dependency error.

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
~/.codex/tools/overnight-runner update --slice "Login flow" --gate implemented=passed
~/.codex/tools/overnight-runner finish-check
~/.codex/tools/overnight-runner handoff --write-todo
```
