# Safe Runner Evidence Wrapper

Todo and overnight runners should call `bin/chromemcp-run` or
`.codex/scripts/chromemcp-run.py` when browser verification is required.

The wrapper returns JSON as the primary contract. Markdown narration, raw tool
reports, and `browser_run_code_unsafe` output are not accepted as completion
proof.

## Page Smoke

```bash
bin/chromemcp-run \
  --url https://example.test/dashboard \
  --profile production-dashboard \
  --action "opened production dashboard" \
  --required \
  --handoff \
  --compact
```

Successful output is compact and safe for todo history:

```json
{
  "status": "pass",
  "url": "https://example.test/dashboard",
  "viewport": "1440x1000",
  "actions": ["opened production dashboard"],
  "console_errors": 0,
  "network_failures": 0,
  "screenshot": "not-requested",
  "handoff_left_open": true
}
```

Blocked output exits `2` and includes `blocked_reason`.

## Safety Rules

- Stable target proof is required. The wrapper selects an existing tab by URL or
  title, or opens one and verifies it before actions run.
- `handoff_left_open` is true only after the verified page is selected.
- Console errors, page errors, visible server-error markers, and unexpected
  network failures block completion.
- Secret-shaped values are redacted recursively before output is printed.
- `browser_run_code_unsafe` is not used for primary workflow proof by this
  wrapper. If a project-specific script uses unsafe code for diagnostics, it
  must report that separately and keep primitive/selector evidence as the
  primary proof.

## Completion Gate

Use `assert_completion_allowed(required=True, evidence=evidence)` from
`mcp.client.safe_runner` in Python runners. It blocks when evidence is missing,
Markdown-only, unsafe-code based, tied to an unproven tab, failed redaction, or
not marked `status: pass`.
