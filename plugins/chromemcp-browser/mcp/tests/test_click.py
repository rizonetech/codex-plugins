#!/usr/bin/env python3
"""Covers: browser_click, browser_hover."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, run_test
from mcp.client import McpClient, ProjectTabSession


HTML = """<!doctype html><title>click-fixture</title>
<button id=btn onclick="document.getElementById('out').textContent='clicked-marker'">Press</button>
<div id=out>idle</div>
<div id=hover-target onmouseenter="document.getElementById('out').textContent='hover-marker'">hover me</div>
"""


def main():
    c = McpClient()
    c.initialize()
    with ProjectTabSession(c, "click-test") as session:
        fixture_url = c.data_url(HTML)
        tab = session.open_tab(fixture_url, expected_title="click-fixture", label="click-fixture")
        session.select_tab(tab)
        snap = c.tool_text(c.call_tool("browser_snapshot", {}))
        # The snapshot is YAML with refs like [ref=e1] that browser_click needs.
        # Find the button's ref.
        btn_ref = _ref_after_keyword(snap, "Press")
        c.call_tool(
            "browser_click",
            {"element": "Press button", "target": btn_ref},
        )
        snap_after = c.tool_text(c.call_tool("browser_snapshot", {}))
        assert_in("clicked-marker", snap_after, "click did not mutate page state")

        # Reload the page state by re-navigating to the same data url for
        # a clean baseline, then hover.
        session.call_tool("browser_navigate", {"url": fixture_url}, tab=tab)
        session.select_tab(tab)
        snap = c.tool_text(c.call_tool("browser_snapshot", {}))
        hover_ref = _ref_after_keyword(snap, "hover me")
        c.call_tool(
            "browser_hover",
            {"element": "hover target", "target": hover_ref},
        )
        snap_after = c.tool_text(c.call_tool("browser_snapshot", {}))
        assert_in("hover-marker", snap_after, "hover did not fire mouseenter")


def _ref_after_keyword(snapshot_yaml: str, keyword: str) -> str:
    """Find the [ref=...] tag of the first node whose serialization mentions `keyword`."""
    for line in snapshot_yaml.splitlines():
        if keyword in line and "[ref=" in line:
            start = line.index("[ref=") + len("[ref=")
            end = line.index("]", start)
            return line[start:end]
    raise AssertionError(f"no ref found for keyword {keyword!r} in snapshot:\n{snapshot_yaml[:500]}")


if __name__ == "__main__":
    run_test("click", main)
