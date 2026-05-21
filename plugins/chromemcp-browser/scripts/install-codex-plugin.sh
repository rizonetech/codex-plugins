#!/usr/bin/env bash
# Compatibility wrapper for the old ChromeMCP-only command.
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/../.." && pwd)"
INSTALLER="$REPO_ROOT/scripts/install-rizonetech-local.ps1"

if [ ! -f "$INSTALLER" ]; then
  echo "ERROR: Rizonetech installer not found: $INSTALLER" >&2
  echo "Run this from the codex-plugins monorepo, or install with scripts/install-rizonetech-local.ps1." >&2
  exit 1
fi

if ! command -v powershell.exe >/dev/null 2>&1 || ! command -v wslpath >/dev/null 2>&1; then
  echo "ERROR: this compatibility installer must run inside WSL with powershell.exe available." >&2
  exit 1
fi

exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w "$INSTALLER")" "$@"
