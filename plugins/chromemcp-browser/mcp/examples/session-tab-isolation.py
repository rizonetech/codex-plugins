#!/usr/bin/env python3
"""Manual smoke for project tab-session isolation.

Run with the MCP server already started:

    python3 mcp/examples/session-tab-isolation.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mcp.client import McpClient, ProjectTabSession  # noqa: E402


def main() -> None:
    client = McpClient()
    client.initialize()

    with ProjectTabSession(client, "example-session") as session:
        first = session.open_data_tab("alpha", "<body>alpha</body>")
        second = session.open_data_tab("beta", "<body>beta</body>")
        session.client.select_tab_verified(
            first.index,
            expected_url=first.url,
            expected_title=first.title,
        )

        result = session.call_tool("browser_evaluate", {"function": "() => document.title"})
        print(f"active owned tab: {client.tool_text(result).strip()}")
        print(f"owned titles: {first.title}, {second.title}")

    listing = client.tool_text(client.call_tool("browser_tabs", {"action": "list"}))
    print(f"cleanup removed example tabs: {'example-session' not in listing}")


if __name__ == "__main__":
    main()
