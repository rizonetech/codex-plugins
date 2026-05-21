#!/usr/bin/env bash
# Install the local ChromeMCP Codex marketplace/plugin entries.
#
# The repository ships a placeholder .mcp.json so no secret is committed. This
# installer creates a user-local marketplace copy with a tokenized .mcp.json,
# then points Codex at that generated marketplace root.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"

if ! command -v wslpath >/dev/null 2>&1; then
  echo "ERROR: install-codex-plugin.sh must run inside WSL for this repository layout." >&2
  exit 1
fi

WIN_ROOT="$(wslpath -w "$ROOT")"
if [[ "$WIN_ROOT" == \\\\wsl.localhost\\* ]]; then
  WIN_ROOT="\\\\?\\UNC\\${WIN_ROOT#\\\\}"
fi

MARKETPLACE_ROOT="${CODEX_CHROMEMCP_MARKETPLACE_ROOT:-${CODEX_PLUGIN_HOME:-$HOME/.codex/plugins}/chromemcp-local}"
PLUGIN_DST="$MARKETPLACE_ROOT/plugins/chromemcp-browser"
case "$MARKETPLACE_ROOT" in
  ""|"/"|"$HOME"|"$HOME/.codex"|"$HOME/.codex/plugins")
    echo "ERROR: refusing unsafe Codex plugin marketplace root: ${MARKETPLACE_ROOT:-<empty>}" >&2
    exit 1
    ;;
esac
WIN_MARKETPLACE_ROOT="$(wslpath -w "$MARKETPLACE_ROOT")"
if [[ "$WIN_MARKETPLACE_ROOT" == \\\\wsl.localhost\\* ]]; then
  WIN_MARKETPLACE_ROOT="\\\\?\\UNC\\${WIN_MARKETPLACE_ROOT#\\\\}"
fi

TOKEN="$("$ROOT/mcp-token" | tr -d '\n\r ')"
if [ "${#TOKEN}" -lt 32 ]; then
  echo "ERROR: generated token is unexpectedly short." >&2
  exit 1
fi

if [ -n "${CODEX_CONFIG:-}" ]; then
  CONFIG="$CODEX_CONFIG"
elif [ -n "${USERPROFILE:-}" ] && [ -d "$(wslpath -u "$USERPROFILE" 2>/dev/null || true)" ]; then
  CONFIG="$(wslpath -u "$USERPROFILE")/.codex/config.toml"
else
  WIN_USERPROFILE="$(
    powershell.exe -NoProfile -Command '[Console]::OutputEncoding=[Text.Encoding]::UTF8; $env:USERPROFILE' 2>/dev/null \
      | tr -d '\r' \
      | tail -n 1
  )"
  if [ -z "$WIN_USERPROFILE" ]; then
    echo "ERROR: Could not resolve the Windows user profile for Codex config." >&2
    exit 1
  fi
  CONFIG="$(wslpath -u "$WIN_USERPROFILE")/.codex/config.toml"
fi

mkdir -p "$(dirname "$CONFIG")"
touch "$CONFIG"

mkdir -p "$MARKETPLACE_ROOT/.agents/plugins" "$MARKETPLACE_ROOT/plugins"
rm -rf "$PLUGIN_DST"
tar -C "$ROOT/plugins" -cf - chromemcp-browser | tar -C "$MARKETPLACE_ROOT/plugins" -xf -
cp "$ROOT/.agents/plugins/marketplace.json" "$MARKETPLACE_ROOT/.agents/plugins/marketplace.json"
chmod -R u+rwX,go-rwx "$MARKETPLACE_ROOT"

cat > "$PLUGIN_DST/.mcp.json" <<EOF
{
  "mcpServers": {
    "chromemcp-playwright": {
      "type": "http",
      "url": "http://localhost:8931/mcp",
      "headers": {
        "Authorization": "Bearer $TOKEN"
      },
      "note": "Local ChromeMCP Playwright MCP server. Start it with $ROOT/mcp-up before use. Token generated from $ROOT/mcp-token. Re-run scripts/install-codex-plugin.sh after rotating the token."
    }
  }
}
EOF
chmod 600 "$PLUGIN_DST/.mcp.json"

TMP_CONFIG="$(mktemp -t chromemcp-codex-config-XXXXXX)"
export CHROMEMCP_CODEX_SOURCE="$WIN_MARKETPLACE_ROOT"
awk '
  function flush_section() {
    if (in_marketplace) {
      if (!saw_source_type) print "source_type = \"local\""
      if (!saw_source) print "source = '\''" source "'\''"
    }
    if (in_plugin) {
      if (!saw_enabled) print "enabled = true"
    }
    in_marketplace = 0
    in_plugin = 0
  }

  BEGIN {
    source = ENVIRON["CHROMEMCP_CODEX_SOURCE"]
  }

  /^\[/ {
    flush_section()
    if ($0 == "[marketplaces.chromemcp-local]") {
      in_marketplace = 1
      saw_marketplace = 1
      saw_source_type = 0
      saw_source = 0
      print
      next
    }
    if ($0 == "[plugins.\"chromemcp-browser@chromemcp-local\"]") {
      in_plugin = 1
      saw_plugin = 1
      saw_enabled = 0
      print
      next
    }
  }

  in_marketplace && /^[[:space:]]*source_type[[:space:]]*=/ {
    print "source_type = \"local\""
    saw_source_type = 1
    next
  }

  in_marketplace && /^[[:space:]]*source[[:space:]]*=/ {
    print "source = '\''" source "'\''"
    saw_source = 1
    next
  }

  in_plugin && /^[[:space:]]*enabled[[:space:]]*=/ {
    print "enabled = true"
    saw_enabled = 1
    next
  }

  { print }

  END {
    flush_section()
    if (!saw_marketplace) {
      print ""
      print "# ChromeMCP local Codex marketplace."
      print "[marketplaces.chromemcp-local]"
      print "source_type = \"local\""
      print "source = '\''" source "'\''"
    }
    if (!saw_plugin) {
      print ""
      print "[plugins.\"chromemcp-browser@chromemcp-local\"]"
      print "enabled = true"
    }
  }
' "$CONFIG" > "$TMP_CONFIG"
cat "$TMP_CONFIG" > "$CONFIG"
rm -f "$TMP_CONFIG"

echo "Installed ChromeMCP Codex plugin entries in:"
echo "  $CONFIG"
echo
echo "Synced tokenized local plugin marketplace to:"
echo "  $MARKETPLACE_ROOT"
echo
echo "Repository marketplace source remains available for development:"
echo "  $WIN_ROOT"
echo
echo "Next:"
echo "  1. Restart Codex."
echo "  2. Start ChromeMCP: $ROOT/mcp-up"
echo "  3. Verify it:       bash $ROOT/mcp/test.sh"
echo "  4. After token rotation, re-run this installer so Codex gets the new token."
