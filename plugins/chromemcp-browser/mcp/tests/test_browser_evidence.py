#!/usr/bin/env python3
"""Covers: structured console/page-error evidence and artifact output."""
import json
import sys
import tempfile
import time

sys.path.insert(0, sys.path[0] or ".")

from _harness import assert_in, assert_not_in, assert_true, run_test
from mcp.client import BrowserEvidenceError, McpClient, ProjectTabSession


HTML = """<!doctype html><title>browser-evidence-fixture</title>
<script>
  console.log("todo06-log-marker");
  console.warn("todo06-warning-marker");
  console.error("todo06-error-marker token=todo06-token-secret-alpha");
  setTimeout(() => { throw new Error("todo06-page-error-marker password=todo06-password-secret-beta"); }, 0);
</script>
<body>browser evidence</body>
"""


def main():
    c = McpClient()
    c.initialize()

    with ProjectTabSession(c, "browser-evidence") as session:
        tab = session.open_tab(c.data_url(HTML), expected_title="browser-evidence-fixture", label="fixture")
        session.select_tab(tab)
        time.sleep(1)

        report = c.collect_browser_evidence(run_id=session.run_id)
        assert_true(report.total >= 4, "expected console and page-error entries")
        assert_true(any(e.kind == "console" and e.severity == "warning" for e in report.entries), "warning missing")
        assert_true(any(e.kind == "console" and e.severity == "error" for e in report.entries), "console error missing")
        assert_true(any(e.kind == "page_error" for e in report.entries), "page error missing")

        serialized = json.dumps(report.to_dict(), sort_keys=True)
        assert_in("todo06-log-marker", serialized, "log marker missing from structured evidence")
        assert_in("todo06-page-error-marker", serialized, "page error marker missing from structured evidence")
        assert_not_in("todo06-token-secret-alpha", serialized, "token sentinel leaked")
        assert_not_in("todo06-password-secret-beta", serialized, "password sentinel leaked")
        assert_not_in("data:text/html", serialized, "data URL leaked into evidence")

        try:
            c.assert_no_high_signal_browser_errors(report)
        except BrowserEvidenceError as e:
            assert_in("todo06-error-marker", str(e), "high-signal failure summary missing console error")
            assert_in("todo06-page-error-marker", str(e), "high-signal failure summary missing page error")
        else:
            raise AssertionError("high-signal browser errors did not fail")

        with tempfile.TemporaryDirectory() as tmp:
            artifact_path = c.write_browser_evidence_artifact(report, artifacts_dir=tmp, max_files=3)
            payload = artifact_path.read_text(encoding="utf-8")
            assert_in('"schema_version": 1', payload, "artifact schema missing")
            assert_in("todo06-warning-marker", payload, "artifact missing warning")
            assert_not_in("todo06-token-secret-alpha", payload, "token sentinel leaked to artifact")
            assert_not_in("todo06-password-secret-beta", payload, "password sentinel leaked to artifact")


if __name__ == "__main__":
    run_test("browser_evidence", main)
