"""ChromeMCP regression-test harness.

The supported client implementation lives in ``mcp.client``. This module keeps
test-only assertion helpers and re-exports the public client classes for older
tests and examples that still import ``_harness``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.client import (  # noqa: E402
    DEFAULT_TIMEOUT,
    DEFAULT_URL,
    McpClient,
    McpError,
    McpHttpError,
    McpProtocolError,
    McpToolError,
    OwnedTab,
    ProjectTabSession,
    TabInfo,
    read_token,
)


def fail(msg: str) -> None:
    sys.stderr.write(f"FAIL: {msg}\n")
    raise SystemExit(1)


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def assert_in(needle: str, haystack: str, msg: str) -> None:
    if needle not in haystack:
        fail(f"{msg} (expected substring {needle!r} not in {haystack[:200]!r})")


def assert_not_in(needle: str, haystack: str, msg: str) -> None:
    if needle in haystack:
        fail(f"{msg} (unexpected substring {needle!r} found in {haystack[:200]!r})")


def run_test(name: str, body) -> None:
    started = time.monotonic()
    try:
        body()
    except Exception as e:
        sys.stderr.write(f"FAIL {name}: {e}\n")
        raise SystemExit(1)
    elapsed = time.monotonic() - started
    print(f"PASS {name} ({elapsed:.2f}s)")


__all__ = [
    "DEFAULT_TIMEOUT",
    "DEFAULT_URL",
    "McpClient",
    "McpError",
    "McpHttpError",
    "McpProtocolError",
    "McpToolError",
    "OwnedTab",
    "ProjectTabSession",
    "TabInfo",
    "read_token",
    "fail",
    "assert_true",
    "assert_in",
    "assert_not_in",
    "run_test",
]
