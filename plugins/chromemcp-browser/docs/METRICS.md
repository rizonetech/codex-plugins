# ChromeMCP metrics

`GET http://127.0.0.1:8931/metrics` returns Prometheus text exposition format. The endpoint is **unauthenticated** — same security posture as `/healthz`: anyone who can reach the public port can scrape. The metric surface is small and bounded, so this is the same trade-off most Prometheus apps make.

Scrape with Prometheus:

```yaml
- job_name: chromemcp
  scrape_interval: 15s
  static_configs:
    - targets: ['127.0.0.1:8931']
```

## Metric surface

| Metric | Type | Labels | Description |
|---|---|---|---|
| `mcp_proxy_requests_total` | counter | `path`, `status` | All HTTP requests received by the auth proxy. Includes `/healthz`, `/metrics`, `/mcp`, anything. `path` is the request URL minus query string. `status` is the response code as string. |
| `mcp_tool_calls_total` | counter | `tool` | MCP method invocations on `/mcp` POSTs. `tool` is `params.name` for `tools/call`, the method name itself otherwise (`initialize`, `notifications/initialized`, …). Reserved sentinel labels: `_unknown`, `_unparseable`, `_oversize`. |
| `mcp_tool_errors_total` | counter | `tool`, `status` | `/mcp` requests that returned HTTP status ≥ 400. Same `tool` labelling as above. Note: **does not** parse JSON-RPC `error` bodies — only HTTP-level failures. Tool-level errors that return HTTP 200 with a `result.isError: true` shape do not increment this. |
| `mcp_tool_duration_seconds` | histogram | `tool` | Wall-clock duration of `/mcp` requests from receive-headers to response-finish. Default buckets `[.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]`. Use `histogram_quantile(0.95, sum by(le, tool) (rate(mcp_tool_duration_seconds_bucket[5m])))` for p95 per tool. |
| `mcp_session_starts_total` | counter | (none) | `initialize` calls seen on `/mcp`. Increments only on parseable JSON-RPC bodies with `method == "initialize"`. |
| `mcp_active_sessions` | gauge | (none) | Distinct `Mcp-Session-Id` values seen in the last `MCP_SESSION_IDLE_MS` (default 5 min). Idle sessions are pruned on a 60 s tick. |
| `mcp_chrome_reconnects_total` | counter | (none) | CDP recovery cycles (`healthy → down → healthy → upstream-restart`). Increments once per recovery from the watchdog (G4). |

## Cardinality notes

- `tool` labels are bounded by the MCP tool surface — currently ~20 distinct names. Adding a tool to the upstream `@playwright/mcp` adds one label value. The three sentinel labels (`_unknown`, `_unparseable`, `_oversize`) are static.
- `status` labels are HTTP status codes — small cardinality.
- `path` labels include any URL — in practice this is `/healthz`, `/metrics`, `/mcp`. If a client probes other paths, you'd get one series per probed path. Watch this if you front the proxy with something that fans out to many paths.

## Not yet exported

The following are listed in the G7 roadmap entry but **not** implemented in this initiative:

- `mcp_chrome_tabs_open` — would require either a parallel CDP connection or proxying `browser_tabs(list)` responses and parsing their text. Both are out of scope; deferred.
- `mcp_chrome_cdp_latency_seconds` — would need an in-proxy CDP client (we don't have one). Deferred.
- Tool-level error parsing of JSON-RPC bodies. The proxy currently classifies errors by HTTP status only.

## Configuration

| Env var | Default | Effect |
|---|---|---|
| `MCP_BODY_BUFFER_LIMIT` | `262144` | Per-request body buffer cap. Requests larger than this are labelled `_oversize` and forwarded without tool extraction. Increase if you call tools with very large argument blobs. |
| `MCP_SESSION_IDLE_MS` | `300000` | Session idle window for the `mcp_active_sessions` gauge. |
| `MCP_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARN` / `ERROR`. |
| `MCP_LOG_FORMAT` | `text` | `text` (backward-compat: `auth-proxy: <msg>`) or `json` (`{"ts","level","source","msg",...}` one per line). |
