#!/usr/bin/env python3
"""Covers: ChromeMCP structuredContent enrichment for eval-style tools."""
import sys
sys.path.insert(0, sys.path[0] or ".")

from _harness import assert_in, assert_true, run_test
from mcp.client import McpClient


SHAPES = [
    ("primitive", "42", 42),
    ("object", "({hello: 'world', n: 1})", {"hello": "world", "n": 1}),
    ("array", "[1, 'two', null]", [1, "two", None]),
    ("markdown-string", '"### Result\\nnot a heading"', "### Result\nnot a heading"),
    ("null", "null", None),
]


def assert_structured(result, tool_name, expected):
    structured = McpClient.tool_structured_result(result)
    assert_true(structured["schemaVersion"] == 1, "structured result schema version changed")
    assert_true(structured["tool"] == tool_name, "structured result recorded the wrong tool name")
    assert_true(structured["status"] == "ok", "structured result did not record ok status")
    assert_true(structured["result"]["value"] == expected, "structured result value mismatch")
    assert_true("### Result" in McpClient.tool_text(result), "human-readable report disappeared")


def call_in_fresh_tab(tool_name, arguments):
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url("<title>structured-fixture</title><body>structured</body>")):
        return c.call_tool(tool_name, arguments)


def main():
    for _label, expression, expected in SHAPES:
        result = call_in_fresh_tab("browser_evaluate", {"function": f"() => {expression}"})
        assert_structured(result, "browser_evaluate", expected)

        unsafe = call_in_fresh_tab("browser_run_code_unsafe", {"code": f"async (page) => {expression}"})
        assert_structured(unsafe, "browser_run_code_unsafe", expected)

    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url("<title>structured-fixture</title><body>structured</body>")):
        error_result = c.call_tool(
            "browser_evaluate",
            {"function": "() => { throw new Error('structured-boom') }"},
            allow_error=True,
        )
        structured = McpClient.tool_structured_result(error_result)
        assert_true(structured["status"] == "error", "structured error did not record error status")
        assert_in("structured-boom", structured["error"]["message"], "structured error lost message")
        assert_true(error_result.get("isError") is True, "human-readable error flag disappeared")

        unsafe_error = c.call_tool(
            "browser_run_code_unsafe",
            {"code": "async (page) => { throw new Error('structured-unsafe-boom') }"},
            allow_error=True,
        )
        structured = McpClient.tool_structured_result(unsafe_error)
        assert_true(structured["status"] == "error", "structured unsafe error did not record error status")
        assert_in("structured-unsafe-boom", structured["error"]["message"], "structured unsafe error lost message")
        assert_true(unsafe_error.get("isError") is True, "human-readable unsafe error flag disappeared")


if __name__ == "__main__":
    run_test("structured_results", main)
