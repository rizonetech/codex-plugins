#!/usr/bin/env bash
# Install the overnight-runner engine + wrapper into the Codex runtime.
#
#   engine  -> ~/.codex/overnight-runner/overnight-runner.py  (+ LICENSE, VERSION, tests)
#   wrapper -> ~/.codex/tools/overnight-runner                (on Codex's tool path)
#
# Idempotent: safe to re-run after a plugin update to refresh both copies.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
ENGINE_SRC="$PLUGIN_ROOT/.codex/scripts/overnight-runner.py"
WRAPPER_SRC="$PLUGIN_ROOT/bin/overnight-runner"

ENGINE_HOME="$HOME/.codex/overnight-runner"
TOOLS_DIR="$HOME/.codex/tools"

[ -f "$ENGINE_SRC" ]  || { echo "ERROR: engine not found at $ENGINE_SRC" >&2; exit 1; }
[ -f "$WRAPPER_SRC" ] || { echo "ERROR: wrapper not found at $WRAPPER_SRC" >&2; exit 1; }

mkdir -p "$ENGINE_HOME" "$TOOLS_DIR"

install -m 0755 "$ENGINE_SRC" "$ENGINE_HOME/overnight-runner.py"
for f in LICENSE VERSION; do
  [ -f "$PLUGIN_ROOT/$f" ] && install -m 0644 "$PLUGIN_ROOT/$f" "$ENGINE_HOME/$f"
done
if [ -d "$PLUGIN_ROOT/tests" ]; then
  mkdir -p "$ENGINE_HOME/tests"
  install -m 0644 "$PLUGIN_ROOT"/tests/*.py "$ENGINE_HOME/tests/" 2>/dev/null || true
fi

install -m 0755 "$WRAPPER_SRC" "$TOOLS_DIR/overnight-runner"

echo "Installed overnight-runner:"
echo "  engine  -> $ENGINE_HOME/overnight-runner.py"
echo "  wrapper -> $TOOLS_DIR/overnight-runner"
echo "Verify: overnight-runner --help  (or ~/.codex/tools/overnight-runner --help)"
