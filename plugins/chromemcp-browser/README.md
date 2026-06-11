# chromemcp-browser (Codex plugin)

Thin Codex plugin for [ChromeMCP](https://github.com/rizonetech/ChromeMCP) — drive a
real, signed-in Windows Chrome from WSL2 over MCP.

## Quick Start

Install the ChromeMCP infrastructure (one-time, from WSL):

```bash
# via npm (latest release)
npx -y @rizonetech/chromemcp install

# or the curl one-liner
curl -fsSL https://raw.githubusercontent.com/rizonetech/ChromeMCP/main/scripts/install.sh | bash

# or from source (contributors; enables `chromemcp update`)
git clone https://github.com/rizonetech/ChromeMCP ~/github/ChromeMCP
bash ~/github/ChromeMCP/scripts/install.sh --from-source
```

Then start and verify the Codex-isolated stack:

```bash
chromemcp codex-bridge
chromemcp codex-chrome
chromemcp codex-up
MCP_URL=http://127.0.0.1:8941/mcp MCP_TOKEN_PATH=~/.config/chromemcp-codex/token chromemcp test
```

A healthy setup reports `Endpoint: http://127.0.0.1:8941/healthz - OK` and
`CDP healthy: yes`, while the default Claude/shared ChromeMCP instance remains
on `8931/9222`.

## What the Skill Does

The `chromemcp-browser` skill instructs Codex to use the Codex-isolated
ChromeMCP Playwright MCP endpoint (`http://localhost:8941/mcp`) for authenticated browser
verification, CRUD testing, local web app testing, production smoke checks, and
screenshots. It enforces tab discipline, stable locators, CRUD loop coverage,
and visual QA rules. See [SKILL.md](skills/chromemcp-browser/SKILL.md) for the
full ruleset.

## bin/chromemcp-run

When no direct MCP tool is exposed in a chat, use the installed safe runner:

```bash
~/.codex/tools/chromemcp-run --url "https://example.com" --required --handoff --screenshot
```

The wrapper defaults to `MCP_URL=http://127.0.0.1:8941/mcp` and
`MCP_TOKEN_PATH=~/.config/chromemcp-codex/token`.

This provides structured browser evidence without raw CDP. Raw CDP/WebSocket
checks are diagnostic only and do not satisfy `browser_verification=passed`.

## What This Plugin Is Not

This plugin ships only the model-facing layer (skill + MCP config + evidence
wrapper). The infrastructure installs separately to `~/ChromeMCP`.
See [github.com/rizonetech/ChromeMCP](https://github.com/rizonetech/ChromeMCP).
