# chromemcp-browser (Codex plugin)

Thin Codex plugin for [ChromeMCP](https://github.com/rizonetech/ChromeMCP) — drive a
real, signed-in Windows Chrome from WSL2 over MCP.

This plugin ships only the model-facing layer: the `chromemcp-browser` skill, the MCP
endpoint config (`.mcp.json`), and the `bin/chromemcp-run` evidence wrapper. The
infrastructure (Playwright MCP server, auth proxy, Windows bridge, systemd unit)
installs separately to `~/ChromeMCP`:

    git clone https://github.com/rizonetech/ChromeMCP ~/github/ChromeMCP
    bash ~/github/ChromeMCP/scripts/install.sh --from-source
    chromemcp enable && chromemcp test

See the ChromeMCP repo for setup, security model, and troubleshooting.
