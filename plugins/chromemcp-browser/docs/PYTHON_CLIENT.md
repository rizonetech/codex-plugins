# ChromeMCP Python Client

ChromeMCP includes a supported standard-library Python client at `mcp.client`.
Use it for local QA scripts, smoke checks, and examples instead of importing
from `mcp/tests/_harness.py`.

## Basic Use

```python
from mcp.client import McpClient, ProjectTabSession

client = McpClient()
client.initialize()

tabs = client.list_tabs()
print(tabs[0].title if tabs else "no tabs")

with ProjectTabSession(client, "local-qa") as session:
    tab = session.open_data_tab("check", "<body>ready</body>")
    result = session.call_tool(
        "browser_evaluate",
        {"function": "() => document.title"},
        tab=tab,
    )
    print(client.tool_structured_result(result)["result"]["value"])
```

## CLI

Run from the repository root after `./mcp-up`:

```bash
python3 -m mcp.client.cli tabs
python3 -m mcp.client.cli smoke
python3 -m mcp.client.cli eval-title
```

`mcp/test.sh` uses the same client module for the repository smoke check.

## Safe Runner Evidence

Todo and overnight runners should call the safe wrapper when browser proof is
required:

```bash
bin/chromemcp-run --url https://example.test --required --handoff --compact
```

The wrapper returns compact JSON and blocks Markdown-only, unsafe, missing, or
wrong-tab evidence. See [SAFE_RUNNER_EVIDENCE.md](SAFE_RUNNER_EVIDENCE.md).

## Local App Runners

App-specific smoke runners should stay out of the public client package. Keep
private route maps, credential paths, production hosts, and local verification
notes under an ignored `.local/` tree while importing generic helpers from
`mcp.client`.

## Auth And Endpoint

The client targets `http://localhost:8931/mcp` unless `MCP_URL` is set or a URL
is passed explicitly to `McpClient(url=...)`.

Token lookup matches the shell tooling:

1. `MCP_NO_AUTH=1` disables the Authorization header.
2. `MCP_AUTH_TOKEN` wins when set.
3. `MCP_TOKEN_PATH` is read when set.
4. Otherwise the default path is `~/.config/chromemcp/token`, honoring
   `XDG_CONFIG_HOME`.

## Common Failures

- `401`: the bearer token is missing or stale. Run `./mcp-up`, set
  `MCP_AUTH_TOKEN`, set `MCP_TOKEN_PATH`, or use `MCP_NO_AUTH=1` only with a
  no-auth server.
- `503`: ChromeMCP or Chrome is not available yet. Start the stack with
  `./mcp-up` and verify Chrome is reachable.
- tool `isError`: the tool ran but returned an MCP tool error. By default
  `call_tool()` raises `McpToolError`; pass `allow_error=True` only when the
  error payload is the behavior being tested.
- timeout: the endpoint did not answer within the configured timeout. Check the
  server process and Chrome connection before retrying broad test suites.

## Supported Helpers

- `McpClient.initialize()`
- `McpClient.call_tool()`
- `McpClient.tool_text()`
- `McpClient.tool_structured_result()`
- `McpClient.tool_image()`
- `McpClient.list_tabs()`, `find_tab()`, `current_tab()`
- `McpClient.open_new_tab()`, `select_tab_verified()`,
  `close_tab_verified()`, `scoped_tab()`
- `ProjectTabSession` for owned-tab QA runs
- `McpClient.collect_browser_evidence()` and
  `assert_no_high_signal_browser_errors()` for structured console/page-error
  checks

The helper is tab/session hygiene for the shared signed-in Chrome profile. It
does not isolate cookies, localStorage, extensions, or authenticated state.

See `docs/BROWSER_EVIDENCE.md` for artifact output and high-signal browser
error handling.
