#!/usr/bin/env python3
"""Repo-agnostic state guard for Rizonetech overnight todo runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHROMEMCP_HEALTH_URL = "http://127.0.0.1:8931/healthz"
STATE_RELATIVE_PATH = Path(".codex/state/overnight-runner.json")
GATE_STATUSES = {"pending", "passed", "failed", "blocked", "not-applicable"}
BLOCKER_KINDS = {"app", "automation", "environment", "data", "decision", "unknown"}
CHROMEMCP_METHODS_THAT_COUNT = {"real-mcp", "mcp-plus-cdp-screenshot"}
REQUIRED_VISUAL_CHECKS = {
    "horizontal-overflow",
    "console-errors",
    "blank-screenshots",
    "missing-assets",
    "mobile-menu",
    "clipped-text",
    "unreadable-text",
    "spacing-alignment",
    "modal-scope",
}
BASE_GATES = (
    "implemented_review",
    "implemented",
    "automated_tests",
    "feature_gate",
    "chromemcp_local",
    "visual_qa",
    "workflow_matrix",
    "browser_handoff",
    "production_deploy",
    "commit_push",
    "destructive_approval",
    "rollback_plan",
    "todo_history_updated",
)
CLASSIFICATION_PATTERNS = {
    "ui_browser_work": (
        r"\badmin\b",
        r"\bui\b",
        r"\bbrowser\b",
        r"\bchrome(?:mcp)?\b",
        r"\bscreenshot\b",
        r"\bvisual\b",
        r"\bcss\b",
        r"\bjavascript\b",
        r"\bnavigation\b",
        r"\bcrud\b",
        r"\bgrud\b",
        r"\bfilament\b",
        r"\blivewire\b",
    ),
    "destructive_cutover": (
        r"\bcutover\b",
        r"\bactive plugin\b",
        r"\bplugin replacement\b",
        r"\breplace\b.*\bplugin\b",
        r"\brm\s+-rf\b",
        r"\bdrop\s+table\b",
        r"\btruncate\b",
        r"\bdelete\b.*\bdata\b",
    ),
    "deploy": (
        r"\bdeploy\b",
        r"\bproduction\b",
        r"\brelease\b",
        r"\bpublish\b",
        r"\blaravel cloud\b",
    ),
    "legal_provenance": (
        r"\bcopyright\b",
        r"\blicen[cs]e\b",
        r"\blegal\b",
        r"\bprovenance\b",
        r"\bclean-room\b",
    ),
    "credential_sensitive": (
        r"\bcredential\b",
        r"\bsecret\b",
        r"\btoken\b",
        r"\bapi[_ -]?key\b",
        r"\bpassword\b",
        r"\.secrets\b",
    ),
    "cleanup_reset": (
        r"\bcleanup\b",
        r"\bclean up\b",
        r"\breset\b",
        r"\bremove\b",
        r"\bdelete\b",
        r"\bimport\b",
        r"\bexport\b",
        r"\brestore\b",
        r"\buninstall\b",
    ),
    "docs_research": (
        r"\bresearch\b",
        r"\bdocs\b",
        r"\bdocumentation\b",
        r"\bbenchmark\b",
        r"\broadmap\b",
    ),
}
DANGEROUS_OPERATION_PATTERNS = {
    "active_plugin_replacement": (
        r"\bactive plugin\b",
        r"\bcutover\b.*\bplugin\b",
        r"\breplace\b.*\bplugin\b",
        r"\bpublic/wp-content/plugins\b",
    ),
    "rm_rf": (r"\brm\s+-rf\b",),
    "production_deploy": (r"\bdeploy\b.*\bproduction\b", r"\bproduction\b.*\bdeploy\b"),
    "release_publishing": (r"\bpublish\b.*\brelease\b", r"\brelease package\b"),
    "copyright_removal": (r"\bcopyright\b.*\bremov", r"\bremov\w*\b.*\bcopyright\b"),
    "destructive_data": (r"\bdrop\s+table\b", r"\btruncate\b", r"\bdelete\b.*\bdata\b"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], *, cwd: Path, timeout: int = 30) -> dict[str, Any]:
    started = now()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "XDEBUG_MODE": "off"},
        )
    except Exception as exc:
        return {
            "command": command,
            "cwd": str(cwd),
            "started_at": started,
            "status": "failed",
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "command": command,
        "cwd": str(cwd),
        "started_at": started,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip()[-4000:],
        "stderr": completed.stderr.strip()[-4000:],
    }


def repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return Path.cwd().resolve()


def state_path(root: Path) -> Path:
    return root / STATE_RELATIVE_PATH


def read_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_unique(target: list[str], values: list[str] | None) -> None:
    for value in values or []:
        if value and value not in target:
            target.append(value)


def resolve_todo(root: Path, todo_file: str | None) -> Path | None:
    if not todo_file:
        return None
    candidate = Path(todo_file)
    return candidate if candidate.is_absolute() else root / candidate


def relative_to_root(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def pattern_matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) for pattern in patterns)


def classify_text(text: str) -> dict[str, Any]:
    classifications = [
        name
        for name, patterns in CLASSIFICATION_PATTERNS.items()
        if pattern_matches(text, patterns)
    ]
    if re.search(r"^\s*[-*]\s+\[[xX]\]\s+", text, flags=re.MULTILINE):
        classifications.append("checked_items_present")
    if re.search(r"^\s*[-*]\s+\[\s\]\s+", text, flags=re.MULTILINE):
        classifications.append("unchecked_items_present")
    if not classifications:
        classifications.append("normal_implementation")

    dangerous = [
        name
        for name, patterns in DANGEROUS_OPERATION_PATTERNS.items()
        if pattern_matches(text, patterns)
    ]
    return {
        "classifications": sorted(set(classifications)),
        "dangerous_operations": sorted(set(dangerous)),
        "checkpoint_required": bool(dangerous or "destructive_cutover" in classifications),
    }


def git_snapshot(root: Path) -> dict[str, Any]:
    status = run_command(["git", "status", "--porcelain=v1"], cwd=root, timeout=30)
    branch = run_command(["git", "branch", "--show-current"], cwd=root, timeout=30)
    entries = []
    if status["status"] == "passed":
        for line in status["stdout"].splitlines():
            if not line:
                continue
            entries.append(
                {
                    "status": line[:2].strip() or line[:2],
                    "path": line[3:] if len(line) > 3 else "",
                    "ownership": "pre_existing",
                }
            )
    return {
        "captured_at": now(),
        "branch": (branch.get("stdout") or "").strip(),
        "entries": entries,
        "dirty_count": len(entries),
    }


def find_chromemcp_roots(root: Path) -> list[str]:
    candidates = [
        Path.home() / ".codex/plugins/rizonetech-local/plugins/chromemcp-browser",
        root / "plugins/chromemcp-browser",
        root.parent / "codex-plugins/plugins/chromemcp-browser",
        Path("/home/<user>/github/codex-plugins/plugins/chromemcp-browser"),
        Path("/home/<user>/github/ChromeMCP"),
    ]
    found = []
    for candidate in candidates:
        if candidate.exists() and str(candidate) not in found:
            found.append(str(candidate))
    return found


def chromemcp_health(root: Path) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(CHROMEMCP_HEALTH_URL, timeout=5) as response:
            body = response.read().decode("utf-8", errors="replace")
            try:
                payload: Any = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body[:1000]}
            ok = response.status == 200
            visible = payload.get("visibleInteractions") if isinstance(payload, dict) else None
            return {
                "status": "passed" if ok else "failed",
                "url": CHROMEMCP_HEALTH_URL,
                "http_status": response.status,
                "visible_interactions": visible,
                "roots": find_chromemcp_roots(root),
                "recovery": recovery_hint(root),
            }
    except (urllib.error.URLError, TimeoutError, OSError, socket.timeout) as exc:
        return {
            "status": "blocked",
            "url": CHROMEMCP_HEALTH_URL,
            "error": str(exc),
            "roots": find_chromemcp_roots(root),
            "recovery": recovery_hint(root),
        }


def recovery_hint(root: Path) -> str:
    roots = find_chromemcp_roots(root)
    if roots:
        return f"cd {roots[0]} && ./mcp-up && ./mcp-status"
    return "Install or enable the ChromeMCP Browser plugin, then run ./mcp-up and ./mcp-status."


def required_gates(preflight: dict[str, Any]) -> set[str]:
    classifications = set(preflight.get("classifications") or [])
    dangerous = set(preflight.get("dangerous_operations") or [])
    required = {"implemented_review", "implemented", "automated_tests", "feature_gate", "todo_history_updated"}
    if "ui_browser_work" in classifications:
        required.update({"chromemcp_local", "visual_qa", "workflow_matrix", "browser_handoff"})
    if "deploy" in classifications:
        required.update({"production_deploy", "rollback_plan"})
    if preflight.get("checkpoint_required"):
        required.add("destructive_approval")
    if dangerous:
        required.add("rollback_plan")
    return required


def blank_gates(preflight: dict[str, Any] | None = None) -> dict[str, Any]:
    required = required_gates(preflight or {})
    return {
        gate: {
            "required": gate in required,
            "status": "pending" if gate in required else "not-applicable",
            "evidence": [],
            "updated_at": now(),
        }
        for gate in BASE_GATES
    }


def build_preflight(root: Path, todo_file: str | None) -> dict[str, Any]:
    todo_path = resolve_todo(root, todo_file)
    if todo_file and (todo_path is None or not todo_path.exists()):
        raise SystemExit(f"Todo file not found: {todo_file}")
    text = todo_path.read_text(encoding="utf-8") if todo_path and todo_path.exists() else ""
    classification = classify_text(text)
    chrome = chromemcp_health(root)
    return {
        **classification,
        "status": "passed" if chrome["status"] == "passed" else "blocked",
        "captured_at": now(),
        "todo_file": todo_file,
        "todo_file_exists": bool(todo_path and todo_path.exists()),
        "git": git_snapshot(root),
        "chromemcp": chrome,
        "notes": [
            "ChromeMCP is preferred for user-facing verification.",
            "If ChromeMCP is blocked, browser/UI completion gates must remain blocked until real evidence is captured.",
        ],
    }


def command_start(args: argparse.Namespace) -> None:
    root = repo_root()
    preflight = build_preflight(root, args.todo_file)
    state = {
        "active": True,
        "started_at": now(),
        "updated_at": now(),
        "todo_file": args.todo_file,
        "current_slice": None,
        "status": "started" if preflight["status"] == "passed" else "preflight_blocked",
        "preflight": preflight,
        "gates": blank_gates(preflight),
        "slices": {},
        "notes": [],
        "completed_slices": [],
        "blockers": [],
        "artifacts": [],
        "chromemcp_failures": {},
        "chromemcp": {
            "required_for_user_facing": True,
            "status": "passed" if preflight["chromemcp"]["status"] == "passed" else "blocked",
            "method": "real-mcp",
            "evidence": [preflight["chromemcp"]],
            "blockers": [] if preflight["chromemcp"]["status"] == "passed" else [
                {
                    "at": now(),
                    "kind": "environment",
                    "blocker": preflight["chromemcp"].get("error") or "ChromeMCP health check did not pass.",
                    "recovery": preflight["chromemcp"].get("recovery"),
                }
            ],
            "report_paths": [],
            "screenshot_paths": [],
            "routes": [],
            "viewports": [],
            "final_visible_handoff": False,
        },
        "visual_qa": {"status": "pending", "checks": [], "evidence": [], "screenshot_paths": [], "blockers": []},
        "workflow_matrix": {"status": "pending", "matrix_paths": [], "routes": [], "viewports": [], "states": []},
        "deploy": {"status": "pending" if "deploy" in preflight["classifications"] else "not-applicable", "evidence": [], "blockers": []},
        "commit_push": {"status": "pending", "commit_sha": None, "branch": None, "evidence": [], "blockers": []},
        "rollback_manifest": {},
        "next_action": "Read todo, reconcile the codebase, and start the first unblocked slice.",
    }
    write_state(root, state)
    print(f"Started Overnight Runner: {args.todo_file}")
    print("Preflight classifications: " + ", ".join(preflight["classifications"]))
    print(f"ChromeMCP: {preflight['chromemcp']['status']}")
    if preflight["chromemcp"]["status"] != "passed":
        print("ChromeMCP blocker recorded; non-browser work may continue when safe.")
        print("Recovery: " + preflight["chromemcp"].get("recovery", "not available"))


def command_preflight(args: argparse.Namespace) -> None:
    root = repo_root()
    preflight = build_preflight(root, args.todo_file)
    print(json.dumps(preflight, indent=2, sort_keys=True))


def ensure_state(root: Path) -> dict[str, Any]:
    state = read_state(root)
    if state:
        return state
    return {
        "active": True,
        "started_at": now(),
        "updated_at": now(),
        "todo_file": None,
        "status": "started",
        "gates": blank_gates({}),
        "slices": {},
        "notes": [],
        "completed_slices": [],
        "blockers": [],
        "artifacts": [],
        "chromemcp_failures": {},
    }


def update_gate(state: dict[str, Any], gate_spec: str, note: str | None = None, command: str | None = None, url: str | None = None) -> None:
    if "=" in gate_spec:
        name, status = gate_spec.split("=", 1)
    else:
        name, status = gate_spec, "passed"
    name = name.strip()
    status = status.strip()
    if name not in BASE_GATES:
        raise SystemExit(f"Unknown gate: {name}. Expected one of: {', '.join(BASE_GATES)}")
    if status not in GATE_STATUSES:
        raise SystemExit(f"Invalid gate status for {name}: {status}")
    gate = state.setdefault("gates", {}).setdefault(
        name,
        {"required": True, "status": "pending", "evidence": [], "updated_at": None},
    )
    gate["status"] = status
    gate["updated_at"] = now()
    evidence = {key: value for key, value in {"at": now(), "note": note, "command": command, "url": url}.items() if value}
    if evidence:
        gate.setdefault("evidence", []).append(evidence)


def current_slice(state: dict[str, Any], name: str | None) -> dict[str, Any] | None:
    slice_name = name or state.get("current_slice")
    if not slice_name:
        return None
    state["current_slice"] = slice_name
    slices = state.setdefault("slices", {})
    return slices.setdefault(slice_name, {"gates": {}, "blockers": [], "evidence": [], "updated_at": now()})


def record_chromemcp_failure(state: dict[str, Any], args: argparse.Namespace) -> None:
    if not args.chromemcp_step:
        return
    failures = state.setdefault("chromemcp_failures", {})
    step = failures.setdefault(args.chromemcp_step, {"count": 0, "kind": args.blocker_kind or "unknown", "events": []})
    step["count"] += 1
    step["kind"] = args.blocker_kind or step.get("kind") or "unknown"
    event = {
        "at": now(),
        "kind": step["kind"],
        "note": args.chromemcp_failure_note,
        "url": args.chromemcp_url,
        "diagnostics": {
            "snapshot": args.diagnostic_snapshot,
            "dom": args.diagnostic_dom,
            "console": args.diagnostic_console,
            "network": args.diagnostic_network,
            "db_probe": args.diagnostic_db,
        },
    }
    step.setdefault("events", []).append(event)
    if step["count"] >= 2:
        blocker = (
            f"ChromeMCP step '{args.chromemcp_step}' failed {step['count']} times; "
            f"classified as {step['kind']} blocker. Diagnose with DOM/snapshot/console/network/DB evidence."
        )
        state.setdefault("blockers", []).append({"at": now(), "kind": step["kind"], "blocker": blocker, "diagnostics": event["diagnostics"]})
        chromemcp = state.setdefault("chromemcp", {"status": "pending", "evidence": [], "blockers": []})
        chromemcp["status"] = "blocked"
        chromemcp.setdefault("blockers", []).append({"at": now(), "kind": step["kind"], "blocker": blocker})


def command_update(args: argparse.Namespace) -> None:
    root = repo_root()
    state = ensure_state(root)
    state["active"] = True
    state["updated_at"] = now()
    if args.todo_file:
        state["todo_file"] = args.todo_file
    if args.slice:
        state["current_slice"] = args.slice
    if args.status:
        state["status"] = args.status
    if args.note:
        state.setdefault("notes", []).append({"at": now(), "note": args.note})
    if args.completed:
        state.setdefault("completed_slices", []).append({"at": now(), "slice": args.completed})
    if args.blocker:
        state.setdefault("blockers", []).append({"at": now(), "kind": args.blocker_kind or "unknown", "blocker": args.blocker})
    if args.next_action:
        state["next_action"] = args.next_action
    for gate_spec in args.gate or []:
        update_gate(state, gate_spec, args.gate_note, args.gate_command, args.gate_url)
        slice_state = current_slice(state, args.slice)
        if slice_state is not None:
            gate_name = gate_spec.split("=", 1)[0].strip()
            slice_state.setdefault("gates", {})[gate_name] = state["gates"][gate_name].copy()
            slice_state["updated_at"] = now()

    record_chromemcp_failure(state, args)
    if any((args.chromemcp_status, args.chromemcp_method, args.chromemcp_note, args.chromemcp_blocker, args.chromemcp_url, args.chromemcp_report, args.chromemcp_screenshot, args.chromemcp_route, args.chromemcp_viewport, args.chromemcp_final_visible_handoff)):
        chromemcp = state.setdefault("chromemcp", {"status": "pending", "method": "real-mcp", "evidence": [], "blockers": [], "report_paths": [], "screenshot_paths": [], "routes": [], "viewports": [], "final_visible_handoff": False})
        if args.chromemcp_status:
            chromemcp["status"] = args.chromemcp_status
        if args.chromemcp_method:
            chromemcp["method"] = args.chromemcp_method
        append_unique(chromemcp.setdefault("report_paths", []), args.chromemcp_report)
        append_unique(chromemcp.setdefault("screenshot_paths", []), args.chromemcp_screenshot)
        append_unique(chromemcp.setdefault("routes", []), args.chromemcp_route)
        append_unique(chromemcp.setdefault("viewports", []), args.chromemcp_viewport)
        if args.chromemcp_final_visible_handoff:
            chromemcp["final_visible_handoff"] = True
        if args.chromemcp_note or args.chromemcp_url:
            chromemcp.setdefault("evidence", []).append({"at": now(), "url": args.chromemcp_url, "note": args.chromemcp_note})
        if args.chromemcp_blocker:
            chromemcp["status"] = "blocked"
            chromemcp.setdefault("blockers", []).append({"at": now(), "kind": args.blocker_kind or "unknown", "blocker": args.chromemcp_blocker})

    if any((args.visual_status, args.visual_note, args.visual_blocker, args.visual_report, args.visual_screenshot, args.visual_check)):
        visual = state.setdefault("visual_qa", {"status": "pending", "evidence": [], "blockers": [], "report_paths": [], "screenshot_paths": [], "checks": []})
        if args.visual_status:
            visual["status"] = args.visual_status
        if args.visual_note:
            visual.setdefault("evidence", []).append({"at": now(), "note": args.visual_note})
        if args.visual_blocker:
            visual["status"] = "blocked"
            visual.setdefault("blockers", []).append({"at": now(), "blocker": args.visual_blocker})
        append_unique(visual.setdefault("report_paths", []), args.visual_report)
        append_unique(visual.setdefault("screenshot_paths", []), args.visual_screenshot)
        append_unique(visual.setdefault("checks", []), args.visual_check)

    if any((args.workflow_status, args.workflow_matrix, args.workflow_route, args.workflow_viewport, args.workflow_state)):
        workflow = state.setdefault("workflow_matrix", {"status": "pending", "matrix_paths": [], "routes": [], "viewports": [], "states": []})
        if args.workflow_status:
            workflow["status"] = args.workflow_status
        append_unique(workflow.setdefault("matrix_paths", []), args.workflow_matrix)
        append_unique(workflow.setdefault("routes", []), args.workflow_route)
        append_unique(workflow.setdefault("viewports", []), args.workflow_viewport)
        append_unique(workflow.setdefault("states", []), args.workflow_state)

    if any((args.commit_status, args.commit_sha, args.pushed_branch, args.commit_note, args.commit_blocker)):
        commit = state.setdefault("commit_push", {"status": "pending", "commit_sha": None, "branch": None, "evidence": [], "blockers": []})
        if args.commit_status:
            commit["status"] = args.commit_status
        if args.commit_sha:
            commit["commit_sha"] = args.commit_sha
        if args.pushed_branch:
            commit["branch"] = args.pushed_branch
        if args.commit_note:
            commit.setdefault("evidence", []).append({"at": now(), "note": args.commit_note})
        if args.commit_blocker:
            commit["status"] = "blocked"
            commit.setdefault("blockers", []).append({"at": now(), "blocker": args.commit_blocker})

    if any((args.deploy_status, args.deploy_note, args.deploy_blocker)):
        deploy = state.setdefault("deploy", {"status": "pending", "evidence": [], "blockers": []})
        if args.deploy_status:
            deploy["status"] = args.deploy_status
        if args.deploy_note:
            deploy.setdefault("evidence", []).append({"at": now(), "note": args.deploy_note})
        if args.deploy_blocker:
            deploy["status"] = "blocked"
            deploy.setdefault("blockers", []).append({"at": now(), "blocker": args.deploy_blocker})

    if any((args.rollback_current, args.rollback_backup, args.rollback_restore_command, args.rollback_check)):
        rollback = state.setdefault("rollback_manifest", {})
        for key, value in {
            "current": args.rollback_current,
            "backup": args.rollback_backup,
            "restore_command": args.rollback_restore_command,
            "check": args.rollback_check,
        }.items():
            if value:
                rollback[key] = value
        rollback["updated_at"] = now()

    write_state(root, state)
    print(f"Updated Overnight Runner: {state.get('status', 'active')}")


def command_status(_: argparse.Namespace) -> None:
    root = repo_root()
    state = read_state(root)
    if not state:
        print("No Overnight Runner state found.")
        return
    print(json.dumps(state, indent=2, sort_keys=True))


def todo_unchecked_and_blocked(root: Path, todo_file: str | None, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    todo_path = resolve_todo(root, todo_file)
    if not todo_path or not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    unchecked = [
        {"line": index, "text": line.strip()}
        for index, line in enumerate(lines, 1)
        if re.search(r"^\s*[-*]\s+\[\s\]\s+", line)
    ]
    checked = [
        {"line": index, "text": line.strip()}
        for index, line in enumerate(lines, 1)
        if re.search(r"^\s*[-*]\s+\[[xX]\]\s+", line)
    ]
    blockers = [
        {"line": index, "text": line.strip()}
        for index, line in enumerate(lines, 1)
        if re.search(r"\b(Blocked|Deferred):", line)
    ]
    return checked[:limit], unchecked[:limit], blockers[:limit]


def existing_artifact_errors(root: Path, label: str, paths: list[str] | None, *, min_bytes: int = 1) -> list[str]:
    if not paths:
        return [f"{label} must include at least one artifact path."]
    errors = []
    for raw in paths:
        path = Path(raw)
        candidate = path if path.is_absolute() else root / path
        if not candidate.exists():
            errors.append(f"{label} artifact does not exist: {raw}")
        elif candidate.is_file() and candidate.stat().st_size < min_bytes:
            errors.append(f"{label} artifact is too small to be useful: {raw}")
    return errors


def finish_errors(root: Path, state: dict[str, Any], *, allow_blocked: bool) -> list[str]:
    errors = []
    for name, gate in (state.get("gates") or {}).items():
        if not gate.get("required"):
            continue
        status = gate.get("status", "pending")
        if status in {"passed", "not-applicable"}:
            continue
        if allow_blocked and status == "blocked":
            continue
        errors.append(f"required gate {name} is {status}")

    chromemcp = state.get("chromemcp") or {}
    chromemcp_status = chromemcp.get("status")
    ui_required = (state.get("gates") or {}).get("chromemcp_local", {}).get("required")
    if ui_required:
        if chromemcp_status in {None, "", "pending"}:
            errors.append("ChromeMCP gate is pending")
        elif chromemcp_status == "blocked" and not allow_blocked:
            errors.append("ChromeMCP gate is blocked")
        elif chromemcp_status == "passed":
            if chromemcp.get("method") not in CHROMEMCP_METHODS_THAT_COUNT:
                errors.append(f"ChromeMCP method must be one of {sorted(CHROMEMCP_METHODS_THAT_COUNT)}")
            errors.extend(existing_artifact_errors(root, "ChromeMCP report", chromemcp.get("report_paths")))
            errors.extend(existing_artifact_errors(root, "ChromeMCP screenshots", chromemcp.get("screenshot_paths"), min_bytes=1000))
            if not chromemcp.get("routes"):
                errors.append("ChromeMCP evidence must include routes")
            if not chromemcp.get("viewports"):
                errors.append("ChromeMCP evidence must include viewports")
            if not chromemcp.get("final_visible_handoff"):
                errors.append("ChromeMCP evidence must record final visible handoff")

    visual = state.get("visual_qa") or {}
    if (state.get("gates") or {}).get("visual_qa", {}).get("required") and visual.get("status") == "passed":
        missing = sorted(REQUIRED_VISUAL_CHECKS - set(visual.get("checks") or []))
        if missing:
            errors.append("Visual QA missing checks: " + ", ".join(missing))
        errors.extend(existing_artifact_errors(root, "Visual QA screenshots", visual.get("screenshot_paths"), min_bytes=1000))

    commit = state.get("commit_push") or {}
    if commit.get("status") == "passed":
        if not re.fullmatch(r"[0-9a-f]{40}", commit.get("commit_sha") or ""):
            errors.append("commit_push passed but does not record a 40-character commit SHA")
        if not commit.get("branch"):
            errors.append("commit_push passed but does not record a pushed branch")

    rollback_required = (state.get("gates") or {}).get("rollback_plan", {}).get("required")
    if rollback_required and (state.get("gates") or {}).get("rollback_plan", {}).get("status") == "passed":
        rollback = state.get("rollback_manifest") or {}
        for key in ("current", "backup", "restore_command", "check"):
            if not rollback.get(key):
                errors.append(f"rollback_manifest missing {key}")
    return errors


def command_finish_check(args: argparse.Namespace) -> None:
    root = repo_root()
    state = read_state(root)
    if not state:
        raise SystemExit("No Overnight Runner state found.")
    todo_file = args.todo_file or state.get("todo_file")
    checked, unchecked, blockers = todo_unchecked_and_blocked(root, todo_file, args.limit)
    print(f"Finish check for {todo_file}")
    print(f"Checked items shown: {len(checked)}")
    print(f"Unchecked items shown: {len(unchecked)}")
    for item in unchecked:
        print(f"- line {item['line']}: {item['text']}")
    print(f"Blocked/Deferred notes shown: {len(blockers)}")
    for item in blockers:
        print(f"- line {item['line']}: {item['text']}")
    errors = finish_errors(root, state, allow_blocked=args.allow_blocked)
    if unchecked and not blockers:
        errors.append("unchecked items remain without Blocked:/Deferred: notes")
    if unchecked and not args.allow_blocked:
        errors.append("unchecked items remain; use --allow-blocked only for documented true blockers")
    if errors:
        raise SystemExit("Finish check failed: " + " ".join(errors))
    print("Finish check passed.")


def build_handoff(state: dict[str, Any]) -> str:
    completed = [item.get("slice") for item in state.get("completed_slices", []) if item.get("slice")]
    blockers = state.get("blockers", [])
    gates = state.get("gates") or {}
    passed = [name for name, gate in gates.items() if gate.get("status") == "passed"]
    blocked = [f"{name}={gate.get('status')}" for name, gate in gates.items() if gate.get("status") == "blocked"]
    chromemcp = state.get("chromemcp") or {}
    commit = state.get("commit_push") or {}
    lines = [
        "## Run Handoff",
        "",
        "- Completed: " + ("; ".join(completed) if completed else "No completed slices recorded."),
        "- Verified Gates: " + ("; ".join(passed) if passed else "No passed gates recorded."),
        "- Blocked Gates: " + ("; ".join(blocked) if blocked else "None recorded."),
        "- Blockers: " + (
            "; ".join(f"{item.get('kind', 'unknown')}: {item.get('blocker')}" for item in blockers)
            if blockers
            else "None recorded."
        ),
        "- ChromeMCP: "
        + f"status={chromemcp.get('status', 'pending')}; method={chromemcp.get('method', 'real-mcp')}; "
        + "routes="
        + (", ".join(chromemcp.get("routes") or []) if chromemcp.get("routes") else "none"),
        "- Evidence: reports="
        + (", ".join(chromemcp.get("report_paths") or []) if chromemcp.get("report_paths") else "none")
        + "; screenshots="
        + (", ".join(chromemcp.get("screenshot_paths") or []) if chromemcp.get("screenshot_paths") else "none"),
        "- Commit: "
        + (
            f"{commit.get('commit_sha')} on {commit.get('branch')}"
            if commit.get("status") == "passed"
            else f"status={commit.get('status', 'not-recorded')}"
        ),
        "- Next Action: " + str(state.get("next_action") or "Not recorded."),
    ]
    return "\n".join(lines) + "\n"


def write_handoff(root: Path, todo_file: str, handoff: str) -> None:
    path = resolve_todo(root, todo_file)
    if not path or not path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r"^## Run Handoff\n.*?(?=^## |\Z)", flags=re.S | re.M)
    if pattern.search(content):
        content = pattern.sub(handoff.rstrip() + "\n\n", content)
    else:
        content = content.rstrip() + "\n\n" + handoff
    path.write_text(content, encoding="utf-8")


def command_handoff(args: argparse.Namespace) -> None:
    root = repo_root()
    state = read_state(root)
    if not state:
        raise SystemExit("No Overnight Runner state found.")
    handoff = build_handoff(state)
    if args.write_todo:
        todo_file = args.todo_file or state.get("todo_file")
        if not todo_file:
            raise SystemExit("No todo file supplied and no active run todo_file found.")
        write_handoff(root, todo_file, handoff)
        print(f"Wrote run handoff to {todo_file}")
    else:
        print(handoff)


def command_clear(args: argparse.Namespace) -> None:
    root = repo_root()
    state = read_state(root)
    if state:
        state["active"] = False
        state["cleared_at"] = now()
        state["clear_reason"] = args.reason
        state["updated_at"] = now()
        write_state(root, state)
    print(f"Cleared Overnight Runner: {args.reason}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage repo-agnostic overnight todo run state.")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="Start a guarded overnight run.")
    start.add_argument("todo_file")
    start.set_defaults(func=command_start)

    preflight = sub.add_parser("preflight", help="Classify a todo and probe ChromeMCP.")
    preflight.add_argument("todo_file", nargs="?")
    preflight.set_defaults(func=command_preflight)

    update = sub.add_parser("update", help="Update state, gates, evidence, and blockers.")
    update.add_argument("--todo-file")
    update.add_argument("--slice")
    update.add_argument("--status")
    update.add_argument("--note")
    update.add_argument("--completed")
    update.add_argument("--blocker")
    update.add_argument("--blocker-kind", choices=sorted(BLOCKER_KINDS))
    update.add_argument("--gate", action="append", help="Set gate as name=status, or omit status to mark passed.")
    update.add_argument("--gate-note")
    update.add_argument("--gate-command")
    update.add_argument("--gate-url")
    update.add_argument("--chromemcp-status", choices=sorted(GATE_STATUSES))
    update.add_argument("--chromemcp-method", choices=["real-mcp", "mcp-plus-cdp-screenshot", "fallback-cdp", "not-applicable"])
    update.add_argument("--chromemcp-url")
    update.add_argument("--chromemcp-note")
    update.add_argument("--chromemcp-blocker")
    update.add_argument("--chromemcp-report", action="append")
    update.add_argument("--chromemcp-screenshot", action="append")
    update.add_argument("--chromemcp-route", action="append")
    update.add_argument("--chromemcp-viewport", action="append")
    update.add_argument("--chromemcp-final-visible-handoff", action="store_true")
    update.add_argument("--chromemcp-step")
    update.add_argument("--chromemcp-failure-note")
    update.add_argument("--diagnostic-snapshot")
    update.add_argument("--diagnostic-dom")
    update.add_argument("--diagnostic-console")
    update.add_argument("--diagnostic-network")
    update.add_argument("--diagnostic-db")
    update.add_argument("--visual-status", choices=sorted(GATE_STATUSES))
    update.add_argument("--visual-note")
    update.add_argument("--visual-blocker")
    update.add_argument("--visual-report", action="append")
    update.add_argument("--visual-screenshot", action="append")
    update.add_argument("--visual-check", choices=sorted(REQUIRED_VISUAL_CHECKS), action="append")
    update.add_argument("--workflow-status", choices=sorted(GATE_STATUSES))
    update.add_argument("--workflow-matrix", action="append")
    update.add_argument("--workflow-route", action="append")
    update.add_argument("--workflow-viewport", action="append")
    update.add_argument("--workflow-state", action="append")
    update.add_argument("--commit-status", choices=sorted(GATE_STATUSES))
    update.add_argument("--commit-sha")
    update.add_argument("--pushed-branch")
    update.add_argument("--commit-note")
    update.add_argument("--commit-blocker")
    update.add_argument("--deploy-status", choices=sorted(GATE_STATUSES))
    update.add_argument("--deploy-note")
    update.add_argument("--deploy-blocker")
    update.add_argument("--rollback-current")
    update.add_argument("--rollback-backup")
    update.add_argument("--rollback-restore-command")
    update.add_argument("--rollback-check")
    update.add_argument("--next-action")
    update.set_defaults(func=command_update)

    status = sub.add_parser("status", help="Print current state.")
    status.set_defaults(func=command_status)

    finish = sub.add_parser("finish-check", help="Check whether the run can final-answer.")
    finish.add_argument("--todo-file")
    finish.add_argument("--allow-blocked", action="store_true")
    finish.add_argument("--limit", type=int, default=20)
    finish.set_defaults(func=command_finish_check)

    handoff = sub.add_parser("handoff", help="Generate or write a structured handoff.")
    handoff.add_argument("--todo-file")
    handoff.add_argument("--write-todo", action="store_true")
    handoff.set_defaults(func=command_handoff)

    clear = sub.add_parser("clear", help="Mark the run ended.")
    clear.add_argument("reason")
    clear.set_defaults(func=command_clear)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
