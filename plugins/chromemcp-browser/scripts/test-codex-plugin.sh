#!/usr/bin/env bash
# Regression tests for the repo-local Codex plugin wrapper and installer.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file() {
  [ -f "$1" ] || fail "expected file: $1"
}

assert_contains() {
  local needle="$1"
  local file="$2"
  grep -qF "$needle" "$file" || fail "expected '$needle' in $file"
}

assert_not_contains() {
  local needle="$1"
  local file="$2"
  ! grep -qF "$needle" "$file" || fail "did not expect '$needle' in $file"
}

python3 - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
for rel in [
    ".agents/plugins/marketplace.json",
    "plugins/chromemcp-browser/.codex-plugin/plugin.json",
    "plugins/chromemcp-browser/.codex-plugin/icon.png",
    "plugins/chromemcp-browser/.codex-plugin/icon.svg",
    "plugins/chromemcp-browser/.mcp.json",
]:
    path = root / rel
    if rel.endswith(".json"):
        json.loads(path.read_text())
    else:
        assert path.is_file(), rel

manifest = json.loads((root / "plugins/chromemcp-browser/.codex-plugin/plugin.json").read_text())
assert manifest["name"] == "chromemcp-browser"
assert manifest["skills"] == "./skills/"
assert manifest["mcpServers"] == "./.mcp.json"
assert manifest["interface"]["composerIcon"] == "./.codex-plugin/icon.png"
assert manifest["interface"]["logo"] == "./.codex-plugin/icon.svg"

marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text())
plugins = {p["name"]: p for p in marketplace["plugins"]}
assert plugins["chromemcp-browser"]["source"]["path"] == "./plugins/chromemcp-browser"
assert plugins["chromemcp-browser"]["policy"]["installation"] == "AVAILABLE"

mcp = json.loads((root / "plugins/chromemcp-browser/.mcp.json").read_text())
server = mcp["mcpServers"]["chromemcp-playwright"]
assert server["type"] == "http"
assert server["url"] == "http://localhost:8931/mcp"
assert server["headers"]["Authorization"] == "Bearer <TOKEN>"
PY

help_text="$(bash chromemcp help)"
case "$help_text" in *codex-plugin-install*) ;; *) fail "chromemcp help does not expose codex-plugin-install" ;; esac
case "$help_text" in *codex-plugin-test*) ;; *) fail "chromemcp help does not expose codex-plugin-test" ;; esac

tmp="$(mktemp -d -t chromemcp-plugin-test-XXXXXX)"
trap 'rm -rf "$tmp"' EXIT

export HOME="$tmp/home"
export XDG_CONFIG_HOME="$tmp/config"
export CODEX_CONFIG="$tmp/codex/config.toml"
mkdir -p "$HOME" "$XDG_CONFIG_HOME/chromemcp" "$(dirname "$CODEX_CONFIG")"
printf '%s\n' '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef' \
  > "$XDG_CONFIG_HOME/chromemcp/token"
chmod 600 "$XDG_CONFIG_HOME/chromemcp/token"

cat > "$CODEX_CONFIG" <<'EOF'
# Existing user settings must survive.
model = "gpt-5.5"

[marketplaces.chromemcp-local]
source_type = "local"
source = '\\?\UNC\wsl.localhost\Ubuntu\old\ChromeMCP'

[plugins."chromemcp-browser@chromemcp-local"]
enabled = false
EOF

bash scripts/install-codex-plugin.sh >"$tmp/install.out"

install_root="$HOME/.codex/plugins/chromemcp-local"
installed_plugin="$install_root/plugins/chromemcp-browser"
installed_mcp="$installed_plugin/.mcp.json"

assert_file "$install_root/.agents/plugins/marketplace.json"
assert_file "$installed_plugin/.codex-plugin/plugin.json"
assert_file "$installed_plugin/.codex-plugin/icon.png"
assert_file "$installed_plugin/.codex-plugin/icon.svg"
assert_file "$installed_mcp"

token="$(tr -d '\n\r ' < "$XDG_CONFIG_HOME/chromemcp/token")"
[ "${#token}" -ge 32 ] || fail "expected generated auth token"

assert_contains "source_type = \"local\"" "$CODEX_CONFIG"
assert_contains ".codex\\plugins\\chromemcp-local" "$CODEX_CONFIG"
assert_contains "[plugins.\"chromemcp-browser@chromemcp-local\"]" "$CODEX_CONFIG"
assert_contains "enabled = true" "$CODEX_CONFIG"
assert_not_contains "\\old\\ChromeMCP" "$CODEX_CONFIG"
assert_contains "model = \"gpt-5.5\"" "$CODEX_CONFIG"

assert_contains "Bearer $token" "$installed_mcp"
assert_not_contains "<TOKEN>" "$installed_mcp"
assert_contains "http://localhost:8931/mcp" "$installed_mcp"

python3 - "$install_root" "$installed_mcp" <<'PY'
import json
import sys
from pathlib import Path

install_root = Path(sys.argv[1])
installed_mcp = Path(sys.argv[2])
json.loads((install_root / ".agents/plugins/marketplace.json").read_text())
manifest = json.loads((install_root / "plugins/chromemcp-browser/.codex-plugin/plugin.json").read_text())
assert manifest["interface"]["composerIcon"] == "./.codex-plugin/icon.png"
assert manifest["interface"]["logo"] == "./.codex-plugin/icon.svg"
server = json.loads(installed_mcp.read_text())["mcpServers"]["chromemcp-playwright"]
assert server["headers"]["Authorization"].startswith("Bearer ")
PY

assert_contains "<TOKEN>" plugins/chromemcp-browser/.mcp.json

echo "PASS codex plugin metadata and installer"
