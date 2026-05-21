#!/usr/bin/env bash
# Starts Playwright MCP behind a bearer-token auth proxy as a long-running
# HTTP/SSE service against the project's bridged Chrome. Idempotent.
#
# Topology:
#   client → http://$HOST:$PORT (auth-proxy.js, validates bearer token)
#                              └→ http://127.0.0.1:$UPSTREAM_PORT (@playwright/mcp)
#
# Env overrides:
#   PORT             (default 8931)        - public port (clients connect here)
#   HOST             (default 127.0.0.1)   - public bind interface
#   UPSTREAM_PORT    (default 8932)        - internal @playwright/mcp port
#   CDP_ENDPOINT     (auto)                - upstream Chrome CDP URL
#   MCP_AUTH_TOKEN   (auto)                - bearer token; auto-generated to
#                                            ~/.config/chromemcp/token if absent
#   MCP_NO_AUTH      (unset)               - set to '1' to disable auth entirely;
#                                            a warning is logged on every request
#   MCP_LOG_MAX_MB   (default 10)          - per-file size cap before rotation
#                                            (ad-hoc mode only; supervised mode
#                                            uses systemd journal which rotates
#                                            on its own)
#   MCP_LOG_KEEP     (default 5)           - rotated copies to retain
#                                            (.1 .. .MCP_LOG_KEEP)
#   MCP_CHROME_MIN_MAJOR (default 140)     - floor of the warn-free Chrome
#                                            version range
#   MCP_CHROME_MAX_MAJOR (default 150)     - ceiling of the warn-free range
#   MCP_VISIBLE_INTERACTIONS (default 1)   - focus the visible ChromeMCP
#                                            window before browser tool calls
#                                            so users can watch interactions.
#                                            Set to 0 to disable.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
PROJECT_ROOT="$(dirname "$(pwd)")"

# --foreground / -f: do not detach. Replaces this shell with auth-proxy.js
# via `exec` so the supervisor (systemd, pm2, ...) sees a single process.
# Skips PID-file management entirely — supervisor owns liveness.
FOREGROUND=0
for arg in "$@"; do
  case "$arg" in
    --foreground|-f) FOREGROUND=1 ;;
  esac
done

PORT="${PORT:-8931}"
HOST="${HOST:-127.0.0.1}"
UPSTREAM_PORT="${UPSTREAM_PORT:-8932}"

# Capture current WSL gateway IP. Used both for the default CDP endpoint
# AND for bridge-drift detection further down (we compare this to the IP
# baked into the Windows-side netsh portproxy entry).
WSLGW="$(ip route show | awk '/^default/ {print $3}')"
CDP_PORT="${CDP_PORT:-9222}"
if [ -z "${CDP_ENDPOINT:-}" ]; then
  CDP_ENDPOINT="http://${WSLGW}:${CDP_PORT}"
fi

PID_FILE="$(pwd)/.playwright.pid"
LOG_FILE="$(pwd)/logs/playwright-mcp.log"
LOGROTATE_PID_FILE="$(pwd)/.logrotate.pid"
MCP_URL="http://${HOST}:${PORT}/mcp"

MCP_LOG_MAX_MB="${MCP_LOG_MAX_MB:-10}"
MCP_LOG_KEEP="${MCP_LOG_KEEP:-5}"

# rotate_logs_now: if $LOG_FILE > threshold, shift .1..KEEP -> .2..KEEP+1, drop
# overflow, snapshot current into .1, and truncate the active file. Uses
# truncate (`: > "$LOG_FILE"`) instead of `mv` so the proxy's already-open
# append-mode FD keeps writing — Linux clamps the next append back to offset 0.
# We lose at most the bytes written during the cp window; for log rotation
# that's acceptable (same trade-off `logrotate copytruncate` makes).
rotate_logs_now() {
  local max_bytes size i
  max_bytes=$(( MCP_LOG_MAX_MB * 1024 * 1024 ))
  [ -s "$LOG_FILE" ] || return 0
  size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
  [ "$size" -gt "$max_bytes" ] || return 0
  for i in $(seq "$((MCP_LOG_KEEP - 1))" -1 1); do
    [ -f "$LOG_FILE.$i" ] && mv -f "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
  done
  # Drop anything beyond the retention window.
  for i in $(seq "$((MCP_LOG_KEEP + 1))" 99); do
    [ -f "$LOG_FILE.$i" ] || break
    rm -f "$LOG_FILE.$i"
  done
  cp "$LOG_FILE" "$LOG_FILE.1"
  : > "$LOG_FILE"
}

find_windows_exe() {
  local name="$1"
  local found
  found="$(command -v "$name" 2>/dev/null || true)"
  if [ -n "$found" ]; then
    printf '%s\n' "$found"
    return 0
  fi

  case "$name" in
    powershell.exe)
      for candidate in \
        /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe \
        /mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe
      do
        [ -x "$candidate" ] && printf '%s\n' "$candidate" && return 0
      done
      ;;
    cmd.exe)
      for candidate in \
        /mnt/c/Windows/System32/cmd.exe \
        /mnt/c/WINDOWS/System32/cmd.exe
      do
        [ -x "$candidate" ] && printf '%s\n' "$candidate" && return 0
      done
      ;;
  esac

  return 1
}

# --- Idempotency: if already running, just report and exit. ---------------
# Supervised mode owns liveness via systemd / pm2; skip the PID-file dance.
if [ "$FOREGROUND" = "0" ] && [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  if curl -s --max-time 2 "$MCP_URL" -o /dev/null --head 2>/dev/null \
     || curl -s --max-time 2 "http://${HOST}:${PORT}/" -o /dev/null 2>/dev/null; then
    echo "Playwright MCP already running (PID $(cat "$PID_FILE")) on ${MCP_URL}"
    exit 0
  fi
  echo "Stale PID file found; cleaning up."
  rm -f "$PID_FILE"
fi

# --- Pre-flight: verify upstream CDP is reachable. ------------------------
probe_cdp() {
  curl -s --max-time 4 "${CDP_ENDPOINT}/json/version" -o /dev/null
}

# WSL2 routing to the Windows-side portproxy can occasionally stall a fresh
# TCP connection. Retry a couple of times before declaring CDP unreachable
# so we don't trigger the auto-launch path on a flaky first probe.
initial_probe_cdp() {
  for i in 1 2 3; do
    probe_cdp && return 0
    sleep 0.3
  done
  return 1
}

# If CDP is down, try to auto-launch Chrome on Windows via the PowerShell
# launcher. The launcher is idempotent (no-op if Chrome is already up), so
# this is safe to call speculatively. Skip with MCP_NO_AUTO_CHROME=1.
if ! initial_probe_cdp; then
  POWERSHELL_EXE="$(find_windows_exe powershell.exe || true)"
  if [ -z "${MCP_NO_AUTO_CHROME:-}" ] && [ -n "$POWERSHELL_EXE" ]; then
    LAUNCHER_PS1="$(wslpath -w "${PROJECT_ROOT}/launcher/Launch-Chrome.ps1" 2>/dev/null || true)"
    if [ -n "$LAUNCHER_PS1" ]; then
      echo "Chrome CDP not reachable - auto-launching Chrome on Windows..."
      "$POWERSHELL_EXE" -NoProfile -ExecutionPolicy Bypass -File "$LAUNCHER_PS1" >/dev/null || true
      # Allow a few seconds for the bridge to forward the freshly-started Chrome.
      for i in $(seq 1 15); do
        probe_cdp && break
        sleep 0.5
      done
    fi
  fi
fi

# Read the Windows-side netsh portproxy listenaddress(es) on $CDP_PORT.
# Stdout: zero or more IPs, one per line. Empty stdout = bridge not installed.
# Stderr/exit-non-zero: interop broken — caller should treat as "unknown".
get_bridge_listenaddrs() {
  local pwsh
  pwsh="$(find_windows_exe powershell.exe || true)"
  [ -z "$pwsh" ] && return 1
  "$pwsh" -NoProfile -Command 'netsh interface portproxy show v4tov4' 2>/dev/null \
    | tr -d '\r' \
    | awk -v p="$CDP_PORT" '$2 == p && $1 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ {print $1}' \
    | sort -u
}

# Returns:
#   0 + stdout="drift"    bridge exists but listenaddress != current gateway
#   0 + stdout="missing"  no portproxy entry on the port
#   0 + stdout="ok"       bridge listenaddress matches current gateway
#   1                     could not determine (interop failure)
classify_bridge_state() {
  local addrs
  addrs="$(get_bridge_listenaddrs)" || return 1
  if [ -z "$addrs" ]; then
    printf 'missing\n'
    return 0
  fi
  if printf '%s\n' "$addrs" | grep -qxF "$WSLGW" \
     && [ "$(printf '%s\n' "$addrs" | wc -l)" = "1" ]; then
    printf 'ok\n'
    return 0
  fi
  printf 'drift\n'
  return 0
}

# If CDP is STILL unreachable, the most likely remaining cause is bridge
# state: either it was never installed, or WSL2 reassigned the gateway IP
# since it was last installed (drift). Both cases are fixed by re-running
# Setup-Bridge.cmd, which self-elevates with a UAC prompt. One-time per
# machine in the install case; once per drift event otherwise. Skip with
# MCP_NO_AUTO_BRIDGE=1.
if ! probe_cdp; then
  CMD_EXE="$(find_windows_exe cmd.exe || true)"
  if [ -z "${MCP_NO_AUTO_BRIDGE:-}" ] && [ -n "$CMD_EXE" ]; then
    BRIDGE_CMD="$(wslpath -w "${PROJECT_ROOT}/Setup-Bridge.cmd" 2>/dev/null || true)"
    if [ -n "$BRIDGE_CMD" ]; then
      STATE="$(classify_bridge_state 2>/dev/null || echo unknown)"
      case "$STATE" in
        drift)
          STALE="$(get_bridge_listenaddrs 2>/dev/null | tr '\n' ' ')"
          echo "Bridge drift detected: WSL gateway is now ${WSLGW}, bridge points at ${STALE}- refreshing..."
          echo "  Approve the UAC prompt on your Windows desktop to continue."
          "$CMD_EXE" /c "$BRIDGE_CMD" /refresh </dev/null >/dev/null 2>&1 || true
          ;;
        missing|unknown)
          echo "Installing the WSL<->Windows bridge (one-time per machine)..."
          echo "  Approve the UAC prompt on your Windows desktop to continue."
          "$CMD_EXE" /c "$BRIDGE_CMD" </dev/null >/dev/null 2>&1 || true
          ;;
        ok)
          # Bridge state matches current IP yet CDP still failing — Chrome
          # itself must be down or CDP port collision. Fall through to the
          # error path; running the bridge installer again wouldn't help.
          ;;
      esac
      if [ "$STATE" != "ok" ]; then
        echo "  Waiting up to 90s for the bridge to come live..."
        for i in $(seq 1 180); do
          probe_cdp && break
          sleep 0.5
        done
      fi
    fi
  fi
fi

if ! probe_cdp; then
  echo "ERROR: Chrome CDP not reachable at ${CDP_ENDPOINT}" >&2
  echo "  Auto-launch + auto-bridge attempted; CDP still unreachable." >&2
  echo "  Possible causes:" >&2
  echo "    * UAC denied or timed out (re-run ./mcp-up to retry)" >&2
  echo "    * Chrome failed to start on Windows" >&2
  echo "    * MCP_NO_AUTO_CHROME or MCP_NO_AUTO_BRIDGE is set in the env" >&2
  echo "  Manual fallback from project root ${PROJECT_ROOT}:" >&2
  echo "    ./chrome           # launch Chrome with --remote-debugging-port=${CDP_PORT}" >&2
  echo "    ./setup-bridge     # one-time, UAC required, exposes ${CDP_PORT} to WSL" >&2
  echo "    ./bridge-check     # diagnose whether drift is the cause" >&2
  exit 1
fi

# Bridge confirmed live by probe — surface that explicitly in the startup
# log so the user can see at a glance which IP:port the bridge is pinned to.
echo "Bridge OK at ${WSLGW}:${CDP_PORT}"

# --- Chrome version check (G9) --------------------------------------------
# Read the Browser field from CDP /json/version, parse the major version,
# and warn (without failing) if it's outside the known-good range. Chrome
# auto-updates on Windows; a breaking CDP change between two chrome.exe
# releases would otherwise surface as opaque tool-call errors. This
# surfaces the version proactively so the user can correlate.
MCP_CHROME_MIN_MAJOR="${MCP_CHROME_MIN_MAJOR:-140}"
MCP_CHROME_MAX_MAJOR="${MCP_CHROME_MAX_MAJOR:-150}"
CHROME_FULL_VER="$(curl -fsS --max-time 3 "${CDP_ENDPOINT}/json/version" 2>/dev/null \
  | sed -n 's/.*"Browser":[[:space:]]*"\([^"]*\)".*/\1/p' \
  | head -1)"
if [ -n "$CHROME_FULL_VER" ]; then
  # e.g. "Chrome/148.0.7778.98" or "HeadlessChrome/148.0.7778.98"
  CHROME_NUM="${CHROME_FULL_VER##*/}"
  CHROME_MAJOR="${CHROME_NUM%%.*}"
  if [ -n "$CHROME_MAJOR" ] \
     && [ "$CHROME_MAJOR" -ge "$MCP_CHROME_MIN_MAJOR" ] \
     && [ "$CHROME_MAJOR" -le "$MCP_CHROME_MAX_MAJOR" ]; then
    echo "Chrome   : ${CHROME_FULL_VER} (supported range: ${MCP_CHROME_MIN_MAJOR}-${MCP_CHROME_MAX_MAJOR})"
  else
    echo "Chrome   : ${CHROME_FULL_VER}" >&2
    echo "  WARN: Chrome major ${CHROME_MAJOR} is outside the verified range ${MCP_CHROME_MIN_MAJOR}-${MCP_CHROME_MAX_MAJOR}." >&2
    echo "  Tool calls may behave unexpectedly if upstream CDP changed. Set" >&2
    echo "  MCP_CHROME_MIN_MAJOR / MCP_CHROME_MAX_MAJOR to silence this warning" >&2
    echo "  once you've verified the suite at this version, or see docs/chrome-pinning.md" >&2
    echo "  for how to pin Chrome to a known-good major on Windows Enterprise." >&2
  fi
else
  echo "Chrome   : version probe failed (CDP /json/version returned no Browser field)" >&2
fi

# --- Install deps if missing (deterministic via package-lock.json). -------
if [ ! -d node_modules ]; then
  echo "Installing MCP server packages (one-time)..."
  npm ci --silent
fi

# --- Launch detached. -----------------------------------------------------
mkdir -p logs
echo "Starting Playwright MCP behind auth proxy..."
echo "  upstream CDP : ${CDP_ENDPOINT}"
echo "  listening on : ${MCP_URL}"

# Rotate at start so a fresh session begins on a clean(er) file. Without this,
# a user who bounces the server after a long-running session would still write
# into the old huge log until the runtime rotator's next tick.
rotate_logs_now
if [ "${MCP_NO_AUTH:-}" = "1" ]; then
  echo "  auth         : DISABLED (MCP_NO_AUTH=1 — any local process can drive Chrome)"
else
  TOKEN_PATH="${MCP_TOKEN_PATH:-${XDG_CONFIG_HOME:-$HOME/.config}/chromemcp/token}"
  echo "  auth         : bearer token (clients must send 'Authorization: Bearer <token>')"
  echo "  token path   : ${TOKEN_PATH}"
fi

if [ "$FOREGROUND" = "1" ]; then
  # Supervised mode: replace this shell with auth-proxy.js so the supervisor
  # gets a single, signal-deliverable PID. Logs go to stdout/stderr (which
  # systemd captures via the journal, or the parent shell's pipes).
  # No file-based log rotation here — journald handles its own rotation.
  exec env \
    MCP_PUBLIC_PORT="$PORT" \
    MCP_PUBLIC_HOST="$HOST" \
    MCP_UPSTREAM_PORT="$UPSTREAM_PORT" \
    MCP_UPSTREAM_HOST="127.0.0.1" \
    MCP_CDP_ENDPOINT="$CDP_ENDPOINT" \
    ${MCP_AUTH_TOKEN:+MCP_AUTH_TOKEN="$MCP_AUTH_TOKEN"} \
    ${MCP_NO_AUTH:+MCP_NO_AUTH="$MCP_NO_AUTH"} \
    ${MCP_TOKEN_PATH:+MCP_TOKEN_PATH="$MCP_TOKEN_PATH"} \
    node "$(pwd)/auth-proxy.js"
fi

# nohup + setsid + & = fully detach, survives this shell exiting. The proxy
# itself spawns the @playwright/mcp child with stdio inherited so its logs
# end up in the same log file as the proxy.
setsid nohup env \
  MCP_PUBLIC_PORT="$PORT" \
  MCP_PUBLIC_HOST="$HOST" \
  MCP_UPSTREAM_PORT="$UPSTREAM_PORT" \
  MCP_UPSTREAM_HOST="127.0.0.1" \
  MCP_CDP_ENDPOINT="$CDP_ENDPOINT" \
  ${MCP_AUTH_TOKEN:+MCP_AUTH_TOKEN="$MCP_AUTH_TOKEN"} \
  ${MCP_NO_AUTH:+MCP_NO_AUTH="$MCP_NO_AUTH"} \
  ${MCP_TOKEN_PATH:+MCP_TOKEN_PATH="$MCP_TOKEN_PATH"} \
  node "$(pwd)/auth-proxy.js" \
  >> "$LOG_FILE" 2>&1 < /dev/null &
echo $! > "$PID_FILE"

# Runtime rotator. Ticks every ROTATE_INTERVAL seconds and runs the same
# rotate_logs_now logic via a re-shell so the env vars and function are
# available. Lives in its own session so `mcp-down` can kill it via the PID
# file without touching the proxy.
ROTATE_INTERVAL="${MCP_LOG_ROTATE_INTERVAL_SEC:-30}"
SELF_PATH="$(readlink -f "$0")"
setsid nohup bash -c '
  set -euo pipefail
  LOG_FILE='"$(printf %q "$LOG_FILE")"'
  MCP_LOG_MAX_MB='"$MCP_LOG_MAX_MB"'
  MCP_LOG_KEEP='"$MCP_LOG_KEEP"'
  ROTATE_INTERVAL='"$ROTATE_INTERVAL"'
  rotate_logs_now() {
    local max_bytes size i
    max_bytes=$(( MCP_LOG_MAX_MB * 1024 * 1024 ))
    [ -s "$LOG_FILE" ] || return 0
    size=$(stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    [ "$size" -gt "$max_bytes" ] || return 0
    for i in $(seq "$((MCP_LOG_KEEP - 1))" -1 1); do
      [ -f "$LOG_FILE.$i" ] && mv -f "$LOG_FILE.$i" "$LOG_FILE.$((i+1))"
    done
    for i in $(seq "$((MCP_LOG_KEEP + 1))" 99); do
      [ -f "$LOG_FILE.$i" ] || break
      rm -f "$LOG_FILE.$i"
    done
    cp "$LOG_FILE" "$LOG_FILE.1"
    : > "$LOG_FILE"
  }
  while true; do
    sleep "$ROTATE_INTERVAL"
    rotate_logs_now || true
  done
' >/dev/null 2>&1 </dev/null &
echo $! > "$LOGROTATE_PID_FILE"

# --- Wait for server to come up. ------------------------------------------
for i in $(seq 1 20); do
  if curl -s --max-time 1 "http://${HOST}:${PORT}/" -o /dev/null 2>/dev/null; then
    echo ""
    echo "Playwright MCP ready (PID $(cat "$PID_FILE"))."
    echo "  Endpoint     : ${MCP_URL}"
    echo "  Log          : ${LOG_FILE}"
    echo "  Stop         : ${PROJECT_ROOT}/mcp-down"
    echo ""
    echo "Connect any MCP client by adding the snippet from mcp/client-config.json"
    echo "to its mcp.json (e.g. ~/.claude.json or .mcp.json in your project)."
    exit 0
  fi
  sleep 0.5
done

echo "ERROR: Playwright MCP did not start within 10s. Check ${LOG_FILE}." >&2
tail -20 "$LOG_FILE" >&2 || true
exit 1
