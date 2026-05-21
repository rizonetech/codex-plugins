#!/usr/bin/env python3
"""Minimal ChromeMCP structured-result consumer example."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.client import McpClient  # noqa: E402


def main() -> None:
    client = McpClient()
    client.initialize(name="structured-result-example", version="0.1.0")
    result = client.call_tool(
        "browser_run_code_unsafe",
        {"code": "async (page) => ({ title: await page.title(), ok: true })"},
    )
    structured = client.tool_structured_result(result)
    print(json.dumps(structured["result"]["value"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
