#!/usr/bin/env python3
"""Covers: public ChromeMCP client module import and token lookup contract."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, sys.path[0] or ".")

from _harness import assert_true, run_test
from mcp.client import McpClient, McpToolError, ProjectTabSession, TabInfo, read_token


def main():
    class StaleIndexClient(McpClient):
        def __init__(self):
            self.list_calls = 0
            self.selected = []
            self.closed = []

        def list_tabs(self):
            self.list_calls += 1
            if self.list_calls == 1:
                return [TabInfo(index=12, current=False, title="Target", url="https://example.test")]
            if self.list_calls == 2:
                return [TabInfo(index=3, current=False, title="Target", url="https://example.test")]
            return []

        def call_tool(self, name, arguments=None, allow_error=False):
            arguments = arguments or {}
            if name == "browser_tabs" and arguments.get("action") == "select":
                self.selected.append(arguments["index"])
                if arguments["index"] == 12:
                    raise McpToolError("browser_tabs returned isError: Error: Tab 12 not found")
                return {"content": [{"type": "text", "text": ""}]}
            if name == "browser_tabs" and arguments.get("action") == "close":
                self.closed.append(arguments["index"])
                return {"content": [{"type": "text", "text": ""}]}
            raise AssertionError(f"unexpected tool call {name} {arguments}")

        def current_tab(self):
            index = self.selected[-1]
            return TabInfo(index=index, current=True, title="Target", url="https://example.test")

    assert_true(McpClient.__module__.startswith("mcp.client"), "McpClient is not public")
    assert_true(ProjectTabSession.__module__.startswith("mcp.client"), "ProjectTabSession is not public")

    old_env = {
        key: os.environ.get(key)
        for key in ("MCP_AUTH_TOKEN", "MCP_NO_AUTH", "MCP_TOKEN_PATH", "XDG_CONFIG_HOME")
    }
    try:
        os.environ.pop("MCP_NO_AUTH", None)
        os.environ["MCP_AUTH_TOKEN"] = "env-token-check"
        assert_true(read_token() == "env-token-check", "MCP_AUTH_TOKEN did not win")

        os.environ.pop("MCP_AUTH_TOKEN", None)
        with tempfile.TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "chromemcp-token"
            token_path.write_text(" file-token-check \n", encoding="utf-8")
            os.environ["MCP_TOKEN_PATH"] = str(token_path)
            assert_true(read_token() == "file-token-check", "MCP_TOKEN_PATH was not read")

        os.environ["MCP_NO_AUTH"] = "1"
        assert_true(read_token() is None, "MCP_NO_AUTH=1 should disable token lookup")

        stale = StaleIndexClient()
        stale.close_tab_verified(expected_url="https://example.test", expected_title="Target")
        assert_true(stale.selected == [12, 3], "stale tab index was not retried")
        assert_true(stale.closed == [3], "refreshed tab index was not closed")
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    run_test("client_module", main)
