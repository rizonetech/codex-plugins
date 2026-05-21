---
name: chromemcp-browser
description: Use when Codex needs a Chrome-backed browser after the bundled Chrome connector is unavailable, or when a task needs the shared ChromeMCP Playwright MCP server at http://localhost:8931/mcp for authenticated browser verification, CRUD testing, local web app testing, production smoke checks, screenshots, or cross-client browser automation.
---

# ChromeMCP Browser

Use ChromeMCP Browser for authenticated browser verification, local web app testing, production smoke checks, and screenshots that need a persistent Windows Chrome profile.

## Start And Verify

1. Ensure the external server is running:

```bash
cd /path/to/codex-plugins/plugins/chromemcp-browser
./mcp-up
```

2. Verify the bridge before relying on it:

```bash
cd /path/to/codex-plugins/plugins/chromemcp-browser
bash mcp/test.sh
```

3. Use the exposed MCP server named `chromemcp-playwright` for browser actions.

If `mcp/test.sh` fails, fix ChromeMCP before claiming browser verification passed.

## Reliable Browser Testing

- Treat ChromeMCP as a real shared browser. Reuse existing authenticated sessions, but never print credentials, cookies, tokens, or localStorage values.
- Expect ChromeMCP to be visible: browser tool calls should bring the shared ChromeMCP window forward so the user can monitor actions. If Chrome does not surface, verify `MCP_VISIBLE_INTERACTIONS` is not set to `0`.
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

- The endpoint is `http://localhost:8931/mcp`.
- The Chrome profile lives at `%LOCALAPPDATA%\ChromeMCP\Profile` on Windows.
- If Codex has not loaded this plugin yet, run the Rizonetech marketplace installer from the `codex-plugins` repository and restart Codex after enabling `chromemcp-browser@rizonetech-local`.
- Other MCP clients, including Claude Code and Cursor, can use the same endpoint.
