"""Safe structured ChromeMCP evidence wrapper for todo runners."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
from datetime import datetime, timezone
import json
import re
import urllib.parse
from typing import Any, Optional

from .core import (
    BrowserEvidenceReport,
    McpClient,
    McpError,
    McpToolError,
    TabInfo,
    redact_text,
    redact_url,
)


DEFAULT_VIEWPORT = {"width": 1440, "height": 1000}
SERVER_ERROR_MARKERS = ("SQLSTATE", "Exception trace", "Server Error", "Internal Server Error", "HTTP ERROR")


class SafeRunnerBlocked(McpError):
    """Raised when browser evidence cannot safely prove completion."""


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    count: int


SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+([A-Za-z0-9._~+/=-]{8,})", re.IGNORECASE),
    re.compile(r"\b(cookie|cookies|authorization|token|access_token|refresh_token|api_key|x-api-key|secret|password|csrf|csrf_token|nonce)\b\s*[:=]\s*([^\s,;'\"}]+)", re.IGNORECASE),
    re.compile(r"(localStorage|sessionStorage)\.(?:setItem\()?['\"]?([A-Za-z0-9_.:-]*(?:token|secret|password|csrf|nonce|auth)[A-Za-z0-9_.:-]*)['\"]?\s*,?\s*['\"]([^'\"]{4,})['\"]", re.IGNORECASE),
    re.compile(r"document\.cookie\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE),
)
SECRET_KEY_PATTERN = re.compile(r"(cookie|cookies|authorization|token|access_token|refresh_token|api_key|x-api-key|secret|password|csrf|csrf_token|nonce)", re.IGNORECASE)


def _redact_string(value: str) -> tuple[str, int]:
    redacted = value
    count = 0

    def replace_bearer(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "Bearer [REDACTED:authorization]"

    def replace_keyed(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        key = match.group(1)
        return f"{key}=[REDACTED:{key.lower().replace('-', '_')}]"

    def replace_storage(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        storage = match.group(1)
        key = match.group(2)
        return f"{storage}.{key}=[REDACTED:storage]"

    def replace_cookie_assignment(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "document.cookie=[REDACTED:cookie]"

    redacted = SECRET_VALUE_PATTERNS[0].sub(replace_bearer, redacted)
    redacted = SECRET_VALUE_PATTERNS[1].sub(replace_keyed, redacted)
    redacted = SECRET_VALUE_PATTERNS[2].sub(replace_storage, redacted)
    redacted = SECRET_VALUE_PATTERNS[3].sub(replace_cookie_assignment, redacted)
    redacted = redact_text(redacted)
    return redacted, count


def deep_redact(value: Any) -> RedactionResult:
    if isinstance(value, str):
        redacted, count = _redact_string(value)
        return RedactionResult(redacted, count)
    if isinstance(value, dict):
        total = 0
        output = {}
        for key, item in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                total += 1
                output[key] = f"[REDACTED:{str(key).lower().replace('-', '_')}]"
                continue
            result = deep_redact(item)
            total += result.count
            output[key] = result.value
        return RedactionResult(output, total)
    if isinstance(value, list):
        total = 0
        output = []
        for item in value:
            result = deep_redact(item)
            total += result.count
            output.append(result.value)
        return RedactionResult(output, total)
    return RedactionResult(value, 0)


def _value_from_tool_result(client: McpClient, result: dict) -> dict:
    value = client.tool_structured_result(result).get("result", {}).get("value")
    if not isinstance(value, dict):
        raise SafeRunnerBlocked("browser state evidence was not structured JSON")
    return value


def page_state_script() -> str:
    return """() => {
      const visibleText = (el) => (el && (el.innerText || el.textContent) || '').trim();
      const h1 = visibleText(document.querySelector('h1'));
      const title = document.title || '';
      const bodyText = visibleText(document.body).slice(0, 4000);
      const serverErrorMarkers = [];
      const markerText = `${title}\n${h1}\n${bodyText}`;
      for (const marker of ['SQLSTATE', 'Exception trace', 'Server Error', 'Internal Server Error', 'HTTP ERROR']) {
        if (markerText.includes(marker)) serverErrorMarkers.push(marker);
      }
      return {
        url: window.location.href,
        title,
        h1,
        viewport: { width: window.innerWidth, height: window.innerHeight },
        server_error_markers: serverErrorMarkers
      };
    }"""


def _network_summary(text: str) -> dict:
    failures = []
    for line in text.splitlines():
        lowered = line.lower()
        if re.search(r"\b(4\d\d|5\d\d)\b", line) or "failed" in lowered or "net::err" in lowered:
            failures.append(redact_text(line.strip()))
    return {"count": len(failures), "failures": failures[:8]}


def _console_summary(report: BrowserEvidenceReport) -> dict:
    return {
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "entries": [entry.to_dict() for entry in report.entries[:8]],
    }


def _urls_match(expected: str, actual: str) -> bool:
    return canonical_browser_url(actual).rstrip("/") == canonical_browser_url(expected).rstrip("/")


def canonical_browser_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme and parsed.netloc and not parsed.path:
        return urllib.parse.urlunparse(parsed._replace(path="/"))
    return url


class SafeRunner:
    def __init__(
        self,
        *,
        client: McpClient,
        viewport: Optional[dict] = None,
        fail_on_warnings: bool = False,
    ):
        self.client = client
        self.viewport = viewport or dict(DEFAULT_VIEWPORT)
        self.fail_on_warnings = fail_on_warnings

    def _select_or_open_tab(self, url: str, expected_title: Optional[str] = None) -> dict:
        url = canonical_browser_url(url)
        tabs = self.client.list_tabs()
        matches = [tab for tab in tabs if _urls_match(url, tab.url) or (expected_title and tab.title == expected_title)]
        if matches:
            target = next((tab for tab in matches if tab.current), matches[-1])
            selected = self.client.select_tab_verified(target.index)
            matched_by = "url" if _urls_match(url, selected.url) else "title"
            opened = False
        else:
            index = self.client.open_new_tab(url, expected_title=expected_title)
            selected = self.client.select_tab_verified(index)
            matched_by = "opened"
            opened = True
        if not (_urls_match(url, selected.url) or (expected_title and selected.title == expected_title)):
            raise SafeRunnerBlocked(
                f"target tab could not be proven before actions: expected url={redact_url(url)!r} "
                f"title={redact_text(expected_title or '')!r}; current url={redact_url(selected.url)!r} title={redact_text(selected.title)!r}"
            )
        return {"tab": selected, "matched_by": matched_by, "opened": opened}

    def open_page(
        self,
        url: str,
        *,
        profile: str = "page-smoke",
        action: str = "opened page",
        expected_title: Optional[str] = None,
        handoff: bool = False,
        screenshot: bool = False,
        deployment_context: Optional[str] = None,
        recovered: bool = False,
    ) -> dict:
        redacted_input = deep_redact({"url": url, "expected_title": expected_title, "deployment_context": deployment_context})
        if redacted_input.count:
            url = redacted_input.value["url"]
            expected_title = redacted_input.value["expected_title"]
            deployment_context = redacted_input.value["deployment_context"]

        tab_target = self._select_or_open_tab(url, expected_title=expected_title)
        self.client.call_tool("browser_resize", dict(self.viewport))
        try:
            self.client.clear_browser_evidence()
        except McpToolError as e:
            if "not found" not in str(e).lower():
                raise
        self.client.call_tool("browser_navigate", {"url": url})

        state = _value_from_tool_result(self.client, self.client.call_tool("browser_evaluate", {"function": page_state_script()}))
        state_redacted = deep_redact(state)
        state = state_redacted.value
        redactions = redacted_input.count + state_redacted.count
        if not _urls_match(url, str(state.get("url", ""))):
            raise SafeRunnerBlocked(
                f"wrong tab after navigation: expected {redact_url(url)!r}, saw {redact_url(str(state.get('url', '')))!r}"
            )
        markers = state.get("server_error_markers") or []
        if markers:
            raise SafeRunnerBlocked(f"server-error markers found: {redact_text(json.dumps(markers))}")

        report = self.client.collect_browser_evidence(run_id=f"safe-runner-{profile}")
        console = _console_summary(report)
        network_text = self.client.tool_text(self.client.call_tool("browser_network_requests", {}))
        network = _network_summary(network_text)
        failure_bits = []
        if console["errors"] or (self.fail_on_warnings and console["warnings"]):
            failure_bits.append(f"console errors={console['errors']} warnings={console['warnings']}")
        if network["count"]:
            failure_bits.append(f"network failures={network['count']}")
        if failure_bits:
            summary = deep_redact("; ".join(failure_bits + [json.dumps(console["entries"][:3]), json.dumps(network["failures"][:3])]))
            raise SafeRunnerBlocked(summary.value)

        screenshot_state = "not-requested"
        if screenshot:
            image = self.client.tool_image(self.client.call_tool("browser_take_screenshot", {"fullPage": False}))
            screenshot_state = "captured" if image else "missing"
            if screenshot_state == "missing":
                raise SafeRunnerBlocked("screenshot was requested but no image content was returned")

        selected = self.client.select_tab_verified(tab_target["tab"].index) if handoff else tab_target["tab"]
        handoff_left_open = bool(handoff and _urls_match(url, selected.url))
        if handoff and not handoff_left_open:
            raise SafeRunnerBlocked("handoff tab was requested but the verified page is not selected")

        viewport = state.get("viewport") or {}
        evidence = {
            "schema_version": 1,
            "status": "pass",
            "profile": profile,
            "url": redact_url(str(state.get("url", ""))),
            "title": redact_text(str(state.get("title", ""))),
            "h1": redact_text(str(state.get("h1", ""))),
            "viewport": f"{viewport.get('width')}x{viewport.get('height')}",
            "actions": [redact_text(action)],
            "console_errors": console["errors"],
            "console_warnings": console["warnings"],
            "network_failures": network["count"],
            "server_error_markers": markers,
            "screenshot": screenshot_state,
            "handoff_left_open": handoff_left_open,
            "tab_target": {
                "matched_by": tab_target["matched_by"],
                "opened_by_runner": tab_target["opened"],
                "url": redact_url(tab_target["tab"].url),
                "title": redact_text(tab_target["tab"].title),
            },
            "target_verified": True,
            "recovered": recovered,
            "deployment_context": redact_text(deployment_context) if deployment_context else None,
            "redactions": redactions,
            "markdown_primary": False,
            "unsafe_code_used": False,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }
        return deep_redact(evidence).value


def assert_completion_allowed(*, required: bool, evidence: Optional[dict]) -> None:
    if not required:
        return
    if not evidence:
        raise SafeRunnerBlocked("browser verification required but structured evidence is missing")
    status = evidence.get("status")
    if status != "pass":
        raise SafeRunnerBlocked(f"browser verification required but status is {status!r}: {redact_text(str(evidence.get('blocked_reason', '')))}")
    if evidence.get("markdown_primary"):
        raise SafeRunnerBlocked("browser evidence is Markdown-only; structured JSON evidence is required")
    if evidence.get("unsafe_code_used"):
        raise SafeRunnerBlocked("browser_run_code_unsafe cannot be primary workflow proof")
    if evidence.get("target_verified") is False:
        raise SafeRunnerBlocked("browser evidence target tab was not proven")
    if evidence.get("redaction_failed"):
        raise SafeRunnerBlocked("browser evidence redaction failed")


def blocked_evidence(error: Exception, *, profile: str = "safe-runner") -> dict:
    return {
        "schema_version": 1,
        "status": "blocked",
        "profile": profile,
        "blocked_reason": redact_text(str(error)),
        "markdown_primary": False,
        "unsafe_code_used": False,
        "target_verified": False,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe structured ChromeMCP evidence wrapper")
    parser.add_argument("--url", default=None, help="Page URL to verify")
    parser.add_argument("--mcp-url", default="http://localhost:8931/mcp", help="MCP Streamable HTTP endpoint")
    parser.add_argument("--profile", default="page-smoke")
    parser.add_argument("--action", default="opened page")
    parser.add_argument("--expected-title", default=None)
    parser.add_argument("--deployment-context", default=None)
    parser.add_argument("--required", action="store_true", help="Exit blocked when safe evidence cannot be produced")
    parser.add_argument("--handoff", action="store_true", help="Leave verified page visibly selected")
    parser.add_argument("--screenshot", action="store_true", help="Capture screenshot metadata")
    parser.add_argument("--compact", action="store_true", help="Print compact JSON")
    return parser


def run_cli(args: argparse.Namespace) -> dict:
    if not args.url:
        raise SafeRunnerBlocked("--url is required for page smoke evidence")
    client = McpClient(url=args.mcp_url)
    client.initialize(name="chromemcp-safe-runner", version="0.1.0")
    runner = SafeRunner(client=client)
    evidence = runner.open_page(
        args.url,
        profile=args.profile,
        action=args.action,
        expected_title=args.expected_title,
        handoff=args.handoff,
        screenshot=args.screenshot,
        deployment_context=args.deployment_context,
    )
    assert_completion_allowed(required=args.required, evidence=evidence)
    return evidence


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_cli(args)
        code = 0
    except (SafeRunnerBlocked, McpError) as e:
        result = blocked_evidence(e, profile=args.profile if "args" in locals() else "safe-runner")
        code = 2
    print(json.dumps(result, indent=None if args.compact else 2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
