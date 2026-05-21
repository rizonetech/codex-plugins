#!/usr/bin/env python3
"""Collect structured console/page-error evidence without parsing Markdown."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.client import BrowserEvidenceError, McpClient, ProjectTabSession  # noqa: E402


HTML = """<!doctype html><title>browser-evidence-example</title>
<script>
  console.warn("example-warning-marker");
  setTimeout(() => { throw new Error("example-page-error-marker"); }, 0);
</script>
<body>browser evidence example</body>
"""


def main() -> None:
    client = McpClient()
    client.initialize(name="browser-evidence-example", version="0.1.0")

    with ProjectTabSession(client, "browser-evidence-example") as session:
        tab = session.open_tab(client.data_url(HTML), expected_title="browser-evidence-example", label="fixture")
        session.select_tab(tab)
        time.sleep(1)
        report = client.collect_browser_evidence(run_id=session.run_id)
        artifact = client.write_browser_evidence_artifact(report)
        print(f"entries={report.total} errors={len(report.errors)} warnings={len(report.warnings)}")
        print(f"artifact={artifact}")
        try:
            client.assert_no_high_signal_browser_errors(report)
        except BrowserEvidenceError as exc:
            print(str(exc).splitlines()[0])


if __name__ == "__main__":
    main()
