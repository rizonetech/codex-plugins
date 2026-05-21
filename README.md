# Rizonetech Codex Plugins

Self-contained Codex marketplace for Rizonetech plugins.

This repository contains the plugin payloads and installer needed to develop and install the Rizonetech Codex plugins from one place.

## Plugins

- [ChromeMCP](plugins/chromemcp-browser)
- [Bashlane](plugins/bashlane)

## Requirements

- Windows 10/11 with WSL2
- A WSL distro with Node.js 18.18 or newer for ChromeMCP
- Google Chrome on Windows for ChromeMCP
- PowerShell 5.1 or newer
- Administrator approval for ChromeMCP's first bridge setup when prompted

## Install

Clone the repository, then run the installer from PowerShell at the repository
root:

```powershell
git clone https://github.com/rizonetech/codex-plugins.git
cd codex-plugins
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1
```

The installer creates:

```text
~/.codex/plugins/rizonetech-local/
  .agents/plugins/marketplace.json
  plugins/chromemcp-browser/
  plugins/bashlane/
```

It also updates `~/.codex/config.toml` to enable:

```toml
[plugins."chromemcp-browser@rizonetech-local"]
enabled = true

[plugins."bashlane@rizonetech-local"]
enabled = true
```

Both plugins are grouped under the `Rizonetech` category.

Restart Codex after installation so it reloads the local marketplace and MCP
definitions.

## ChromeMCP First Run

After installing the plugin and restarting Codex, start ChromeMCP from WSL:

```bash
cd /home/<user>/github/codex-plugins/plugins/chromemcp-browser
./mcp-up
./mcp-status
```

On a clean machine, `./mcp-up` may launch Chrome and prompt for administrator
approval to install the WSL-to-Windows bridge. Approve the UAC prompt. A healthy
setup reports:

```text
Endpoint: http://127.0.0.1:8931/healthz - OK
Visible interactions: enabled
CDP healthy: yes (...)
```

ChromeMCP focuses the visible ChromeMCP Chrome window before browser tool calls
by default. Set `MCP_VISIBLE_INTERACTIONS=0` before starting the server only if
you intentionally want background behavior.

## Bashlane First Run

The installer also installs the global `wsl-run` helper. New PowerShell sessions
can run:

```powershell
wsl-run 'pwd && uname -a'
```

## Layout

```text
plugins/
  chromemcp-browser/  # Codex plugin plus ChromeMCP MCP server/runtime
  bashlane/           # Codex plugin plus wsl-run installer/helper
scripts/
  install-rizonetech-local.ps1
```

Develop plugin changes directly in `plugins/`, then rerun the installer to refresh the local Codex marketplace.

## Clean Installs

The installer derives paths from its own location and from Codex defaults:

- Codex config: `$env:CODEX_HOME` or `$HOME\.codex`
- Codex plugin cache: `$HOME\.codex`, or the matching WSL home when the repo is run from `\\wsl.localhost\...`

Override either path when needed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1 `
  -CodexConfigHome "$HOME\.codex" `
  -CodexPluginHome "\\wsl.localhost\Ubuntu\home\you\.codex"
```

The installer also removes older `chromemcp-local` and `bashlane-local` marketplace folders unless `-KeepOldLocalMarketplaces` is provided.

## Browser Smoke Tests

The real browser smoke test is target-driven so this repository does not bake
in local app names, URLs, or credentials. Copy
`scripts/real-browser-smoke-targets.example.json` to a private location, point
it at your own `.secrets` files, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-real-browser.ps1 `
  -TargetsPath "\\wsl.localhost\Ubuntu\path\to\your-targets.json"
```

The test brings the ChromeMCP window forward before browser actions by default
so the run is visible. Pass `-NoVisible` only when you intentionally want a
background smoke run.
