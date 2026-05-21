#!/usr/bin/env python3
"""Covers: browser_snapshot (accessibility tree shape sanity)."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, assert_true, run_test
from mcp.client import McpClient


HTML = """<!doctype html><title>snapshot-fixture</title>
<h1>Snapshot title heading</h1>
<button>snapshot-button-label</button>
<a href="#">snapshot-link-label</a>
<input type="text" aria-label="snapshot-input-label">
"""


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url(HTML)):
        result = c.call_tool("browser_snapshot", {})
        text = c.tool_text(result)
        # Each element from the fixture should be reflected in the a11y tree.
        for marker in (
            "snapshot-button-label",
            "snapshot-link-label",
            "snapshot-input-label",
            "Snapshot title heading",
        ):
            assert_in(marker, text, f"a11y tree missing {marker}")
        # Snapshots from Playwright MCP carry [ref=eN] tags used by click/type/etc.
        assert_true("[ref=" in text, "snapshot has no [ref=...] tags — clicks/types won't work")


if __name__ == "__main__":
    run_test("snapshot", main)
