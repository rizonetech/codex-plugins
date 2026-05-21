#!/usr/bin/env python3
"""Covers: browser_tabs (list / new / close), browser_close."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, assert_not_in, run_test
from mcp.client import McpClient, McpToolError


def main():
    c = McpClient()
    c.initialize()

    # baseline list
    before = c.tool_text(c.call_tool("browser_tabs", {"action": "list"}))

    # open a new tab with a recognizable title
    idx = c.open_new_tab(
        c.data_url("<title>tabs-fixture-titlemarker</title><body>x</body>"),
        expected_title="tabs-fixture-titlemarker",
    )
    after_open = c.tool_text(c.call_tool("browser_tabs", {"action": "list"}))
    assert_in("tabs-fixture-titlemarker", after_open, "newly opened tab not in list")

    # browser_close closes the current page (different surface from browser_tabs close).
    # We use browser_tabs close explicitly to cover the close action.
    c.close_tab(idx)
    after_close = c.tool_text(c.call_tool("browser_tabs", {"action": "list"}))
    assert_not_in("tabs-fixture-titlemarker", after_close, "tab still present after close")

    tab_a = c.open_new_tab(
        c.data_url("<title>tabs-target-a</title><body>a</body>"),
        expected_title="tabs-target-a",
    )
    tab_b = c.open_new_tab(
        c.data_url("<title>tabs-target-b</title><body>b</body>"),
        expected_title="tabs-target-b",
    )
    try:
        c.select_tab_verified(tab_b, expected_title="tabs-target-b")
        try:
            c.select_tab_verified(tab_a, expected_title="tabs-target-b")
        except McpToolError as e:
            assert_in("selected wrong tab", str(e), "wrong-tab selection did not fail loudly")
        else:
            raise AssertionError("wrong-tab selection was not detected")
    finally:
        c.close_tab_verified(expected_title="tabs-target-a")
        c.close_tab_verified(expected_title="tabs-target-b")


if __name__ == "__main__":
    run_test("tabs", main)
