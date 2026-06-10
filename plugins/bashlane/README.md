# Bashlane (Codex plugin)

Keep Codex usable when a chat launches through PowerShell but the real project
work belongs in WSL. PowerShell is the transport layer — Linux commands run
inside WSL, file edits stay in Codex tools.

## Quick Start

Install the global `wsl-run` helper from PowerShell:

```powershell
.\scripts\install.ps1
```

Then use it in any Codex chat:

```powershell
wsl-run 'pwd && rg "needle" .'
wsl-run 'npm test'
wsl-run 'python3 script.py'
wsl-run 'git diff --stat'
```

## What the Skill Does

The `wsl-run` skill tells Codex to route all command execution through
`wsl-run '<linux command>'` and use `apply_patch` for file edits. This avoids
PowerShell differences around `&&`, environment variables, quoting, globbing,
path separators, and GNU tool behavior. See [SKILL.md](skills/wsl-run/SKILL.md)
for the full ruleset.

## What Gets Installed

```text
%USERPROFILE%\.codex\tools\wsl-run.ps1
```

The installer also adds a `wsl-run` function to both the modern PowerShell and
Windows PowerShell profile locations. The helper maps Windows drive paths
(`C:\Users\...`) or WSL UNC paths (`\\wsl.localhost\Ubuntu\home\...`) to the
corresponding WSL working directory before running `bash -lc`.
