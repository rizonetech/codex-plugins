#!/usr/bin/env python3
"""Covers: browser_console_messages."""
import sys
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, run_test
from mcp.client import McpClient


HTML = """<!doctype html><title>console-fixture</title>
<script>
  console.log('console-marker-line-' + Date.now());
  console.warn('console-warn-marker');
</script>
"""


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url(HTML)):
        result = c.call_tool("browser_console_messages", {})
        text = c.tool_text(result)
        assert_in("console-marker-line-", text, "console.log() output not captured")
        assert_in("console-warn-marker", text, "console.warn() output not captured")
        report = c.collect_browser_evidence()
        assert_in("console-marker-line-", " ".join(entry.text for entry in report.entries), "structured console log missing")
        assert_in("console-warn-marker", " ".join(entry.text for entry in report.entries), "structured console warn missing")


if __name__ == "__main__":
    run_test("console", main)
