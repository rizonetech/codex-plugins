"""Command-line helpers for the ChromeMCP Python client."""

from __future__ import annotations

import argparse
import json

from .core import McpClient, McpError, ProjectTabSession


def _client(args) -> McpClient:
    client = McpClient(url=args.url)
    client.initialize(name="chromemcp-python-cli", version="0.1.0")
    return client


def cmd_tabs(args) -> int:
    client = _client(args)
    for tab in client.list_tabs():
        marker = " *" if tab.current else "  "
        crashed = " [crashed]" if tab.crashed else ""
        print(f"{marker} {tab.index}: {tab.title} <{tab.url}>{crashed}")
    return 0


def cmd_smoke(args) -> int:
    client = _client(args)
    tabs = client.list_tabs()
    print(f"tabs: {len(tabs)}")
    snapshot = client.call_tool("browser_snapshot", {})
    lines = client.tool_text(snapshot).strip().splitlines()
    print(f"snapshot-lines: {len(lines)}")
    return 0


def cmd_eval_title(args) -> int:
    client = _client(args)
    with ProjectTabSession(client, args.session_name) as session:
        tab = session.open_data_tab("title-check", "<body>title check</body>")
        result = session.call_tool(
            "browser_evaluate",
            {"function": "() => document.title"},
            tab=tab,
        )
        value = client.tool_structured_result(result)["result"]["value"]
        print(json.dumps(value))
    return 0


def cmd_evidence(args) -> int:
    client = _client(args)
    report = client.collect_browser_evidence(level=args.level, all_messages=args.all, run_id=args.run_id)
    if args.artifact:
        path = client.write_browser_evidence_artifact(report, artifacts_dir=args.artifacts_dir)
        print(path)
    else:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if args.fail_on_errors:
        client.assert_no_high_signal_browser_errors(report, fail_on_warnings=args.fail_on_warnings)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChromeMCP Python client helper")
    parser.add_argument("--url", default="http://localhost:8931/mcp", help="MCP Streamable HTTP endpoint")
    subparsers = parser.add_subparsers(dest="command", required=True)

    tabs = subparsers.add_parser("tabs", help="List live Chrome tabs")
    tabs.set_defaults(func=cmd_tabs)

    smoke = subparsers.add_parser("smoke", help="Run initialize, tabs, and snapshot smoke checks")
    smoke.set_defaults(func=cmd_smoke)

    eval_title = subparsers.add_parser("eval-title", help="Open an isolated tab and evaluate document.title")
    eval_title.add_argument("--session-name", default="client-cli", help="Run marker for the owned tab")
    eval_title.set_defaults(func=cmd_eval_title)

    evidence = subparsers.add_parser("evidence", help="Collect structured console/page-error evidence")
    evidence.add_argument("--level", default="debug", choices=["error", "warning", "info", "debug"])
    evidence.add_argument("--all", action="store_true", help="Include all messages, not only since navigation")
    evidence.add_argument("--run-id", default=None, help="Optional run/session marker")
    evidence.add_argument("--artifact", action="store_true", help="Write JSON artifact instead of printing JSON")
    evidence.add_argument("--artifacts-dir", default="mcp/artifacts/browser-evidence")
    evidence.add_argument("--fail-on-errors", action="store_true", help="Exit non-zero on console/page errors")
    evidence.add_argument("--fail-on-warnings", action="store_true", help="Treat warnings as high-signal")
    evidence.set_defaults(func=cmd_evidence)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except McpError as e:
        parser.exit(1, f"ChromeMCP client error: {e}\n")


if __name__ == "__main__":
    raise SystemExit(main())
