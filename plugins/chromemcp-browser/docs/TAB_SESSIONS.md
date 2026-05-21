# ChromeMCP Project Tab Sessions

ChromeMCP intentionally uses a shared signed-in Chrome session. Project tab
sessions are therefore tab hygiene, not full browser isolation.

Use `ProjectTabSession` from `mcp.client` when a QA run needs a bounded
workspace inside an already-noisy Chrome window:

- open one or more owned tabs with a unique run marker in the title
- remember which tabs belong to the current run
- re-select and verify the active owned tab before page-affecting tool calls
- close only owned tabs during cleanup
- optionally preserve owned tabs when a run fails so the page state can be
  inspected afterwards

## Recommended Pattern

```python
from mcp.client import McpClient, ProjectTabSession

client = McpClient()
client.initialize()

with ProjectTabSession(client, "local-qa") as session:
    tab = session.open_data_tab("smoke-start", "<body>ready</body>")
    result = session.call_tool(
        "browser_evaluate",
        {"function": "() => document.title"},
        tab=tab,
    )
```

For application URLs, use `open_tab(url, expected_title=..., label=...)` when
the title is predictable. If the title is dynamic, pass a unique URL and keep the
label meaningful so ownership is still clear in script output.

## Failure Preservation

Use `preserve_on_failure=True` for exploratory or browser-heavy runs where the
failed page is useful evidence:

```python
with ProjectTabSession(client, "checkout-smoke", preserve_on_failure=True) as session:
    session.open_data_tab("before-submit", "<body>debug me</body>")
    raise RuntimeError("example failure")
```

On normal exit the session cleans up owned tabs. On an exception, owned tabs are
left open and their titles include the run name and run id.

## What This Does Not Isolate

Project tab sessions do not isolate cookies, localStorage, service workers,
browser extensions, signed-in accounts, or Chrome profile state. Use a separate
Chrome profile when a test must prove behavior with fresh authentication,
fresh storage, extension isolation, or clean browser policy.

## Tab Groups

Chrome has an extension-facing `chrome.tabGroups` API, but the current
Playwright MCP `browser_tabs` surface only exposes numeric tab indices. CDP's
Target domain can create and close targets, but it does not provide the same
extension tab-group management contract through the tool path ChromeMCP is
using here.

Until upstream exposes stable tab IDs or group operations through `browser_tabs`,
ChromeMCP keeps grouping as documentation-level guidance and implements safe
client-side ownership instead.
