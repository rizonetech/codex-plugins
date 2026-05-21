# ChromeMCP Structured Results

ChromeMCP preserves upstream Playwright MCP's human-readable `content` report
and adds a compatibility-safe `structuredContent.chromemcp` object for
`browser_evaluate` and `browser_run_code_unsafe`.

The structured object is added by the local proxy after TODO-01 response
redaction, so values exposed here follow the same redaction boundary as the
Markdown report.

## Contract

```json
{
  "structuredContent": {
    "chromemcp": {
      "schemaVersion": 1,
      "tool": "browser_run_code_unsafe",
      "status": "ok",
      "result": {
        "value": { "hello": "world" },
        "jsonType": "object",
        "raw": "{\"hello\":\"world\"}",
        "parseError": null
      },
      "error": null
    }
  }
}
```

- `schemaVersion`: contract version for ChromeMCP's enrichment layer.
- `tool`: source tool name.
- `status`: `ok` or `error`.
- `result.value`: parsed JSON result for primitives, objects, arrays, strings,
  and `null`.
- `result.jsonType`: one of `null`, `array`, `object`, `string`, `number`,
  `boolean`, `undefined`, or `unparsed`.
- `result.raw`: raw result section text after redaction.
- `result.parseError`: JSON parse error text when `jsonType` is `unparsed`.
- `error.message`: upstream error section text when the tool reports `isError`.

## Edge Cases

- Thrown exceptions are represented with `status: "error"`, `result: null`,
  and `error.message`.
- Upstream `undefined` is represented as `jsonType: "undefined"` and
  `value: null`.
- Dates, buffers, handles, circular objects, and other unserializable values
  follow upstream Playwright MCP serialization first. If upstream renders a
  JSON result, ChromeMCP parses it; if upstream renders an error or unparseable
  text, ChromeMCP reports that state without hiding the original report.

## Client Usage

Prefer `structuredContent.chromemcp.result.value` for automation and keep
`content[0].text` for human debugging.

See `mcp/examples/structured-result.py` for a minimal consumer using the
supported `mcp.client` module.
