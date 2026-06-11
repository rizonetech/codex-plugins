---
name: chromemcp-browser
description: Use when Codex needs a Chrome-backed browser after the bundled Chrome connector is unavailable, or when a task needs the Codex-isolated ChromeMCP Playwright MCP server at http://localhost:8941/mcp for authenticated browser verification, CRUD testing, local web app testing, production smoke checks, screenshots, or browser automation that must not interfere with Claude's shared ChromeMCP instance.
---

# ChromeMCP Browser

Use ChromeMCP Browser for authenticated browser verification, local web app testing, production smoke checks, and screenshots that need a persistent Windows Chrome profile.

The infrastructure stack lives at `~/ChromeMCP`, installed from
https://github.com/rizonetech/ChromeMCP via:

```bash
bash ~/github/ChromeMCP/scripts/install.sh --from-source
eval "$(chromemcp codex-lane acquire --format shell --owner "codex-$$")"
chromemcp codex-bridge "$CODEX_CHROMEMCP_LANE"
chromemcp codex-chrome "$CODEX_CHROMEMCP_LANE"
chromemcp codex-up "$CODEX_CHROMEMCP_LANE"
MCP_URL="$MCP_URL" MCP_TOKEN_PATH="$MCP_TOKEN_PATH" chromemcp test
```

The `chromemcp` CLI is at `~/.local/bin/chromemcp`. Screenshots are returned inline
and saved to `.playwright-mcp/` under the current project root (the server resolves
output paths against the MCP client's workspace root); prefer the default
timestamped filename.

## Start And Verify

1. Ensure the external server is running:

```bash
eval "$(chromemcp codex-lane acquire --format shell --owner "codex-$$")"
chromemcp codex-up "$CODEX_CHROMEMCP_LANE"
```

2. Verify the bridge before relying on it:

```bash
MCP_URL="$MCP_URL" MCP_TOKEN_PATH="$MCP_TOKEN_PATH" chromemcp test
```

3. Use the exposed MCP server named `chromemcp-playwright` for browser actions.

If the Codex smoke test fails because CDP is unreachable, run
`chromemcp codex-bridge "$CODEX_CHROMEMCP_LANE" /refresh`, then retry
`chromemcp codex-up "$CODEX_CHROMEMCP_LANE"`. Fix
ChromeMCP before claiming browser verification passed.

## Tab Discipline

- List tabs before acting; reuse the current tab for navigation.
- Never retry a failed navigation by opening a new tab — recover health instead
  (`chromemcp codex-bridge "$CODEX_CHROMEMCP_LANE" /refresh`).
- Hard cap: 3 tabs open at once. Never close tabs you did not open this session
  without asking the user first.
- Close every tab you opened before finishing the task.

## Reliable Browser Testing

- Treat ChromeMCP as a real persistent browser. Reuse existing authenticated sessions, but never print credentials, cookies, tokens, or localStorage values.
- Expect ChromeMCP to be visible: browser tool calls should bring the Codex ChromeMCP window forward so the user can monitor actions. If Chrome does not surface, verify `MCP_VISIBLE_INTERACTIONS` is not set to `0`.
- Prefer user-visible actions: navigate, click the actual control, wait for the page state that proves success, and take screenshots only when visual proof is useful.
- For user-facing app handoff, verify visual accuracy, appearance, and navigation explicitly, not only DOM state.
- Use stable locators based on role, label, placeholder, visible text, or form semantics. Avoid brittle generated CSS classes.
- For CRUD flows, prove the full loop: create, read/list/detail, update, verify updated state, delete/archive, then verify the record is gone.
- Clean up records created during production tests.
- If a ChromeMCP browser test finds an issue, fix it and rerun the affected browser verification before moving on.
- If the app uses a shared profile with theme preferences, normalize the test theme at the beginning of the flow when visual consistency matters. Choose the app's intended theme explicitly instead of relying on system detection:

```javascript
localStorage.setItem('theme', 'dark')
document.documentElement.classList.add('dark')
```

Use `light` and remove the `dark` class only when the test intentionally targets light mode. Then reload or navigate to the target page before asserting visuals.

## Filament And Livewire Forms

Filament and Livewire pages can reject low-level DOM typing in some browser contexts. When normal typing is unreliable, use the real clipboard path:

1. Write the target value to the browser clipboard.
2. Click the real input, textarea, or combobox.
3. Send `Control+A`, `Backspace`, then `Control+V`.
4. Submit with the visible form button, not the first icon button with the same label.

For destructive actions, click the visible action first, scope confirmation to the modal/dialog, then click the exact confirm button. If Playwright reports the modal wrapper as hidden while it is visibly open, use the modal submit button as the scoped target and document that workaround in the test note.

## Client Notes

- Lane 1's Codex endpoint is `http://localhost:8941/mcp`; lane 2 uses `http://localhost:8951/mcp`, and higher lanes follow the same `+10` pattern.
- For concurrent Codex runs, claim a lane with `eval "$(chromemcp codex-lane acquire --format shell --owner "codex-$$")"` and release it with `chromemcp codex-lane release "$CODEX_CHROMEMCP_LANE"` when done.
- The Codex Chrome profile lives at `%LOCALAPPDATA%\ChromeMCP-Codex\Profile` on Windows.
- The default Claude/shared ChromeMCP endpoint remains `http://localhost:8931/mcp`; do not use it from Codex when the user wants isolation.
- If Codex has not loaded this plugin yet, run the Rizonetech marketplace installer from the `codex-plugins` repository and restart Codex after enabling `chromemcp-browser@rizonetech-local`.
- Other MCP clients can use the same endpoint, but Claude Code should stay on the default endpoint when the user wants Codex isolated.
