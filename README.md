# Rizonetech Codex Plugins

Self-contained Codex marketplace for Rizonetech plugins.

This repository contains the plugin payloads and installer needed to develop and install the Rizonetech Codex plugins from one place.

## Plugins

- [ChromeMCP](https://github.com/rizonetech/ChromeMCP)
- [Bashlane](https://github.com/rizonetech/Bashlane)

## Install

From PowerShell:

```powershell
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
