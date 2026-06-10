# Rizonetech Codex Plugins

Three Codex plugins for Windows/WSL2 development — ChromeMCP browser automation,
WSL command routing, and guarded overnight todo runs.

## Plugins

| Plugin | Description |
|---|---|
| [chromemcp-browser](plugins/chromemcp-browser) | Thin client for [ChromeMCP](https://github.com/rizonetech/ChromeMCP) — drive a real, signed-in Windows Chrome from Codex over MCP |
| [bashlane](plugins/bashlane) | Route Codex command work from PowerShell into WSL via `wsl-run` |
| [overnight-runner](plugins/overnight-runner) | State guard for long autonomous todo runs — adversarial review, slice gates, ChromeMCP verification, finish checks |

## Install

From PowerShell at the repo root:

```powershell
git clone https://github.com/rizonetech/codex-plugins.git
cd codex-plugins
powershell -ExecutionPolicy Bypass -File ./scripts/install-rizonetech-local.ps1
```

Restart Codex after installation so it picks up the local marketplace and MCP config.

## What Gets Installed

```text
~/.codex/plugins/rizonetech-local/
  plugins/chromemcp-browser/
  plugins/bashlane/
  plugins/overnight-runner/
~/.codex/tools/
  chromemcp-run
  overnight-runner
  wsl-run.ps1
```

The installer also enables all three plugins in `~/.codex/config.toml` and
removes legacy `chromemcp-local` / `bashlane-local` marketplace folders.

## ChromeMCP

The `chromemcp-browser` plugin is the thin model-facing layer only. The
infrastructure (Playwright MCP server, auth proxy, Windows bridge, systemd unit)
installs separately to `~/ChromeMCP`:

```bash
git clone https://github.com/rizonetech/ChromeMCP ~/github/ChromeMCP
bash ~/github/ChromeMCP/scripts/install.sh --from-source
# or the release one-liner:
# curl -fsSL https://raw.githubusercontent.com/rizonetech/ChromeMCP/main/scripts/install.sh | bash
chromemcp enable && chromemcp test
```

See [github.com/rizonetech/ChromeMCP](https://github.com/rizonetech/ChromeMCP)
for setup, security model, and troubleshooting.

## Requirements

- Windows 10/11 with WSL2
- PowerShell 5.1 or newer
- Google Chrome on Windows (for chromemcp-browser)

## License

MIT
