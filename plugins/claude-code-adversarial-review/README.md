# Claude Code Adversarial Review

Codex plugin for reviewing Claude Code output as an external adversarial reviewer.

Use it when Claude Code has implemented a task, changed a TODO section, opened a PR, or produced a diff that needs a skeptical second pass. The skill requires Codex to inspect the actual code, cite file and line evidence, separate real defects from false positives, and block completion on unresolved Critical or High findings.

## Install

Install through the repository-level installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1
```

Restart Codex after installation.

## Typical Prompts

```text
Use Claude Code Adversarial Review on this diff
Review Claude Code's changes for bugs and regressions
Run an adversarial review of this TODO section
```
