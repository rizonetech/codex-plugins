#!/usr/bin/env bash
# Legacy ChromeMCP standalone installer.
#
# Codex plugin distribution is handled by the repository root installer:
#   powershell -ExecutionPolicy Bypass -File ./scripts/install-rizonetech-local.ps1
#
# From this plugin checkout (e.g. during dev / testing this legacy installer):
#   bash scripts/install.sh --from-source
#
# Uninstall:
#   bash scripts/install.sh --uninstall
#
# Env overrides:
#   CHROMEMCP_PREFIX        install dir (default: $XDG_DATA_HOME/chromemcp
#                           which is $HOME/.local/share/chromemcp by default)
#   CHROMEMCP_BIN_DIR       directory for the chromemcp symlink
#                           (default: $HOME/.local/bin)
set -euo pipefail

REPO_OWNER="${CHROMEMCP_REPO_OWNER:-rizonetech}"
REPO_NAME="${CHROMEMCP_REPO_NAME:-ChromeMCP}"
PREFIX="${CHROMEMCP_PREFIX:-${XDG_DATA_HOME:-$HOME/.local/share}/chromemcp}"
BIN_DIR="${CHROMEMCP_BIN_DIR:-$HOME/.local/bin}"

MODE="install"
WANT_TAG=""
FROM_SOURCE=""

for arg in "$@"; do
  case "$arg" in
    --upgrade)       MODE="upgrade" ;;
    --uninstall)     MODE="uninstall" ;;
    --from-source)   FROM_SOURCE=1 ;;
    --version)       echo "install.sh: --version requires an argument (e.g. --version=v0.1.1)" >&2; exit 64 ;;
    --version=*)     WANT_TAG="${arg#--version=}" ;;
    --prefix=*)      PREFIX="${arg#--prefix=}" ;;
    --bin-dir=*)     BIN_DIR="${arg#--bin-dir=}" ;;
    --help|-h)       sed -n '1,40p' "$0"; exit 0 ;;
    *)               echo "install.sh: unknown arg: $arg" >&2; exit 64 ;;
  esac
done

if [ "$MODE" != "uninstall" ] && [ "$FROM_SOURCE" = "0" ]; then
  cat >&2 <<'EOF'
ERROR: release-based ChromeMCP standalone install is not used by codex-plugins.

For Codex plugin setup, run this from the codex-plugins repository root:

  powershell -ExecutionPolicy Bypass -File ./scripts/install-rizonetech-local.ps1

For local ChromeMCP standalone development, run:

  bash scripts/install.sh --from-source
EOF
  exit 2
fi

# --- Prerequisite checks ---------------------------------------------------
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: missing prerequisite: $1" >&2
    echo "  Install $1 (apt: 'sudo apt install $1') and re-run." >&2
    exit 1
  fi
}

require_cmd bash
require_cmd curl
require_cmd tar
require_cmd sed
require_cmd readlink

if [ "$MODE" != "uninstall" ]; then
  require_cmd node
  NODE_MAJOR=$(node -e 'console.log(parseInt(process.versions.node.split(".")[0], 10))')
  if [ "$NODE_MAJOR" -lt 18 ]; then
    echo "ERROR: node >= 18.18 required; you have $(node -v)" >&2
    exit 1
  fi
  require_cmd npm
fi

# --- Uninstall path -------------------------------------------------------
if [ "$MODE" = "uninstall" ]; then
  if [ -L "$BIN_DIR/chromemcp" ]; then
    rm "$BIN_DIR/chromemcp"
    echo "Removed $BIN_DIR/chromemcp"
  fi
  if [ -d "$PREFIX" ]; then
    rm -rf "$PREFIX"
    echo "Removed $PREFIX"
  fi
  if systemctl --user list-unit-files --type=service 2>/dev/null | grep -q '^chromemcp.service'; then
    echo "Note: the chromemcp.service systemd unit is still installed."
    echo "  Run 'chromemcp disable' BEFORE uninstall next time, or remove manually:"
    echo "    systemctl --user disable --now chromemcp.service"
    echo "    rm ~/.config/systemd/user/chromemcp.service && systemctl --user daemon-reload"
  fi
  echo "chromemcp uninstalled."
  exit 0
fi

# --- Resolve source: tarball or in-tree -----------------------------------
WORKDIR="$(mktemp -d -t chromemcp-install-XXXXXX)"
trap 'rm -rf "$WORKDIR"' EXIT

if [ -n "$FROM_SOURCE" ]; then
  SOURCE_DIR="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
  echo "Installing from local source: $SOURCE_DIR"
  SOURCE_TYPE="local"
else
  # Discover the tag we want.
  if [ -z "$WANT_TAG" ]; then
    # Use GitHub API to find the latest release tag.
    LATEST_JSON="$WORKDIR/latest.json"
    if ! curl -fsSL "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest" -o "$LATEST_JSON"; then
      echo "ERROR: could not query GitHub API for latest release." >&2
      echo "  Either the network is down, the repo $REPO_OWNER/$REPO_NAME has no published release yet," >&2
      echo "  or you've hit the unauthenticated GitHub API rate limit (60/hr per IP)." >&2
      echo "  Workaround: clone the repo and run 'bash scripts/install.sh --from-source'." >&2
      exit 1
    fi
    WANT_TAG=$(sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' "$LATEST_JSON" | head -1)
    if [ -z "$WANT_TAG" ]; then
      echo "ERROR: could not parse latest tag from GitHub response." >&2
      head -20 "$LATEST_JSON" >&2 || true
      exit 1
    fi
  fi
  WANT_VERSION="${WANT_TAG#v}"

  # --upgrade short-circuits if the installed version equals the latest.
  if [ "$MODE" = "upgrade" ] && [ -r "$PREFIX/VERSION" ]; then
    CURRENT_VERSION="$(tr -d '\n\r ' < "$PREFIX/VERSION")"
    if [ "$CURRENT_VERSION" = "$WANT_VERSION" ]; then
      echo "Already up to date (installed: $CURRENT_VERSION, latest: $WANT_VERSION)."
      exit 0
    fi
    echo "Upgrading $CURRENT_VERSION -> $WANT_VERSION"
  fi

  echo "Downloading ChromeMCP $WANT_TAG..."
  TARBALL_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/$WANT_TAG/chromemcp-$WANT_VERSION.tar.gz"
  if ! curl -fsSL "$TARBALL_URL" -o "$WORKDIR/release.tar.gz"; then
    echo "ERROR: download failed: $TARBALL_URL" >&2
    exit 1
  fi
  mkdir -p "$WORKDIR/extracted"
  tar -xzf "$WORKDIR/release.tar.gz" -C "$WORKDIR/extracted"
  # The tarball is "chromemcp-VERSION/...". Find that one inner dir.
  SOURCE_DIR=$(find "$WORKDIR/extracted" -maxdepth 1 -mindepth 1 -type d | head -1)
  if [ -z "$SOURCE_DIR" ] || [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: tarball didn't contain a single top-level directory." >&2
    exit 1
  fi
  SOURCE_TYPE="release"
fi

# --- Install path: stage to $PREFIX --------------------------------------
echo "Install dir : $PREFIX"
echo "Bin dir     : $BIN_DIR"

mkdir -p "$PREFIX" "$BIN_DIR"

# Use rsync if available (preserves perms; --delete cleans removed files
# on upgrade). Fall back to a tar pipe so this works on minimal hosts.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude='.git' \
    --exclude='mcp/node_modules' \
    --exclude='mcp/logs' \
    --exclude='mcp/.playwright-mcp' \
    --exclude='mcp/demo-output' \
    --exclude='mcp/.playwright.pid' \
    --exclude='mcp/.logrotate.pid' \
    --exclude='__pycache__' \
    "$SOURCE_DIR/" "$PREFIX/"
else
  ( cd "$SOURCE_DIR" && tar --exclude='.git' --exclude='mcp/node_modules' \
        --exclude='mcp/logs' --exclude='mcp/.playwright-mcp' \
        --exclude='mcp/demo-output' --exclude='mcp/.playwright.pid' \
        --exclude='mcp/.logrotate.pid' --exclude='__pycache__' \
        -cf - . ) | ( cd "$PREFIX" && tar -xf - )
fi

# Make sure the wrappers are executable (rsync respects mode but a tar pipe
# may strip the +x bit if the source files lost it).
for f in chromemcp mcp-up mcp-down mcp-status mcp-enable mcp-disable \
         mcp-logs mcp-token bridge-check chrome setup-bridge; do
  [ -f "$PREFIX/$f" ] && chmod +x "$PREFIX/$f"
done
[ -f "$PREFIX/scripts/install.sh" ] && chmod +x "$PREFIX/scripts/install.sh"
[ -f "$PREFIX/scripts/install-codex-plugin.sh" ] && chmod +x "$PREFIX/scripts/install-codex-plugin.sh"
[ -f "$PREFIX/scripts/test-codex-plugin.sh" ] && chmod +x "$PREFIX/scripts/test-codex-plugin.sh"

# Drop a VERSION file derived from --version or VERSION file in source.
if [ -n "${WANT_VERSION:-}" ]; then
  echo "$WANT_VERSION" > "$PREFIX/VERSION"
elif [ ! -f "$PREFIX/VERSION" ] && [ -f "$SOURCE_DIR/VERSION" ]; then
  cp "$SOURCE_DIR/VERSION" "$PREFIX/VERSION"
fi

# Install MCP server deps.
if [ -f "$PREFIX/mcp/package.json" ]; then
  echo "Installing MCP server deps via npm ci..."
  ( cd "$PREFIX/mcp" && npm ci --no-audit --no-fund )
fi

# Symlink chromemcp into BIN_DIR. Refresh if it already points elsewhere.
ln -sfn "$PREFIX/chromemcp" "$BIN_DIR/chromemcp"
echo "Symlinked   : $BIN_DIR/chromemcp -> $PREFIX/chromemcp"

# PATH check: warn if BIN_DIR isn't on it.
case ":$PATH:" in
  *":$BIN_DIR:"*)
    ;;
  *)
    echo ""
    echo "NOTE: $BIN_DIR is not on your PATH. Add this line to your shell rc:"
    echo "  export PATH=\"$BIN_DIR:\$PATH\""
    ;;
esac

INSTALLED_VERSION="$( "$PREFIX/chromemcp" version 2>/dev/null || echo unknown )"
echo ""
echo "ChromeMCP $INSTALLED_VERSION installed."
echo ""
echo "Next steps (run from anywhere on PATH):"
echo "  chromemcp setup-bridge    # one-time, Windows-side, UAC required"
echo "  chromemcp chrome          # launch signed-in Chrome with CDP"
echo "  chromemcp up              # start the MCP server"
echo "  chromemcp token           # print the bearer token for your client config"
echo "  chromemcp test            # smoke test"
echo ""
echo "Optional (auto-restart + survives logout):"
echo "  chromemcp enable          # install the systemd user unit"
