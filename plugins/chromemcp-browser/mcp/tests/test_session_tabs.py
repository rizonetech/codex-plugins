#!/usr/bin/env python3
"""Covers: project tab-session ownership, cleanup, and failure preservation."""
import sys
import uuid
sys.path.insert(0, sys.path[0] or ".")
from _harness import assert_in, assert_not_in, run_test
from mcp.client import McpClient, ProjectTabSession


class IntentionalPreservationError(Exception):
    pass


def tab_titles(client):
    return "\n".join(tab.title for tab in client.list_tabs())


def main():
    c = McpClient()
    c.initialize()

    unrelated_title = f"session-unrelated-survivor-{uuid.uuid4().hex[:8]}"
    unrelated_url = c.data_url(f"<title>{unrelated_title}</title><body>keep</body>")
    c.open_new_tab(unrelated_url, expected_title=unrelated_title)

    try:
        with ProjectTabSession(c, "session-cleanup") as session:
            owned_a = session.open_data_tab("session-owned-a", "<body>a</body>")
            owned_b = session.open_data_tab("session-owned-b", "<body>b</body>")

            c.select_tab_verified(owned_a.index, expected_url=owned_a.url, expected_title=owned_a.title)
            result = session.call_tool("browser_evaluate", {"function": "() => document.title"})
            assert_in(owned_b.title, c.tool_text(result), "session did not restore its active owned tab")

        after_cleanup = tab_titles(c)
        assert_not_in(owned_a.title, after_cleanup, "owned tab a survived normal cleanup")
        assert_not_in(owned_b.title, after_cleanup, "owned tab b survived normal cleanup")
        assert_in(unrelated_title, after_cleanup, "unrelated tab was closed by session cleanup")

        preserved = None
        try:
            with ProjectTabSession(c, "session-preserve", preserve_on_failure=True) as session:
                preserved = session.open_data_tab("session-preserved-debug", "<body>debug</body>")
                raise IntentionalPreservationError("intentional preservation check")
        except IntentionalPreservationError:
            pass

        after_failure = tab_titles(c)
        assert_in("session-preserved-debug", after_failure, "failed-run tab was not preserved")
        assert_in("session-preserve", after_failure, "preserved tab was not clearly marked with run ownership")

        c.close_tab_verified(expected_url=preserved.url, expected_title=preserved.title)
    finally:
        c.close_tab_verified(expected_url=unrelated_url, expected_title=unrelated_title)


if __name__ == "__main__":
    run_test("session_tabs", main)
