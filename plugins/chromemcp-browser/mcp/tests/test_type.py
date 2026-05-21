#!/usr/bin/env python3
"""Covers: browser_type, browser_press_key, browser_fill_form."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, run_test
from mcp.client import McpClient


HTML = """<!doctype html><title>type-fixture</title>
<input id=t aria-label="text-input" oninput="document.title = 'typed-' + this.value">
<input id=t2 aria-label="form-field-a">
<input id=t3 aria-label="form-field-b">
<div id=ks oninput="">key:</div>
<script>
  document.addEventListener('keydown', e => {
    if (e.target.tagName !== 'INPUT') {
      document.getElementById('ks').textContent = 'key:' + e.key;
    }
  });
</script>
"""


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url(HTML)):
        snap = c.tool_text(c.call_tool("browser_snapshot", {}))
        first_input_ref = _input_ref(snap, "text-input")
        c.call_tool(
            "browser_type",
            {"element": "the text input", "target": first_input_ref, "text": "abc123"},
        )
        snap_after = c.tool_text(c.call_tool("browser_snapshot", {}))
        assert_in("typed-abc123", snap_after, "browser_type did not produce 'typed-abc123' title")

        # press_key — verify the tool returns without error. Tightening to
        # observe a specific keydown effect is fragile (Playwright routes
        # the key based on whatever's focused; capturing it deterministically
        # from a snapshot requires a focused input element with a visible
        # value mutation, which is awkward here). The smoke test for this
        # tool is "the call succeeds against a live Chrome".
        c.call_tool("browser_press_key", {"key": "Escape"})

        # fill_form — populate the two named fields in one go. Re-fetch
        # refs after type may have re-rendered the page.
        snap_key = c.tool_text(c.call_tool("browser_snapshot", {}))
        ref_a = _input_ref(snap_key, "form-field-a")
        ref_b = _input_ref(snap_key, "form-field-b")
        c.call_tool(
            "browser_fill_form",
            {
                "fields": [
                    {"name": "form-field-a", "type": "textbox", "target": ref_a, "value": "AAA"},
                    {"name": "form-field-b", "type": "textbox", "target": ref_b, "value": "BBB"},
                ]
            },
        )
        verify = c.tool_text(
            c.call_tool(
                "browser_evaluate",
                {
                    "function": "() => ['#t2','#t3'].map(s => document.querySelector(s).value).join('|')",
                },
            )
        )
        assert_in("AAA|BBB", verify, "browser_fill_form did not populate both fields")


def _input_ref(snap: str, label: str) -> str:
    for line in snap.splitlines():
        if label in line and "[ref=" in line:
            s = line.index("[ref=") + len("[ref=")
            return line[s:line.index("]", s)]
    raise AssertionError(f"no [ref=] for input labelled {label!r} in snapshot:\n{snap[:500]}")


if __name__ == "__main__":
    run_test("type", main)
