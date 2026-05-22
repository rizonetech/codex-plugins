#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
RUNNER="$PLUGIN_ROOT/scripts/overnight-runner.py"
tmp="$(mktemp -d -t overnight-runner-test-XXXXXX)"
trap 'rm -rf "$tmp"' EXIT

cd "$tmp"
git init -q
git config user.email test@example.invalid
git config user.name "Overnight Runner Test"
mkdir -p todo artifacts/browser
cat > todo/ui.md <<'EOF'
# Todo

- [x] Existing UI skeleton
- [ ] Add admin settings CRUD flow
- Blocked: placeholder blocker note for finish-check negative/blocked path
EOF

printf '{"ok":true}\n' > artifacts/browser/report.json
python3 - <<'PY'
from pathlib import Path
Path("artifacts/browser/desktop.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 2048)
PY

git add todo/ui.md artifacts/browser/report.json artifacts/browser/desktop.png
git commit -q -m "seed test repo"

python3 "$RUNNER" start todo/ui.md >/tmp/overnight-start.out
python3 "$RUNNER" update \
  --slice "Admin settings CRUD" \
  --gate implemented=passed \
  --gate automated_tests=passed \
  --gate feature_gate=passed \
  --gate chromemcp_local=passed \
  --gate visual_qa=passed \
  --gate workflow_matrix=passed \
  --gate browser_handoff=passed \
  --gate todo_history_updated=passed \
  --chromemcp-status passed \
  --chromemcp-method real-mcp \
  --chromemcp-report artifacts/browser/report.json \
  --chromemcp-screenshot artifacts/browser/desktop.png \
  --chromemcp-route /admin/settings \
  --chromemcp-viewport 1440x1000 \
  --chromemcp-final-visible-handoff \
  --visual-status passed \
  --visual-screenshot artifacts/browser/desktop.png \
  --visual-check horizontal-overflow \
  --visual-check console-errors \
  --visual-check blank-screenshots \
  --visual-check missing-assets \
  --visual-check mobile-menu \
  --visual-check clipped-text \
  --visual-check unreadable-text \
  --visual-check spacing-alignment \
  --visual-check modal-scope \
  --workflow-status passed \
  --workflow-route /admin/settings \
  --workflow-viewport 1440x1000 \
  >/tmp/overnight-update.out

python3 "$RUNNER" checked-review \
  --line 3 \
  --status missing-added \
  --evidence "Verified skeleton exists in current code; ARIA polish remains separate." \
  --missing "Add ARIA label to existing UI skeleton" \
  --add-missing \
  >/tmp/overnight-checked-review.out
grep -q "Missing from completed claim: Add ARIA label to existing UI skeleton" todo/ui.md
python3 "$RUNNER" finish-check --allow-blocked >/tmp/overnight-finish.out
python3 "$RUNNER" handoff --write-todo >/tmp/overnight-handoff.out
grep -q "## Run Handoff" todo/ui.md
python3 "$RUNNER" clear "test completed" >/tmp/overnight-clear.out

laravel_tmp="$tmp/laravel"
mkdir -p "$laravel_tmp/app/Providers" "$laravel_tmp/todo"
cd "$laravel_tmp"
git init -q
git config user.email test@example.invalid
git config user.name "Overnight Runner Test"
touch artisan composer.json
cat > todo/deploy.md <<'EOF'
# Todo

- [ ] Deploy Laravel settings page to production
- Blocked: deployment requires explicit target approval
EOF
python3 "$RUNNER" preflight todo/deploy.md > "$tmp/laravel-preflight.json"
python3 - "$tmp/laravel-preflight.json" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
modules = {item["name"] for item in data["modules"]}
assert "laravel" in modules, modules
assert "deploy" in data["classifications"], data["classifications"]
assert data["module_checks"].get("laravel_cloud_queue", {}).get("status") == "not-applicable"
PY

wordpress_tmp="$tmp/wordpress"
mkdir -p "$wordpress_tmp/public/wp-content/plugins/example" "$wordpress_tmp/todo"
cd "$wordpress_tmp"
git init -q
git config user.email test@example.invalid
git config user.name "Overnight Runner Test"
cat > todo/cutover.md <<'EOF'
# Todo

- [ ] Replace active plugin during production cutover
- Blocked: waiting for approval
EOF
python3 "$RUNNER" preflight todo/cutover.md > "$tmp/wordpress-preflight.json"
python3 - "$tmp/wordpress-preflight.json" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
modules = {item["name"] for item in data["modules"]}
assert "wordpress" in modules, modules
assert "destructive_cutover" in data["classifications"], data["classifications"]
assert "active_plugin_replacement" in data["dangerous_operations"], data["dangerous_operations"]
assert data["module_checks"].get("wordpress_cutover_manifest", {}).get("status") == "required-before-cutover"
PY

echo "PASS overnight runner guard"
