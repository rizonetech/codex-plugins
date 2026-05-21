#!/usr/bin/env bash
# Smoke test for the running Playwright MCP server.
# Verifies initialize -> initialized -> browser_tabs -> browser_snapshot through
# the supported Python client module.
set -euo pipefail

ROOT="$(dirname "$(dirname "$(readlink -f "$0")")")"
cd "$ROOT"

python3 -m mcp.client.cli smoke

echo
echo "All checks passed. The MCP server can drive your Chrome."
