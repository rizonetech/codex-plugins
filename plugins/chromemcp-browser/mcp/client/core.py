"""Dependency-light Python client for ChromeMCP's MCP HTTP endpoint."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Optional


DEFAULT_URL = os.environ.get("MCP_URL", "http://localhost:8931/mcp")
DEFAULT_TIMEOUT = float(os.environ.get("MCP_TEST_TIMEOUT", os.environ.get("MCP_TIMEOUT", "30")))


class McpError(RuntimeError):
    """Base exception for ChromeMCP client failures."""


class McpHttpError(McpError):
    """Raised when the MCP endpoint returns an HTTP error."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:300]}")


class McpProtocolError(McpError):
    """Raised when the MCP transport response cannot be decoded."""


class McpToolError(McpError):
    """Raised when a JSON-RPC or tool-level error occurs."""


class BrowserEvidenceError(McpError):
    """Raised when collected browser evidence contains high-signal failures."""


SECRET_KEY_PATTERN = re.compile(
    r"\b(cookie|cookies|authorization|bearer|token|access_token|refresh_token|api_key|x-api-key|secret|password)\b"
    r"\s*[:=]\s*([^\s,;]+)",
    re.IGNORECASE,
)


def redact_text(value: str) -> str:
    redacted = re.sub(r"\bBearer\s+([A-Za-z0-9._~+/=-]{8,})", "Bearer [REDACTED:authorization]", value, flags=re.IGNORECASE)

    def replace_secret(match: re.Match[str]) -> str:
        key = match.group(1)
        normalized = key.lower().replace("-", "_")
        if normalized == "bearer":
            normalized = "authorization"
        return f"{key}=[REDACTED:{normalized}]"

    redacted = SECRET_KEY_PATTERN.sub(replace_secret, redacted)
    return redacted


def redact_url(value: str) -> str:
    if value.startswith("data:"):
        return "data:[REDACTED:data-url]"
    return redact_text(value)


@dataclass(frozen=True)
class BrowserEvidenceEntry:
    kind: str
    severity: str
    text: str
    source_url: Optional[str] = None
    line: Optional[int] = None
    timestamp: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "text": self.text,
            "source_url": self.source_url,
            "line": self.line,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class BrowserEvidenceReport:
    collected_at: str
    tab_title: str
    tab_url: str
    run_id: Optional[str]
    entries: list[BrowserEvidenceEntry]
    raw_summary: str

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def errors(self) -> list[BrowserEvidenceEntry]:
        return [entry for entry in self.entries if entry.severity == "error"]

    @property
    def warnings(self) -> list[BrowserEvidenceEntry]:
        return [entry for entry in self.entries if entry.severity == "warning"]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "collected_at": self.collected_at,
            "tab": {
                "title": self.tab_title,
                "url": self.tab_url,
                "run_id": self.run_id,
            },
            "summary": {
                "total": self.total,
                "errors": len(self.errors),
                "warnings": len(self.warnings),
            },
            "entries": [entry.to_dict() for entry in self.entries],
            "raw_summary": self.raw_summary,
        }


def read_token() -> Optional[str]:
    """Read ChromeMCP bearer token from env or the default config path."""

    if os.environ.get("MCP_NO_AUTH") == "1":
        return None
    env = os.environ.get("MCP_AUTH_TOKEN")
    if env:
        return env.strip()
    token_path = (
        os.environ.get("MCP_TOKEN_PATH")
        or str(
            Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            / "chromemcp"
            / "token"
        )
    )
    try:
        return Path(token_path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


@dataclass(frozen=True)
class TabInfo:
    index: int
    current: bool
    title: str
    url: str
    crashed: bool = False


@dataclass
class OwnedTab:
    index: int
    url: str
    title: str
    label: str


class McpClient:
    def __init__(self, url: str = DEFAULT_URL, token: Optional[str] = None):
        self.url = url
        self.token = token if token is not None else read_token()
        self.sid: Optional[str] = None
        self._next_id = 1

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        return headers

    def post(self, payload: dict, expect_response: bool = True, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        body = ""
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                self.sid = (
                    response.headers.get("mcp-session-id")
                    or response.headers.get("Mcp-Session-Id")
                    or self.sid
                )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise McpHttpError(e.code, body) from e

        if not expect_response:
            return None

        sse_payloads = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
        if sse_payloads:
            return json.loads(sse_payloads[-1])
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as e:
            raise McpProtocolError(f"invalid JSON response: {body[:200]!r}") from e

    def initialize(self, name: str = "chromemcp-python-client", version: str = "0.1.0") -> dict:
        self._next_id = 1
        try:
            resp = self.post(
                {
                    "jsonrpc": "2.0",
                    "id": self._next_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": name, "version": version},
                    },
                }
            )
        except McpHttpError as e:
            if e.status == 401:
                raise McpToolError(
                    "initialize failed with 401; set MCP_AUTH_TOKEN, run ./mcp-up, "
                    "or set MCP_NO_AUTH=1 for a no-auth server"
                ) from e
            if e.status == 503:
                raise McpToolError("initialize failed with 503; ChromeMCP or Chrome is unavailable") from e
            raise
        self._next_id += 1
        if not resp or "error" in resp:
            raise McpToolError(f"initialize failed: {resp.get('error') if resp else 'no response'}")
        self.post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            expect_response=False,
        )
        return resp["result"]

    def call_tool(self, name: str, arguments: Optional[dict] = None, allow_error: bool = False) -> dict:
        resp: Optional[dict] = None
        for attempt in range(2):
            rid = self._next_id
            self._next_id += 1
            try:
                resp = self.post(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments or {}},
                    }
                )
                if resp is None and attempt == 0:
                    self.sid = None
                    self.initialize()
                    continue
                break
            except McpProtocolError as e:
                if attempt == 0 and "Session not found" in str(e):
                    self.sid = None
                    self.initialize()
                    continue
                raise
            except McpHttpError as e:
                if attempt == 0 and e.status == 404 and "Session not found" in e.body:
                    self.sid = None
                    self.initialize()
                    continue
                if e.status == 401:
                    raise McpToolError(f"{name}: 401 unauthorized; check MCP_AUTH_TOKEN or MCP_TOKEN_PATH") from e
                if e.status == 503:
                    raise McpToolError(f"{name}: 503 unavailable; ChromeMCP or Chrome is not ready") from e
                raise

        if not resp or "error" in resp:
            raise McpToolError(f"{name}: {resp.get('error') if resp else 'no response'}")
        result = resp["result"]
        if result.get("isError") and not allow_error:
            text = self.tool_text(result)
            raise McpToolError(f"{name} returned isError: {text[:400]}")
        return result

    @staticmethod
    def tool_text(result: dict) -> str:
        return next(
            (content.get("text", "") for content in result.get("content", []) if content.get("type") == "text"),
            "",
        )

    @staticmethod
    def tool_structured_result(result: dict) -> dict:
        return result["structuredContent"]["chromemcp"]

    @staticmethod
    def tool_image(result: dict) -> Optional[dict]:
        for content in result.get("content", []):
            if content.get("type") == "image" and (content.get("data") or content.get("uri")):
                return content
        return None

    @staticmethod
    def data_url(html: str) -> str:
        encoded = base64.b64encode(html.encode("utf-8")).decode("ascii")
        return f"data:text/html;base64,{encoded}"

    @staticmethod
    def parse_browser_evidence(text: str, collected_at: Optional[str] = None) -> list[BrowserEvidenceEntry]:
        timestamp = collected_at or datetime.now(timezone.utc).isoformat()
        entries: list[BrowserEvidenceEntry] = []
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip("\n")
            message = re.match(r"^\[([A-Z]+)\] (.*?)(?: @ (.*):(\d+))?$", line)
            if message:
                message_type = message.group(1).lower()
                severity = "warning" if message_type in ("warning", "warn") else "error" if message_type == "error" else "info"
                source = redact_url(message.group(3) or "")
                entries.append(
                    BrowserEvidenceEntry(
                        kind="console",
                        severity=severity,
                        text=redact_text(message.group(2)),
                        source_url=source or None,
                        line=int(message.group(4)) if message.group(4) else None,
                        timestamp=timestamp,
                    )
                )
                i += 1
                continue
            if line.startswith("Error:") or line.startswith("TypeError:") or line.startswith("ReferenceError:"):
                stack = [line]
                i += 1
                while i < len(lines) and not lines[i].startswith("["):
                    if lines[i].strip():
                        stack.append(lines[i])
                    i += 1
                source_url: Optional[str] = None
                source_line: Optional[int] = None
                for stack_line in stack[1:]:
                    stack_match = re.search(r"\s+at (.*):(\d+):(\d+)", stack_line)
                    if stack_match:
                        source_url = redact_url(stack_match.group(1))
                        source_line = int(stack_match.group(2))
                        break
                entries.append(
                    BrowserEvidenceEntry(
                        kind="page_error",
                        severity="error",
                        text=redact_text(stack[0]),
                        source_url=source_url,
                        line=source_line,
                        timestamp=timestamp,
                    )
                )
                continue
            i += 1
        return entries

    def clear_browser_evidence(self) -> None:
        self.call_tool("browser_console_clear", {})

    def collect_browser_evidence(
        self,
        level: str = "debug",
        all_messages: bool = False,
        run_id: Optional[str] = None,
    ) -> BrowserEvidenceReport:
        collected_at = datetime.now(timezone.utc).isoformat()
        current = self.current_tab()
        result = self.call_tool("browser_console_messages", {"level": level, "all": all_messages})
        text = self.tool_text(result)
        entries = self.parse_browser_evidence(text, collected_at=collected_at)
        summary = next((line for line in text.splitlines() if line.startswith("Total messages:")), "")
        return BrowserEvidenceReport(
            collected_at=collected_at,
            tab_title=redact_text(current.title),
            tab_url=redact_url(current.url),
            run_id=redact_text(run_id) if run_id else None,
            entries=entries,
            raw_summary=redact_text(summary),
        )

    @staticmethod
    def assert_no_high_signal_browser_errors(
        report: BrowserEvidenceReport,
        allowed_text_patterns: Optional[list[str]] = None,
        fail_on_warnings: bool = False,
    ) -> None:
        allowed = [re.compile(pattern) for pattern in (allowed_text_patterns or [])]
        offending: list[BrowserEvidenceEntry] = []
        for entry in report.entries:
            high_signal = entry.severity == "error" or (fail_on_warnings and entry.severity == "warning")
            if not high_signal:
                continue
            if any(pattern.search(entry.text) for pattern in allowed):
                continue
            offending.append(entry)
        if offending:
            lines = [
                f"{entry.severity.upper()} {entry.kind}: {entry.text}"
                for entry in offending[:10]
            ]
            raise BrowserEvidenceError("High-signal browser evidence found:\n" + "\n".join(lines))

    @staticmethod
    def write_browser_evidence_artifact(
        report: BrowserEvidenceReport,
        artifacts_dir: str | Path = "mcp/artifacts/browser-evidence",
        max_files: int = 50,
    ) -> Path:
        directory = Path(artifacts_dir)
        directory.mkdir(parents=True, exist_ok=True)
        safe_run = re.sub(r"[^a-zA-Z0-9_.-]+", "-", report.run_id or "browser-evidence").strip("-")
        safe_time = re.sub(r"[^0-9T]+", "-", report.collected_at.split("+", 1)[0]).strip("-")
        path = directory / f"{safe_time}-{safe_run}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if max_files > 0:
            files = sorted(directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
            for stale in files[max_files:]:
                stale.unlink(missing_ok=True)
        return path

    @staticmethod
    def parse_tabs(text: str) -> list[TabInfo]:
        tabs: list[TabInfo] = []
        for line in text.splitlines():
            match = re.match(r"^- (\d+):( \(current\))? \[(.*)\]\((.*)\)( \[crashed\])?$", line)
            if not match:
                continue
            tabs.append(
                TabInfo(
                    index=int(match.group(1)),
                    current=bool(match.group(2)),
                    title=match.group(3),
                    url=match.group(4),
                    crashed=bool(match.group(5)),
                )
            )
        return tabs

    def list_tabs(self) -> list[TabInfo]:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                return self.parse_tabs(self.tool_text(self.call_tool("browser_tabs", {"action": "list"})))
            except (McpProtocolError, McpToolError, json.JSONDecodeError) as e:
                last_error = e
                if "no response" in str(e) or "Session not found" in str(e):
                    self.sid = None
                    try:
                        self.initialize()
                    except McpError:
                        if attempt == 2:
                            raise
                time.sleep(0.2)
        raise McpToolError(f"browser_tabs list failed after retries: {last_error}")

    @staticmethod
    def _tab_matches(tab: TabInfo, expected_url: Optional[str], expected_title: Optional[str]) -> bool:
        if expected_url is not None and tab.url != expected_url:
            return False
        if expected_title is not None and tab.title != expected_title:
            return False
        return True

    def find_tab(self, expected_url: Optional[str] = None, expected_title: Optional[str] = None) -> TabInfo:
        matches = [
            tab for tab in self.list_tabs()
            if self._tab_matches(tab, expected_url, expected_title)
        ]
        if not matches:
            raise McpToolError(f"tab not found for url={expected_url!r} title={expected_title!r}")
        if len(matches) > 1 and expected_url is None:
            raise McpToolError(f"ambiguous tab title {expected_title!r}; provide an expected URL")
        return matches[-1]

    def current_tab(self) -> TabInfo:
        current = [tab for tab in self.list_tabs() if tab.current]
        if not current:
            raise McpToolError("could not determine current tab")
        return current[0]

    def _verify_current_tab(
        self,
        expected_url: Optional[str] = None,
        expected_title: Optional[str] = None,
        reason: str = "selected wrong tab",
    ) -> TabInfo:
        current = self.current_tab()
        if not self._tab_matches(current, expected_url, expected_title):
            raise McpToolError(
                f"{reason}: current index={current.index} title={current.title!r} "
                f"url={current.url!r}; expected title={expected_title!r} url={expected_url!r}"
            )
        return current

    def select_tab_verified(
        self,
        index: int,
        expected_url: Optional[str] = None,
        expected_title: Optional[str] = None,
    ) -> TabInfo:
        self.call_tool("browser_tabs", {"action": "select", "index": index})
        return self._verify_current_tab(expected_url, expected_title)

    def open_new_tab(self, url: str, expected_title: Optional[str] = None) -> int:
        result = self.call_tool("browser_tabs", {"action": "new", "url": url})
        tabs = self.parse_tabs(self.tool_text(result))
        current = [tab for tab in tabs if tab.current]
        if not current:
            raise McpToolError(f"could not determine current tab after opening: {self.tool_text(result)[:400]}")
        opened = current[0]
        if not self._tab_matches(opened, url, expected_title):
            raise McpToolError(
                f"new tab verification failed: current index={opened.index} title={opened.title!r} "
                f"url={opened.url!r}; expected title={expected_title!r} url={url!r}"
            )
        selected = self.select_tab_verified(opened.index, expected_url=url, expected_title=expected_title)
        return selected.index

    def close_tab(self, index: int) -> None:
        try:
            self.call_tool("browser_tabs", {"action": "close", "index": index})
        except McpToolError as e:
            message = str(e)
            if "no response" not in message and "Tab " not in message and "not found" not in message:
                raise

    def close_tab_verified(
        self,
        expected_url: Optional[str] = None,
        expected_title: Optional[str] = None,
    ) -> None:
        selected: Optional[TabInfo] = None
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                tab = self.find_tab(expected_url, expected_title)
                selected = self.select_tab_verified(tab.index, expected_url, expected_title)
                break
            except McpToolError as e:
                last_error = e
                message = str(e)
                stale_index = "Tab " in message and "not found" in message
                if ("selected wrong tab" not in message and not stale_index) or attempt == 2:
                    raise
                time.sleep(0.2 * (attempt + 1))
        if selected is None:
            raise McpToolError(f"could not select tab before close: {last_error}")
        self.close_tab(selected.index)
        remaining: list[TabInfo] = []
        for attempt in range(5):
            remaining = [
                candidate for candidate in self.list_tabs()
                if self._tab_matches(candidate, expected_url, expected_title)
            ]
            if not remaining:
                return
            time.sleep(0.2 * (attempt + 1))
        if remaining:
            raise McpToolError(f"tab still present after close: {remaining[-1]}")

    def scoped_tab(self, url: str, expected_title: Optional[str] = None):
        client = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner.idx = client.open_new_tab(url, expected_title=expected_title)
                return self_inner.idx

            def __exit__(self_inner, *exc):
                try:
                    client.close_tab_verified(expected_url=url, expected_title=expected_title)
                except Exception:
                    pass

        return _Ctx()


class ProjectTabSession:
    """Client-side tab ownership boundary for shared-Chrome QA runs."""

    def __init__(
        self,
        client: McpClient,
        name: str,
        preserve_on_failure: bool = False,
    ):
        self.client = client
        self.name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-") or "project-session"
        self.run_id = f"{self.name}-{uuid.uuid4().hex[:8]}"
        self.preserve_on_failure = preserve_on_failure
        self.owned_tabs: list[OwnedTab] = []
        self.active_tab: Optional[OwnedTab] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None and self.preserve_on_failure:
            return False
        self.cleanup()
        return False

    def tab_title(self, label: str) -> str:
        safe_label = re.sub(r"[\r\n]+", " ", label).strip() or "tab"
        return f"{self.run_id}:{safe_label}"

    def open_data_tab(self, label: str, body_html: str = "") -> OwnedTab:
        title = self.tab_title(label)
        url = self.client.data_url(f"<title>{escape(title)}</title>{body_html}")
        return self.open_tab(url, expected_title=title, label=label)

    def open_tab(
        self,
        url: str,
        expected_title: Optional[str] = None,
        label: str = "tab",
    ) -> OwnedTab:
        index = self.client.open_new_tab(url, expected_title=expected_title)
        tab = OwnedTab(index=index, url=url, title=expected_title or "", label=label)
        self.owned_tabs.append(tab)
        self.active_tab = tab
        return tab

    def select_tab(self, tab: Optional[OwnedTab] = None) -> TabInfo:
        target = tab or self.active_tab
        if target is None:
            raise McpToolError("project tab session has no active owned tab")
        current = self.client.find_tab(
            expected_url=target.url,
            expected_title=target.title or None,
        )
        target.index = current.index
        return self.client.select_tab_verified(
            current.index,
            expected_url=target.url,
            expected_title=target.title or None,
        )

    def call_tool(
        self,
        name: str,
        arguments: Optional[dict] = None,
        tab: Optional[OwnedTab] = None,
        allow_error: bool = False,
    ) -> dict:
        if name != "browser_tabs":
            self.select_tab(tab)
        return self.client.call_tool(name, arguments, allow_error=allow_error)

    def cleanup(self) -> None:
        failures: list[str] = []
        for tab in reversed(self.owned_tabs):
            try:
                self.client.close_tab_verified(
                    expected_url=tab.url,
                    expected_title=tab.title or None,
                )
            except McpToolError as e:
                if "tab not found" not in str(e):
                    failures.append(str(e))
        if failures:
            raise McpToolError("project tab session cleanup failed: " + "; ".join(failures))
