#!/usr/bin/env python3
"""Covers: browser_select_option."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, run_test
from mcp.client import McpClient


HTML = """<!doctype html><title>select-fixture</title>
<select id=s onchange="document.getElementById('out').textContent='picked-' + this.value">
  <option value="alpha">Alpha</option>
  <option value="beta">Beta</option>
  <option value="gamma">Gamma</option>
</select>
<div id=out>idle</div>
"""


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url(HTML)):
        snap = c.tool_text(c.call_tool("browser_snapshot", {}))
        # Find the select element ref.
        ref = None
        for line in snap.splitlines():
            if "combobox" in line.lower() or "select" in line.lower():
                if "[ref=" in line:
                    s = line.index("[ref=") + len("[ref=")
                    ref = line[s:line.index("]", s)]
                    break
        if not ref:
            raise AssertionError(f"no select ref in snapshot:\n{snap[:500]}")
        c.call_tool(
            "browser_select_option",
            {"element": "demo select", "target": ref, "values": ["beta"]},
        )
        after = c.tool_text(c.call_tool("browser_snapshot", {}))
        assert_in("picked-beta", after, "select did not fire onchange with value 'beta'")


if __name__ == "__main__":
    run_test("select", main)
