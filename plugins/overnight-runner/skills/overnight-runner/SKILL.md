---
name: overnight-runner
description: Run long autonomous todo files with guarded state, slice gates, ChromeMCP-visible browser verification, finish checks, and handoff notes.
---

# Overnight Runner

Use this skill when the user asks Codex to run a todo list autonomously for a
long time, overnight, while they are away, or until the todo file is complete.
Also use it when the user asks for guarded continuation, slice-by-slice todo
execution, or a final finish check for such a run.

## Helper Path

Resolve the guard helper before starting work:

```bash
if [ -f "$HOME/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py" ]; then
  OR="$HOME/.codex/plugins/rizonetech-local/plugins/overnight-runner/scripts/overnight-runner.py"
elif [ -f "plugins/overnight-runner/scripts/overnight-runner.py" ]; then
  OR="$PWD/plugins/overnight-runner/scripts/overnight-runner.py"
else
  OR=""
fi
```

If the helper is missing, continue with the workflow manually and tell the user
that the state helper is unavailable. Do not pretend gates passed without
evidence.

## Start Rule

For explicit overnight or long autonomous todo requests, start with:

```bash
python3 "$OR" start path/to/todo.md
```

If a start preflight records ChromeMCP as blocked, keep going only on work that
can be honestly completed without browser evidence. User-facing UI, navigation,
visual, CRUD, GRUD, and production smoke items remain incomplete until real
ChromeMCP verification passes or the todo records a concrete blocker.

## Modules

Overnight Runner is project-agnostic. The helper detects repository modules from
markers and records them in preflight state:

- `laravel`: `artisan`, `composer.json`, and `app/Providers`
- `wordpress`: `wp-content`, `public/wp-content`, or `wp-config.php`
- `node`: `package.json`
- `generic`: no known module markers

Apply only the rules for detected modules. A Laravel project can use Laravel
Cloud queue/deploy checks. A WordPress project can require plugin/theme cutover
rollback evidence. A generic repository still keeps the deploy, rollback, test,
and todo-history gates, but must not assume Laravel, WordPress, Node, or any
other stack-specific command.

If more than one module is detected, apply the relevant rules for each touched
slice. For example, a Laravel app with a Node build should satisfy Laravel
deploy safety and the Node build/test checks when both apply.

## Autonomy

Work through all unblocked todo slices. Stop only for:

- destructive actions without explicit current-thread approval
- credential or secret access that is unavailable or unsafe to reveal
- legal, licensing, provenance, or paid external-service uncertainty
- production data, deployment, or release risk that the todo did not authorize
- missing business decisions that would likely cause rework
- a total blocker with no safe local progress remaining

Do not final-answer just because one slice is done. Reread the todo file, update
the state, and continue to the next actionable item.

## Slice Loop

For every slice:

1. Reconcile the todo with the current codebase and mark stale checked items only
   after reviewing actual implementation evidence.
2. Classify the slice: `code`, `ui`, `docs-research`, `infra`, `deploy`,
   `cleanup-reset`, `legal-provenance`, or `evidence-note`.
3. Implement a vertical slice with the smallest safe blast radius.
4. Run focused tests/builds/lints for touched behavior.
5. For user-facing work, use ChromeMCP in a visible browser. Keep one intentional
   tab when practical, use a desktop viewport such as `1440x1000`, and add mobile
   viewports when responsive behavior matters.
6. Review visual evidence for horizontal overflow, console errors, blank screens,
   broken or missing assets, clipped text, unreadable text, spacing/alignment
   problems, modal scope errors, and mobile navigation.
7. For CRUD/GRUD workflows, exercise the real create/read/update/delete or
   generate/read/update/delete path with safe test data.
8. Update the todo/history with the commands, URLs, screenshots/reports, commit
   SHA, blockers, and next action.
9. Update the guard state before moving to the next slice.

Example:

```bash
python3 "$OR" update \
  --slice "Settings form" \
  --gate implemented=passed \
  --gate automated_tests=passed \
  --gate chromemcp_local=passed \
  --gate visual_qa=passed \
  --chromemcp-url "http://example.local/admin/settings" \
  --chromemcp-report "artifacts/browser/settings-report.json" \
  --chromemcp-screenshot "artifacts/browser/settings-desktop.png" \
  --chromemcp-route "/admin/settings" \
  --chromemcp-viewport "1440x1000" \
  --visual-check horizontal-overflow \
  --visual-check console-errors \
  --visual-check blank-screenshots \
  --visual-check missing-assets \
  --visual-check mobile-menu \
  --visual-check clipped-text \
  --visual-check unreadable-text \
  --visual-check spacing-alignment \
  --visual-check modal-scope \
  --chromemcp-final-visible-handoff
```

## ChromeMCP Dependency

ChromeMCP is the expected browser path. The guard probes
`http://127.0.0.1:8931/healthz` and records whether visible interactions are
enabled. If ChromeMCP is missing, unavailable, or not enabled in Codex:

- classify the browser gate as `blocked`
- capture the exact blocker and recovery command if available
- continue non-browser work only when it is still useful
- do not mark user-facing UI, visual QA, CRUD/GRUD, or production smoke complete

Retry the same browser automation step at most twice. After two failures,
switch to diagnose-blocker mode: capture DOM/snapshot, console, network, URL,
and any safe database or server evidence, then classify the blocker as `app`,
`automation`, `environment`, `data`, `decision`, or `unknown`.

## Production And Destructive Work

Production deploys, release publishing, destructive cleanup, active plugin
cutovers, `rm -rf`, data deletion, and reset/import/export/restore operations
need explicit current-thread authorization. Todo-file text alone is not enough
for destructive operations.

Before any deployment or release:

- verify there is no pending/running deployment queue if the project exposes one
- record current deployment/release pointer and rollback instructions
- avoid starting another deploy when a previous deploy is still pending/running
- update `production_deploy`, `rollback_plan`, and `todo_history_updated` gates

Laravel module:

- If `bin/cloud` exists, inspect Laravel Cloud before deploy/push handoff.
- If a deployment is pending/running, block code/UI/infra deploy work and record
  the active deployment evidence.
- After deployment, verify the deployed URL and record the deployment pointer.

WordPress module:

- Treat active plugin/theme replacement, release package publication, and
  updater publication as deploy/cutover work.
- Before cutover, record active path/version, backup path, restore command, and
  WP-CLI verification command in the rollback manifest.
- Do not replace or delete active plugin/theme directories without explicit
  current-thread approval.

Generic module:

- Keep deploy gates active when the todo requests deploy/release/production work.
- Record the project-specific deploy command and rollback plan discovered from
  the repo or user instructions; do not invent framework-specific commands.

## Finish Rule

Before final response:

```bash
python3 "$OR" finish-check
```

Use `--allow-blocked` only when every remaining unchecked item has a concrete
`Blocked:` or `Deferred:` note and the state records corresponding blocker
evidence.

For handoff:

```bash
python3 "$OR" handoff --write-todo
python3 "$OR" clear "completed overnight run"
```

The final answer should summarize completed slices, verified gates, blockers,
commit/push status, ChromeMCP evidence, and the next action.
