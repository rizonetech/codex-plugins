# ChromeMCP MCP-tool test coverage

Snapshot of which `@playwright/mcp@0.0.75` tools have at least one
regression test in `mcp/tests/`. Coverage target: ≥ 80% (per roadmap G8).
Current: **18 / 23 = 78%** — just under target; the five uncovered tools
have explicit blocking reasons documented below.

| Tool | Test file | Notes |
|---|---|---|
| `browser_click` | `test_click.py` | Verifies click mutates page state. Uses `[ref=eN]` from `browser_snapshot`. |
| `browser_close` | — (untested) | **Semantic mismatch with tabs**: closes the Playwright `Page` object, not a Chrome tab. Closing it during a test orphaned the browser context for subsequent tests. Would need an isolated-context fixture to test safely. |
| `browser_console_messages` | `test_console.py` | Asserts `console.log` and `console.warn` lines are captured. |
| `browser_drag` | — (untested) | **Out of scope**: needs source+target refs and reliable mouse-path coordinates. Deferred to a follow-up if drag-drop becomes a load-bearing feature. |
| `browser_drop` | — (untested) | **Out of scope**: needs file-like data or a specific element target. Same justification as `browser_drag`. |
| `browser_evaluate` | `test_evaluate.py` | Primitive return (`6*7=42`) AND object return (`{hello:'world'}`). |
| `browser_file_upload` | — (untested) | **Out of scope**: needs a file path that is reachable from the Windows side. Coordinating fixture files across the WSL↔Windows boundary is non-trivial and not load-bearing for ChromeMCP's mission. |
| `browser_fill_form` | `test_type.py` | Populates two named text fields in one call, asserts both `value`s. |
| `browser_handle_dialog` | — (untested) | **Tested manually only**: Playwright's default dialog handler races with the MCP `browser_handle_dialog` tool; the dialog is dismissed before our handle call lands. Would need either an upstream-supported "pause-on-dialog" mode or a deterministic event-listener priming step. |
| `browser_hover` | `test_click.py` | Hover fires the page's `mouseenter` handler. |
| `browser_navigate` | `test_navigate.py` | Navigates between two `data:` URL pages. |
| `browser_navigate_back` | `test_navigate.py` | Verifies history navigation returns to the first page. |
| `browser_network_request` | `test_network.py` | Pulls one specific request by index from the list response. |
| `browser_network_requests` | `test_network.py` | `static=true` so `data:` URL traffic surfaces in the list. |
| `browser_press_key` | `test_type.py` | Smoke: tool returns without error. Key-event observability is implementation-specific. |
| `browser_resize` | `test_screenshot.py` | Sets viewport before screenshotting so geometry is known. |
| `browser_run_code_unsafe` | `test_evaluate.py` | Returns `document.title` via Playwright's `async (page)` wrapper and proves secret-shaped code/result echoes are redacted. |
| `browser_select_option` | `test_select.py` | Selecting `beta` fires `onchange`; verified via DOM-text mutation. |
| `browser_snapshot` | `test_snapshot.py` | Shape sanity: every fixture element + `[ref=...]` tags must be present. |
| `browser_tabs` | `test_tabs.py` | `new` → `list` → `select` → verified current-tab guard → `close` lifecycle. |
| `browser_take_screenshot` | `test_screenshot.py` | Viewport AND `fullPage`; PNG magic-bytes verified. |
| `browser_type` | `test_type.py` | Typing into an input fires `oninput` which mutates `document.title`. |
| `browser_wait_for` | `test_navigate.py` | Waits for the second-page text marker after navigate. |

`test_structured_results.py` also covers ChromeMCP's proxy-level
`structuredContent.chromemcp` enrichment for `browser_evaluate` and
`browser_run_code_unsafe`; it is not counted as an additional upstream tool.

`test_session_tabs.py` covers the ChromeMCP harness-level project tab session
helper: owned-tab cleanup, unrelated-tab preservation, failed-run preservation,
and active owned-tab verification before page tool calls.

`test_client_module.py` covers the supported `mcp.client` import surface and
token lookup contract used by tests, examples, and `mcp/test.sh`.

`test_browser_evidence.py` covers the public structured console/page-error
evidence helpers, high-signal failure checks, redaction, and bounded artifact
writer.

`test_safe_runner.py` covers the safe todo-runner evidence wrapper: recursive
secret redaction, compact JSON output, stable URL/title tab targeting,
handoff-tab accuracy, console/network completion blockers, and required-browser
completion gate failures for missing, Markdown-only, unsafe, or wrong-tab
evidence.

## Running

```bash
./mcp-up                          # ensure the stack is up + auth token is on disk
bash mcp/tests/run-all.sh         # 15 public test_*.py files, ~190 s wall clock
```

`run-all.sh` exits non-zero if any test fails. Each test prints its
PASS/FAIL line. Failure detail goes to `/tmp/mcp-test-<name>.out` and is
also tee-printed in the runner output.

## Authoring new tests

Each `test_*.py`:

1. Imports `McpClient` and helpers from `_harness.py`.
2. Calls `c.initialize()`.
3. Wraps the body in `with c.scoped_tab(c.data_url('<html>...</html>')) as idx:`
   so the test cleans up after itself.
4. Drives tools via `c.call_tool(name, args)` and reads `c.tool_text(result)`
   or `c.tool_image(result)`.
5. Asserts via `assert_in`, `assert_not_in`, `assert_true`, or raises directly.
6. Wraps `main` with `run_test('<name>', main)` so PASS/FAIL output is uniform.

Avoid external HTTP fixture servers — use `data:` URLs. The WSL ↔ Windows
firewall makes a WSL-side fixture HTTP server reachable to Chrome on
Windows non-trivial to set up; `data:` URLs sidestep this entirely.
