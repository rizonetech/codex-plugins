#!/usr/bin/env python3
"""Covers: browser_navigate, browser_navigate_back, browser_wait_for."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, run_test
from mcp.client import McpClient


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url("<title>nav-1</title><body>first</body>")) as _idx:
        # browser_navigate to a different page in the same tab
        c.call_tool(
            "browser_navigate",
            {"url": c.data_url("<title>nav-2</title><body>second-page-text</body>")},
        )
        snap1 = c.tool_text(c.call_tool("browser_snapshot", {}))
        assert_in("nav-2", snap1, "browser_navigate did not change page title")

        # browser_wait_for: text "second-page-text" should already be there
        c.call_tool("browser_wait_for", {"text": "second-page-text", "time": 2})

        # browser_navigate_back to the first page
        c.call_tool("browser_navigate_back", {})
        snap2 = c.tool_text(c.call_tool("browser_snapshot", {}))
        assert_in("nav-1", snap2, "browser_navigate_back did not return to first page")


if __name__ == "__main__":
    run_test("navigate", main)
