#!/usr/bin/env python3
"""Covers: safe structured evidence wrapper for todo runners."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, sys.path[0] or ".")

from _harness import assert_not_in, assert_true, run_test
from mcp.client import BrowserEvidenceEntry, BrowserEvidenceReport, McpToolError, TabInfo
from mcp.client.safe_runner import (
    SafeRunner,
    SafeRunnerBlocked,
    assert_completion_allowed,
    canonical_browser_url,
    deep_redact,
)


class FakeClient:
    def __init__(self, tabs=None, state=None, console_entries=None, network_text="Total requests: 1"):
        self.tabs = tabs or []
        self.state = state or {
            "url": "https://example.test/dashboard",
            "title": "Example Dashboard",
            "h1": "Dashboard",
            "viewport": {"width": 1440, "height": 1000},
            "server_error_markers": [],
        }
        self.console_entries = console_entries or []
        self.network_text = network_text
        self.calls = []
        self.new_tab_count = 0

    def list_tabs(self):
        return list(self.tabs)

    def select_tab_verified(self, index, expected_url=None, expected_title=None):
        self.calls.append(("select", index, expected_url, expected_title))
        for tab in self.tabs:
            if tab.index == index:
                return tab
        raise McpToolError("missing tab")

    def open_new_tab(self, url, expected_title=None):
        self.new_tab_count += 1
        index = max([tab.index for tab in self.tabs], default=0) + 1
        self.tabs.append(TabInfo(index=index, current=True, title="Opened", url=url))
        self.calls.append(("new", url, expected_title))
        return index

    def call_tool(self, name, arguments=None, allow_error=False):
        arguments = arguments or {}
        self.calls.append((name, arguments))
        if name == "browser_evaluate":
            return {"structuredContent": {"chromemcp": {"result": {"value": self.state}}}}
        if name == "browser_network_requests":
            return {"content": [{"type": "text", "text": self.network_text}]}
        if name == "browser_take_screenshot":
            return {"content": [{"type": "image", "data": "ZmFrZQ==", "mimeType": "image/png"}]}
        return {"content": [{"type": "text", "text": ""}]}

    @staticmethod
    def tool_text(result):
        return next((item.get("text", "") for item in result.get("content", []) if item.get("type") == "text"), "")

    @staticmethod
    def tool_structured_result(result):
        return result["structuredContent"]["chromemcp"]

    @staticmethod
    def tool_image(result):
        for item in result.get("content", []):
            if item.get("type") == "image":
                return item
        return None

    def clear_browser_evidence(self):
        self.calls.append(("clear_browser_evidence", {}))

    def collect_browser_evidence(self, **kwargs):
        self.calls.append(("collect_browser_evidence", kwargs))
        return BrowserEvidenceReport(
            collected_at="2026-05-21T00:00:00+00:00",
            tab_title=self.state["title"],
            tab_url=self.state["url"],
            run_id=kwargs.get("run_id"),
            entries=list(self.console_entries),
            raw_summary=f"Total messages: {len(self.console_entries)}",
        )


def test_deep_redaction_covers_secret_shapes():
    payload = {
        "code": "localStorage.setItem('token','tok_123456789'); document.cookie='sid=abcdef123456';",
        "headers": {"Authorization": "Bearer abcdefghijklmnop", "X-CSRF-Token": "csrf-123456789"},
        "text": "password=hunter2 nonce=nonce-secret api_key=key-secret sessionStorage.refresh_token=refresh-secret",
    }
    redacted = deep_redact(payload)
    serialized = json.dumps(redacted.value, sort_keys=True)

    for secret in ("tok_123456789", "abcdef123456", "abcdefghijklmnop", "csrf-123456789", "hunter2", "nonce-secret", "key-secret", "refresh-secret"):
        assert_not_in(secret, serialized, f"secret leaked: {secret}")
    assert_true(redacted.count >= 8, "redaction count did not include sentinel secrets")


def test_successful_page_smoke_returns_compact_json_evidence():
    client = FakeClient(
        tabs=[TabInfo(index=7, current=False, title="Example", url="https://example.test/dashboard")],
        network_text="1. [GET] https://example.test/dashboard => [200]",
    )
    runner = SafeRunner(client=client)
    evidence = runner.open_page(
        "https://example.test/dashboard",
        profile="dashboard",
        action="open page",
        handoff=True,
        screenshot=True,
        deployment_context="commit abc123",
    )

    assert_true(evidence["status"] == "pass", "status missing")
    assert_true(evidence["url"] == "https://example.test/dashboard", "URL missing")
    assert_true(evidence["title"] == "Example Dashboard", "title missing")
    assert_true(evidence["h1"] == "Dashboard", "H1 missing")
    assert_true(evidence["viewport"] == "1440x1000", "viewport missing")
    assert_true(evidence["actions"] == ["open page"], "actions missing")
    assert_true(evidence["console_errors"] == 0, "console error count missing")
    assert_true(evidence["network_failures"] == 0, "network failure count missing")
    assert_true(evidence["screenshot"] == "captured", "screenshot metadata missing")
    assert_true(evidence["handoff_left_open"] is True, "handoff was not verified")
    assert_true(evidence["tab_target"]["matched_by"] == "url", "stable tab targeting missing")
    assert_true(evidence["markdown_primary"] is False, "Markdown must not be primary evidence")
    assert_true(evidence["unsafe_code_used"] is False, "unsafe code must not be primary proof")
    assert_true(client.new_tab_count == 0, "existing tab was not reused")


def test_bare_origin_url_is_canonicalized_for_browser_open():
    assert_true(canonical_browser_url("https://example.com") == "https://example.com/", "bare origin URL should include slash")
    assert_true(canonical_browser_url("https://example.com/path") == "https://example.com/path", "path URL should be unchanged")


def test_wrong_tab_blocks_before_actions_run():
    client = FakeClient(
        tabs=[TabInfo(index=2, current=False, title="Other", url="https://other.test")],
        state={"url": "https://wrong.test", "title": "Wrong", "h1": "", "viewport": {"width": 1440, "height": 1000}, "server_error_markers": []},
    )
    runner = SafeRunner(client=client)
    try:
        runner.open_page("https://example.test/dashboard", profile="dashboard")
    except SafeRunnerBlocked as e:
        assert_true("target tab" in str(e) or "wrong tab" in str(e), "wrong-tab blocker was unclear")
    else:
        raise AssertionError("wrong target tab did not block")


def test_completion_gate_blocks_missing_markdown_or_unsafe_evidence():
    try:
        assert_completion_allowed(required=True, evidence=None)
    except SafeRunnerBlocked:
        pass
    else:
        raise AssertionError("missing required evidence did not block")

    for evidence in (
        {"status": "pass", "markdown_primary": True},
        {"status": "pass", "unsafe_code_used": True},
        {"status": "pass", "target_verified": False},
        {"status": "blocked", "blocked_reason": "redaction failed"},
    ):
        try:
            assert_completion_allowed(required=True, evidence=evidence)
        except SafeRunnerBlocked:
            pass
        else:
            raise AssertionError(f"unsafe evidence did not block: {evidence}")


def test_console_and_network_failures_block_completion():
    client = FakeClient(
        tabs=[TabInfo(index=3, current=True, title="Example", url="https://example.test/dashboard")],
        console_entries=[BrowserEvidenceEntry(kind="console", severity="error", text="SQLSTATE token=secret-token")],
        network_text="1. [GET] https://example.test/api => [500]",
    )
    runner = SafeRunner(client=client)
    try:
        runner.open_page("https://example.test/dashboard", profile="dashboard")
    except SafeRunnerBlocked as e:
        message = str(e)
        assert_true("console" in message or "network" in message, "failure blocker did not name evidence source")
        assert_not_in("secret-token", message, "secret leaked in blocker")
    else:
        raise AssertionError("console/network failures did not block")


def main():
    test_deep_redaction_covers_secret_shapes()
    test_successful_page_smoke_returns_compact_json_evidence()
    test_bare_origin_url_is_canonicalized_for_browser_open()
    test_wrong_tab_blocks_before_actions_run()
    test_completion_gate_blocks_missing_markdown_or_unsafe_evidence()
    test_console_and_network_failures_block_completion()


if __name__ == "__main__":
    run_test("safe_runner", main)
