---
name: wsl-run
description: Use when a Codex chat is running in PowerShell on Windows but the workspace or project expects Linux/WSL command semantics. Prefer the global wsl-run helper for shell commands, tests, builds, search, git inspection, and other command-line work while continuing to use apply_patch for file edits.
---

# WSL Run

Use this skill whenever the current shell is PowerShell and command work should behave like Linux/WSL.

## Operating Rule

- Treat PowerShell as the transport layer.
- Use `apply_patch` for file edits.
- Use `wsl-run '<linux command>'` for command execution.
- Keep commands Linux-native inside the quoted command string.

Examples:

```powershell
wsl-run 'pwd && rg "needle" .'
wsl-run 'npm test'
wsl-run 'python3 script.py'
wsl-run 'git diff --stat'
```

## Why

This avoids recurring PowerShell differences around `&&`, environment variables, quoting, globbing, path separators, and GNU tool behavior. Codex can still launch from PowerShell, but the actual project commands run in WSL.

## Expected Global Helper

The helper should live at:

```text
C:\Users\<user>\.codex\tools\wsl-run.ps1
```

The PowerShell profile should expose:

```powershell
function wsl-run {
    & "$HOME\.codex\tools\wsl-run.ps1" @args
}
```

If `wsl-run` is unavailable in a future chat, use `scripts/install.ps1` from this plugin to install or refresh the global helper.
