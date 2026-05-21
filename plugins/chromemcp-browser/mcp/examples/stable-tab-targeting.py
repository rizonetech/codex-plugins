#!/usr/bin/env python3
"""Manual smoke for ChromeMCP's verified tab-targeting harness helpers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.client import McpClient  # noqa: E402


def main() -> None:
    client = McpClient()
    client.initialize()

    first_url = client.data_url("<title>stable-tab-alpha</title><body>alpha</body>")
    second_url = client.data_url("<title>stable-tab-beta</title><body>beta</body>")

    first = client.open_new_tab(first_url, expected_title="stable-tab-alpha")
    second = client.open_new_tab(second_url, expected_title="stable-tab-beta")

    try:
        selected = client.select_tab_verified(
            second,
            expected_url=second_url,
            expected_title="stable-tab-beta",
        )
        print(f"selected index={selected.index} title={selected.title}")

        try:
            client.select_tab_verified(
                first,
                expected_url=second_url,
                expected_title="stable-tab-beta",
            )
        except Exception as exc:
            print(f"wrong-tab guard fired: {exc}")
        else:
            raise SystemExit("wrong-tab guard did not fire")
    finally:
        client.close_tab_verified(expected_url=first_url, expected_title="stable-tab-alpha")
        client.close_tab_verified(expected_url=second_url, expected_title="stable-tab-beta")


if __name__ == "__main__":
    main()
