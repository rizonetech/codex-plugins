#!/usr/bin/env python3
"""Covers: browser_evaluate, browser_run_code_unsafe."""
import sys
sys.path.insert(0, sys.path[0] or ".")
import json

from _harness import assert_in, run_test
from mcp.client import McpClient


FIXTURE_HTML = "<title>eval-fixture</title><body>seven</body>"


def call_in_fresh_tab(tool_name, arguments):
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url(FIXTURE_HTML)):
        return c.call_tool(tool_name, arguments)


def main():
    c = McpClient()
    c.initialize()
    with c.scoped_tab(c.data_url(FIXTURE_HTML)):
        # Primitive return value
        r1 = c.call_tool("browser_evaluate", {"function": "() => 6 * 7"})
        text1 = c.tool_text(r1)
        assert_in("42", text1, "evaluate did not return 42 for 6*7")

        # Object return value (Playwright serializes via JSON)
        r2 = c.call_tool(
            "browser_evaluate",
            {"function": "() => ({hello: 'world', n: 1})"},
        )
        text2 = c.tool_text(r2)
        assert_in("hello", text2, "evaluate did not surface object key 'hello'")
        assert_in("world", text2, "evaluate did not surface object value 'world'")

        # run_code_unsafe takes a Playwright async function `(page) => ...`
        # per its schema description. We use it to read the page title via
        # Playwright's own API, which is deterministic for our fixture.
        r3 = call_in_fresh_tab(
            "browser_run_code_unsafe",
            {"code": "async (page) => await page.title()"},
        )
        text3 = c.tool_text(r3)
        assert_in("eval-fixture", text3, "run_code_unsafe did not return document.title")

        secret_sentinels = [
            "todo01-cookie-secret-alpha",
            "todo01-cookie-header-secret-beta",
            "todo01-bearer-secret-gamma",
            "todo01-token-secret-delta",
            "todo01-access-token-secret-epsilon",
            "todo01-refresh-token-secret-zeta",
            "todo01-api-key-secret-eta",
            "todo01-secret-field-theta",
            "todo01-password-secret-iota",
        ]
        secret_code = """
async (page) => {
  const cookie = "todo01-cookie-secret-alpha";
  const cookies = [{ name: "session", value: "todo01-cookie-header-secret-beta" }];
  const token = "todo01-token-secret-delta";
  const access_token = "todo01-access-token-secret-epsilon";
  const refresh_token = "todo01-refresh-token-secret-zeta";
  const api_key = "todo01-api-key-secret-eta";
  const secret = "todo01-secret-field-theta";
  const password = "todo01-password-secret-iota";
  if (false) {
    await page.context().setExtraHTTPHeaders({
      Cookie: `wordpress_logged_in=${cookie}; session=${cookies[0].value}`,
      Authorization: "Bearer todo01-bearer-secret-gamma",
      "x-api-key": api_key,
    });
  }
  return `non-secret-result-marker:${token}:${access_token}:${refresh_token}:${secret}:${password}`;
}
"""
        r4 = call_in_fresh_tab("browser_run_code_unsafe", {"code": secret_code})
        text4 = c.tool_text(r4)
        raw4 = json.dumps(r4, sort_keys=True)
        assert_in(
            "non-secret-result-marker",
            text4,
            "run_code_unsafe did not preserve useful non-secret result context",
        )
        if "[REDACTED" not in raw4:
            raise AssertionError("run_code_unsafe did not mark redacted report output")
        for sentinel in secret_sentinels:
            if sentinel in text4 or sentinel in raw4:
                raise AssertionError("run_code_unsafe leaked a secret sentinel in report output")


if __name__ == "__main__":
    run_test("evaluate", main)
