#!/usr/bin/env bash
# Regression tests for the ChromeMCP Codex plugin wrapper in the monorepo.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
REPO_ROOT="$(cd "$PLUGIN_ROOT/../.." && pwd)"
cd "$REPO_ROOT"

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
    "plugins/bashlane/.codex-plugin/plugin.json",
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

marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text())
plugins = {p["name"]: p for p in marketplace["plugins"]}
assert plugins["chromemcp-browser"]["source"]["path"] == "./plugins/chromemcp-browser"
assert plugins["bashlane"]["source"]["path"] == "./plugins/bashlane"

mcp = json.loads((root / "plugins/chromemcp-browser/.mcp.json").read_text())
server = mcp["mcpServers"]["chromemcp-playwright"]
assert server["type"] == "http"
assert server["url"] == "http://localhost:8931/mcp"
assert server["headers"]["Authorization"] == "Bearer <TOKEN>"
PY

help_text="$(bash plugins/chromemcp-browser/chromemcp help)"
case "$help_text" in *codex-plugin-install*) ;; *) fail "chromemcp help does not expose codex-plugin-install" ;; esac
case "$help_text" in *codex-plugin-test*) ;; *) fail "chromemcp help does not expose codex-plugin-test" ;; esac

if ! command -v powershell.exe >/dev/null 2>&1 || ! command -v wslpath >/dev/null 2>&1; then
  echo "SKIP installer simulation: powershell.exe/wslpath unavailable"
  exit 0
fi

tmp="$(mktemp -d -t rizonetech-plugin-test-XXXXXX)"
trap 'rm -rf "$tmp"' EXIT

config_home="$tmp/config-home"
plugin_home="$tmp/plugin-home"
mkdir -p "$config_home" "$plugin_home"
config_home_win="$(wslpath -w "$config_home")"
plugin_home_win="$(wslpath -w "$plugin_home")"

cat > "$config_home/config.toml" <<'EOF'
# Existing user settings must survive.
model = "gpt-5.5"

[marketplaces.chromemcp-local]
source_type = "local"
source = '\\?\UNC\wsl.localhost\Ubuntu\old\ChromeMCP'

[plugins."chromemcp-browser@chromemcp-local"]
enabled = false
EOF

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$REPO_ROOT/scripts/install-rizonetech-local.ps1")" \
  -CodexConfigHome "$config_home_win" \
  -CodexPluginHome "$plugin_home_win" \
  -SkipToolInstall \
  >"$tmp/install.out"

install_root="$plugin_home/plugins/rizonetech-local"
installed_plugin="$install_root/plugins/chromemcp-browser"
installed_mcp="$installed_plugin/.mcp.json"
config="$config_home/config.toml"

assert_file "$install_root/.agents/plugins/marketplace.json"
assert_file "$installed_plugin/.codex-plugin/plugin.json"
assert_file "$installed_plugin/.codex-plugin/icon.png"
assert_file "$installed_plugin/.codex-plugin/icon.svg"
assert_file "$install_root/plugins/bashlane/.codex-plugin/plugin.json"
assert_file "$installed_mcp"
assert_file "$installed_plugin/launcher/Focus-Chrome.ps1"
assert_file "$installed_plugin/mcp/auth-proxy.js"
assert_file "$installed_plugin/mcp-status"

assert_contains "[marketplaces.rizonetech-local]" "$config"
assert_contains "[plugins.\"chromemcp-browser@rizonetech-local\"]" "$config"
assert_contains "[plugins.\"bashlane@rizonetech-local\"]" "$config"
assert_contains "enabled = true" "$config"
assert_contains "model = \"gpt-5.5\"" "$config"
assert_not_contains "chromemcp-local" "$config"
assert_not_contains "\\old\\ChromeMCP" "$config"

assert_contains "http://localhost:8931/mcp" "$installed_mcp"
assert_not_contains "<TOKEN>" "$installed_mcp"
assert_contains "<TOKEN>" plugins/chromemcp-browser/.mcp.json
assert_contains "process.env.MCP_VISIBLE_INTERACTIONS !== '0'" "$installed_plugin/mcp/auth-proxy.js"
assert_contains "visibleInteractions" "$installed_plugin/mcp/auth-proxy.js"
assert_contains "Visible interactions:" "$installed_plugin/mcp-status"

python3 - "$install_root" "$installed_mcp" <<'PY'
import json
import sys
from pathlib import Path

install_root = Path(sys.argv[1])
installed_mcp = Path(sys.argv[2])
marketplace = json.loads((install_root / ".agents/plugins/marketplace.json").read_text())
plugins = {p["name"]: p for p in marketplace["plugins"]}
assert set(plugins) == {"chromemcp-browser", "bashlane"}
manifest = json.loads((install_root / "plugins/chromemcp-browser/.codex-plugin/plugin.json").read_text())
assert manifest["interface"]["category"] == "Rizonetech"
server = json.loads(installed_mcp.read_text())["mcpServers"]["chromemcp-playwright"]
assert server["headers"]["Authorization"].startswith("Bearer ")
PY

if curl -fsS --max-time 3 http://127.0.0.1:8931/healthz >"$tmp/healthz.json" 2>/dev/null; then
  python3 - "$tmp/healthz.json" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
visible = data.get("visibleInteractions")
assert visible, "healthz did not expose visibleInteractions"
assert visible.get("enabled") is True, "visible interactions are not enabled by default"
assert str(visible.get("focusScript", "")).endswith("launcher/Focus-Chrome.ps1")
PY
else
  echo "SKIP live visible-interactions health check: ChromeMCP server is not running"
fi

echo "PASS codex plugin metadata, monorepo installer, and visible defaults"
