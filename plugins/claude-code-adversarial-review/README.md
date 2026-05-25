# Claude Code Adversarial Review

Codex plugin for asking Claude Code to adversarially review Codex changes, then having Codex verify Claude's findings before acting on them.

Use it when Codex has implemented a task, changed a TODO section, opened a PR, or produced a diff that needs a skeptical second pass from Claude Code. The skill requires Claude to produce adversarial findings and requires Codex to verify each finding against the actual code before fixing, rejecting, or accepting it.

The Claude review step is fail-soft. If Claude Code is unavailable, rate-limited,
unauthenticated, asks a question, or needs interaction, Codex records
`Claude review: skipped (<reason>)` and continues the normal Codex flow.

Claude prompts should be written to a temporary file and passed through stdin
instead of embedded directly in shell arguments. This avoids PowerShell/Bash
quoting failures before Claude Code starts.

## Install

Install through the repository-level installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1
```

Restart Codex after installation.

## Typical Prompts

```text
Use Claude Code Adversarial Review on my Codex changes
Ask Claude Code to review this diff, then verify the findings
Run Claude Code adversarial review on this TODO section
```
