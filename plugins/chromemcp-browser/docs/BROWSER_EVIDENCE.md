# Browser Evidence

ChromeMCP exposes structured console and page-error evidence through
`mcp.client`. Use this during repeatable QA runs instead of scraping the
Markdown returned by `browser_console_messages`.

## Collect Evidence

```python
from mcp.client import McpClient, ProjectTabSession

client = McpClient()
client.initialize()

with ProjectTabSession(client, "local-smoke") as session:
    tab = session.open_tab("https://example.com", expected_title="Example Domain")
    session.select_tab(tab)
    report = client.collect_browser_evidence(run_id=session.run_id)
```

The report contains:

- current tab title and URL
- optional run/session marker
- collected timestamp
- console entries with severity, text, source URL, and line when available
- page errors as high-signal error entries
- summary counts for total entries, warnings, and errors

`data:` URLs are redacted as `data:[REDACTED:data-url]`, and common
secret-shaped values such as bearer tokens, API keys, passwords, cookies, and
token fields are redacted before artifacts are written.

## Fail On High-Signal Errors

```python
client.assert_no_high_signal_browser_errors(report)
```

By default this fails on console errors and page errors. Warnings are preserved
in the report but do not fail a run unless `fail_on_warnings=True` is passed.
Use `allowed_text_patterns=[...]` for known benign errors that should be
documented rather than hidden.

## Artifacts

```python
path = client.write_browser_evidence_artifact(report)
```

Artifacts are JSON files under `mcp/artifacts/browser-evidence/` by default.
The writer keeps the newest 50 JSON files unless a different `max_files` value
is passed. Do not write ad hoc console evidence into the `mcp/` root.

## CLI

```bash
python3 -m mcp.client.cli evidence
python3 -m mcp.client.cli evidence --artifact
python3 -m mcp.client.cli evidence --fail-on-errors
```

If console collection is unavailable, record the blocker with the tool result,
current URL/title, and whether ChromeMCP was reachable. High-signal manual
markers remain `SQLSTATE`, `Exception trace`, visible HTTP error headings,
uncaught `Error:`/`TypeError:`/`ReferenceError:`, and MCP tool `isError`
responses.
