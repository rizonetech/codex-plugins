# Rizonetech Codex Plugins

Local Codex marketplace installer for Rizonetech plugins.

This repository does not combine plugin source code. It installs independent plugin repositories into one local Codex marketplace so they appear together in the Codex plugins interface.

## Plugins

- [ChromeMCP](https://github.com/rizonetech/ChromeMCP)
- [Bashlane](https://github.com/rizonetech/Bashlane)

## Install

From PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1
```

If sibling `ChromeMCP` or `Bashlane` repositories are missing, the installer clones them from GitHub before creating the local marketplace.

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
