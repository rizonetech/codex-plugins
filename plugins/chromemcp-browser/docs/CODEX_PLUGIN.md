# ChromeMCP Codex Plugin

ChromeMCP is distributed for Codex from the `rizonetech/codex-plugins` monorepo. The plugin wrapper lives in `plugins/chromemcp-browser`, declares the local HTTP MCP endpoint, and ships agent instructions for reliable Chrome-backed browser testing.

## Install From A Local Clone

From PowerShell at the `codex-plugins` repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1
```

Restart Codex after the installer updates `~/.codex/config.toml`. The plugin exposes the MCP server as `chromemcp-playwright`.

The installer does two things:

- Generates or reuses the ChromeMCP bearer token from `./mcp-token`.
- Creates a user-local Rizonetech marketplace copy at `~/.codex/plugins/rizonetech-local/` with a tokenized `.mcp.json`.

The tracked repository plugin keeps `Authorization: Bearer <TOKEN>` on purpose so secrets never land in git. Re-run the installer after `./mcp-token --rotate` so Codex receives the new token.

Then start and test ChromeMCP from WSL:

```bash
cd /path/to/codex-plugins/plugins/chromemcp-browser
./mcp-up
bash mcp/test.sh
```

To validate the plugin packaging and installer without touching your real Codex config:

```bash
bash scripts/test-codex-plugin.sh
```

## Manual Codex Config

If you prefer to edit the config yourself, add the generated local marketplace and enable both Rizonetech plugins:

```toml
[marketplaces.rizonetech-local]
source_type = "local"
source = '<generated Windows UNC path to ~/.codex/plugins/rizonetech-local>'

[plugins."chromemcp-browser@rizonetech-local"]
enabled = true

[plugins."bashlane@rizonetech-local"]
enabled = true
```

Use the actual generated marketplace path for `source`. For WSL paths, `wslpath -w "$HOME/.codex/plugins/rizonetech-local"` prints the Windows UNC path.

## Distribution Notes

- Keep `.agents/plugins/marketplace.json` in the repository root. It makes the Rizonetech plugins discoverable when this repository is used as a local Codex marketplace.
- Keep `plugins/chromemcp-browser/.codex-plugin/plugin.json`, `.mcp.json`, and `skills/` together. The tracked `.mcp.json` must keep the `<TOKEN>` placeholder; the installer writes the real token only into the user-local marketplace copy.
- The plugin endpoint is intentionally `http://localhost:8931/mcp`; users start the server with `./mcp-up`.
- A fresh Codex process is required after plugin installation because Codex loads marketplace and MCP definitions during startup.
