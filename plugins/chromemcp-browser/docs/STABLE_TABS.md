# ChromeMCP Stable Tab Targeting

Upstream Playwright MCP currently exposes `browser_tabs` targeting by numeric
index only. Those indices can become stale when tabs are opened, closed, or
reordered, and duplicate titles are common in shared browser sessions.

ChromeMCP's shared Python harness therefore treats a numeric index as a
temporary transport detail, not as the identity of a tab.

## Harness Pattern

Use `McpClient.scoped_tab(url, expected_title=...)` or the lower-level helpers:

- `open_new_tab(url, expected_title=...)`
- `select_tab_verified(index, expected_url=..., expected_title=...)`
- `close_tab_verified(expected_url=..., expected_title=...)`
- `list_tabs()`, `find_tab()`, and `current_tab()`

The verified helpers:

1. Parse the `browser_tabs` list response into structured `TabInfo` records.
2. Select using the current numeric index only at the last possible moment.
3. Re-list tabs and verify the current tab's URL and title before page actions.
4. Fail loudly with `McpToolError` if the selected tab is not the intended tab.
5. Close by finding the current matching tab again instead of trusting a stale
   stored index.

For reliable automation, use a unique URL or title marker per run. When titles
are not unique, pass an expected URL.

## Upstream Limitation

No stable tab ID is exposed by `browser_tabs` in `@playwright/mcp@0.0.75`.
ChromeMCP cannot make numeric indices stable, but it can prevent a script from
silently continuing on the wrong tab.

For multi-step QA runs that own several tabs, use `ProjectTabSession` instead.
See `docs/TAB_SESSIONS.md` for the cleanup and failed-run preservation pattern.
