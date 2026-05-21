#!/usr/bin/env bash
# Stops the Playwright MCP server started by ./start.sh.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"
PID_FILE="$(pwd)/.playwright.pid"
LOGROTATE_PID_FILE="$(pwd)/.logrotate.pid"

# Kill the log rotator sidecar first (if any). It's an independent session,
# so we have to clean it up explicitly — the proxy doesn't own it.
if [ -f "$LOGROTATE_PID_FILE" ]; then
  RPID="$(cat "$LOGROTATE_PID_FILE" 2>/dev/null || echo)"
  if [ -n "$RPID" ] && kill -0 "$RPID" 2>/dev/null; then
    kill "$RPID" 2>/dev/null || true
  fi
  rm -f "$LOGROTATE_PID_FILE"
fi

if [ ! -f "$PID_FILE" ]; then
  echo "No PID file. Server is not tracked as running."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Process $PID not running. Cleaning up stale PID file."
  rm -f "$PID_FILE"
  exit 0
fi

echo "Stopping Playwright MCP (PID $PID)..."
kill "$PID" 2>/dev/null || true

# Wait up to 5s for graceful shutdown.
for i in $(seq 1 10); do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "Stopped."
    exit 0
  fi
  sleep 0.5
done

echo "Process did not exit gracefully; sending SIGKILL."
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Stopped."
