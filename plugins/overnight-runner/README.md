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

## Helper

```bash
python3 ~/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py start todo/example.md
python3 ~/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py update --slice "Login flow" --gate implemented=passed
python3 ~/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py finish-check
python3 ~/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py handoff --write-todo
```
