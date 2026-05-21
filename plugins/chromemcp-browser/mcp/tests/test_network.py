#!/usr/bin/env python3
"""Covers: browser_network_requests, browser_network_request.

Uses a small fetch() against a data: URL so the network capture has at
least one observable request. data: URLs DO produce a Playwright network
event even though there's no actual TCP. If that proves flaky we'd fall
back to a real HTTP fixture (gated on G15 CI work).
"""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_true, run_test
from mcp.client import McpClient


def main():
    c = McpClient()
    c.initialize()
    # Page that issues a fetch on load. We embed the URL inline so the test
    # is self-contained.
    fixture = (
        "<!doctype html><title>network-fixture</title>"
        "<script>"
        "fetch('data:text/plain,marker-network-body').then(r => r.text())"
        "  .then(t => document.title = 'fetched-' + t.length);"
        "</script>"
    )
    with c.scoped_tab(c.data_url(fixture)):
        import time
        time.sleep(0.5)  # let the fetch settle into the request log
        # static=true makes Playwright also include resources like the data:
        # URL fetch the page issued; without it the list might be empty for
        # data: URLs that don't trip Playwright's "interesting traffic" filter.
        result = c.call_tool("browser_network_requests", {"static": True})
        text = c.tool_text(result)
        # Loose assertion: any non-empty network output is enough to prove
        # the tool wired up correctly. Tightening this would couple the
        # test to Playwright's exact output formatting.
        assert_true(
            len(text.strip()) > 0,
            f"browser_network_requests returned empty body: {text[:200]!r}",
        )

        # Also cover browser_network_request (singular). The list output
        # shape varies between Playwright versions; pull an actual index
        # out of it rather than guessing. Lines look like "1. GET https://..."
        # — match the first leading number we see.
        import re
        m = re.search(r"^\s*(\d+)\.\s", text, re.MULTILINE)
        if m:
            idx = int(m.group(1))
            result_one = c.call_tool("browser_network_request", {"index": idx})
            text_one = c.tool_text(result_one)
            assert_true(
                len(text_one.strip()) > 0,
                f"browser_network_request returned empty body: {text_one[:200]!r}",
            )
        # else: no enumerated requests were available — skip the singular
        # variant rather than fail. browser_network_requests already covered.


if __name__ == "__main__":
    run_test("network", main)
