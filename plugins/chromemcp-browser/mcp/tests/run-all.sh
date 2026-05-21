#!/usr/bin/env bash
# Run every test_*.py in this directory against the live MCP server.
# Returns non-zero on any failure. Each test prints PASS/FAIL on its own line.
#
# Tests expect the MCP server to be up — start it via ./mcp-up first.
set -uo pipefail

cd "$(dirname "$(readlink -f "$0")")"

PASS=0
FAIL=0
FAILED=()
START=$(date +%s)

for t in test_*.py; do
  [ -e "$t" ] || continue
  name=$(basename "$t" .py)
  printf '%-60s ' "$name ..."
  if python3 "$t" > "/tmp/mcp-test-${name}.out" 2>&1; then
    last=$(tail -1 "/tmp/mcp-test-${name}.out")
    printf '%s\n' "$last"
    PASS=$((PASS+1))
  else
    printf 'FAIL\n'
    sed 's/^/    /' "/tmp/mcp-test-${name}.out"
    FAIL=$((FAIL+1))
    FAILED+=("$name")
  fi
done

ELAPSED=$(( $(date +%s) - START ))
echo ""
echo "================================"
echo "PASS: $PASS"
echo "FAIL: $FAIL"
echo "TIME: ${ELAPSED}s"
if [ "$FAIL" -gt 0 ]; then
  echo "Failed tests: ${FAILED[*]}"
  exit 1
fi
echo "All tests passed."
