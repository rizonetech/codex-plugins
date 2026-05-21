# Bashlane Codex Plugin

This plugin keeps Codex usable when a chat is launched through PowerShell but the real project work belongs in WSL.

The rule is simple:

- edit files with Codex tools such as `apply_patch`
- run command-line work through `wsl-run '<linux command>'`
- let PowerShell act as the launch tube, not the shell semantics

## Install the helper

From PowerShell:

```powershell
.\scripts\install.ps1
```

The installer copies `scripts/wsl-run.ps1` to:

```text
%USERPROFILE%\.codex\tools\wsl-run.ps1
```

It also adds a `wsl-run` function to both modern PowerShell and Windows PowerShell profile locations.

## Usage

```powershell
wsl-run 'pwd && rg "something" .'
wsl-run 'npm test'
wsl-run 'python3 script.py'
wsl-run 'git diff --stat'
```

The helper maps either Windows drive paths such as `C:\Users\...` or WSL UNC paths such as `\\wsl.localhost\Ubuntu\home\...` into the corresponding WSL working directory before running `bash -lc`.
