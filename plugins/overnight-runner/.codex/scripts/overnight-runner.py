#!/usr/bin/env python3
"""Repo-agnostic state guard for Rizonetech overnight todo runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHROMEMCP_HEALTH_URL = "http://127.0.0.1:8931/healthz"
BASE_DIR = os.environ.get("OVERNIGHT_RUNNER_BASE", ".codex")
STATE_RELATIVE_PATH = Path(BASE_DIR) / "state/overnight-runner.json"
GATE_STATUSES = {"pending", "passed", "failed", "blocked", "not-applicable"}
BLOCKER_KINDS = {"app", "automation", "environment", "data", "decision", "unknown"}
CHROMEMCP_METHODS_THAT_COUNT = {"real-mcp", "mcp-plus-cdp-screenshot"}
SIDE_CHANGE_POLICY = (
    "preserve user side changes, inspect every dirty file before staging, include "
    "safe small side changes in the next coherent commit/push, and never discard/"
    "reset/restore/checkout/clean without explicit user instruction"
)
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
    "browser_verification",
    "visual_qa",
    "workflow_matrix",
    "browser_handoff",
    "production_deploy",
    "commit_push",
    "destructive_approval",
    "rollback_plan",
    "todo_history_updated",
)
MODULE_DEFINITIONS = {
    "laravel": {
        "label": "Laravel",
        "markers": ("artisan", "composer.json", "app/Providers"),
        "deploy_queue_markers": ("bin/cloud",),
        "deploy_rules": (
            "Check Laravel Cloud or project deployment queue before commit/push/deploy when the project exposes a cloud CLI.",
            "Do not start another deploy while a deployment is pending or running.",
            "After deploy, verify the deployed URL and record the current deployment pointer.",
        ),
        "suggested_checks": ("php artisan test", "npm run build"),
    },
    "wordpress": {
        "label": "WordPress",
        "markers": ("wp-content", "public/wp-content", "wp-config.php"),
        "deploy_queue_markers": (),
        "deploy_rules": (
            "Treat plugin/theme cutovers, release packages, and publish operations as deploy work.",
            "Record the active plugin/theme path, version, backup, restore command, and WP-CLI verification command before cutover.",
            "Do not replace an active plugin/theme directory without explicit current-thread approval.",
        ),
        "suggested_checks": ("php -l", "wp plugin list"),
    },
    "node": {
        "label": "Node",
        "markers": ("package.json",),
        "deploy_queue_markers": (),
        "deploy_rules": (
            "Run the project build/test commands before release or production handoff.",
            "Record package manager, build command, and release target when deploy work is requested.",
        ),
        "suggested_checks": ("npm test", "npm run build"),
    },
}
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
TODO_ITEM_RE = re.compile(r"^(\s*)[-*]\s+\[([ xX])\]\s+(.*)$")
ADVERSARIAL_FIX_PREFIX = "Adversarial review:"
TODO_REVIEW_CONTEXT_RADIUS = 3


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


def reports_dir(root: Path) -> Path:
    return root / BASE_DIR / "reports"


def _migrate_state_gates(state: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy gate names in a loaded state dict (in place)."""
    gates = state.get("gates")
    if isinstance(gates, dict) and "chromemcp_local" in gates:
        gates["browser_verification"] = gates.pop("chromemcp_local")
    return state


def read_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    return _migrate_state_gates(state)


def write_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_unique(target: list[str], values: list[str] | None) -> None:
    for value in values or []:
        if value and value not in target:
            target.append(value)


def normalize_gate_name(name: str) -> str:
    """Migrate legacy gate names to canonical names.

    Accepts the old ``chromemcp_local`` name used in state files written before
    the ``browser_verification`` rename and returns the current canonical name.
    All other names are returned unchanged.
    """
    if name == "chromemcp_local":
        return "browser_verification"
    return name


def resolve_todo(root: Path, todo_file: str | None) -> Path | None:
    if not todo_file:
        return None
    candidate = Path(todo_file)
    return candidate if candidate.is_absolute() else root / candidate


def todo_claim_text(line: str) -> str:
    return re.sub(r"^\s*[-*]\s+\[[xX ]\]\s*", "", line).strip()


def claim_id(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def todo_line_indent(line: str) -> str:
    match = re.match(r"^(\s*)", line)
    return match.group(1) if match else ""


def parse_todo_items(root: Path, todo_file: str | None) -> dict[str, list[dict[str, Any]]]:
    todo_path = resolve_todo(root, todo_file)
    if not todo_path or not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    checked = []
    unchecked = []
    blockers = []
    for index, line in enumerate(todo_path.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"^\s*[-*]\s+\[[xX]\]\s+", line):
            text = todo_claim_text(line)
            checked.append({"line": index, "text": line.strip(), "claim": text, "claim_id": claim_id(text)})
        elif re.search(r"^\s*[-*]\s+\[\s\]\s+", line):
            text = todo_claim_text(line)
            unchecked.append({"line": index, "text": line.strip(), "claim": text, "claim_id": claim_id(text)})
        if re.search(r"\b(Blocked|Deferred):", line):
            blockers.append({"line": index, "text": line.strip()})
    return {"checked": checked, "unchecked": unchecked, "blockers": blockers}


def all_todo_items(root: Path, todo_file: str | None) -> list[dict[str, Any]]:
    todo_path = resolve_todo(root, todo_file)
    if not todo_path or not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    items = []
    for index, line in enumerate(todo_path.read_text(encoding="utf-8").splitlines(), 1):
        match = TODO_ITEM_RE.match(line)
        if not match:
            continue
        indent, marker, claim = match.groups()
        claim = claim.strip()
        items.append(
            {
                "line": index,
                "indent": indent,
                "marker": marker,
                "status": "checked" if marker.lower() == "x" else "unchecked",
                "text": line.strip(),
                "claim": claim,
                "claim_id": claim_id(claim),
            }
        )
    return items


def todo_context(lines: list[str], line_number: int, radius: int = TODO_REVIEW_CONTEXT_RADIUS) -> str:
    start = max(0, line_number - radius - 1)
    end = min(len(lines), line_number + radius)
    return "\n".join(lines[start:end])


def todo_review_finding_id(rule: str, line_number: int, claim: str, fix: str) -> str:
    raw = f"{rule}:{line_number}:{claim}:{fix}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def fix_already_present(lines: list[str], line_number: int, fix: str) -> bool:
    normalized_fix = re.sub(r"\s+", " ", fix.strip().lower())
    if not normalized_fix:
        return True
    local = todo_context(lines, line_number, radius=8).lower()
    whole = "\n".join(lines).lower()
    return normalized_fix in re.sub(r"\s+", " ", local) or normalized_fix in re.sub(r"\s+", " ", whole)


def add_todo_review_fixes(root: Path, todo_file: str, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    todo_path = resolve_todo(root, todo_file)
    if not todo_path or not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    added: list[dict[str, Any]] = []
    insertions_by_line: dict[int, list[str]] = {}
    for finding in findings:
        if finding.get("verification_status") != "verified":
            continue
        line_number = int(finding["line"])
        fix = str(finding["fix"]).strip()
        if not fix or fix_already_present(lines, line_number, fix):
            finding["verification_status"] = "already-addressed"
            continue
        parent_line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
        indent = todo_line_indent(parent_line) + "  "
        addition = f"{indent}- [ ] {ADVERSARIAL_FIX_PREFIX} {fix}"
        insertions_by_line.setdefault(line_number, []).append(addition)
        added.append({"finding_id": finding["id"], "line": line_number, "text": addition.strip()})
        finding["todo_fix"] = addition.strip()

    if not insertions_by_line:
        return []

    offset = 0
    for line_number in sorted(insertions_by_line):
        index = line_number + offset
        additions = insertions_by_line[line_number]
        lines[index:index] = additions
        offset += len(additions)
    todo_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return added


def build_adversarial_todo_review(root: Path, todo_file: str) -> dict[str, Any]:
    todo_path = resolve_todo(root, todo_file)
    if not todo_path or not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    items = all_todo_items(root, todo_file)
    findings: list[dict[str, Any]] = []

    def add_finding(
        *,
        rule: str,
        severity: str,
        item: dict[str, Any],
        evidence: str,
        impact: str,
        fix: str,
    ) -> None:
        verification_status = "already-addressed" if fix_already_present(lines, item["line"], fix) else "verified"
        findings.append(
            {
                "id": todo_review_finding_id(rule, item["line"], item["claim"], fix),
                "rule": rule,
                "severity": severity,
                "line": item["line"],
                "item_status": item["status"],
                "claim": item["claim"],
                "evidence": evidence,
                "impact": impact,
                "fix": fix,
                "verification_status": verification_status,
            }
        )

    seen_claims: dict[str, dict[str, Any]] = {}
    for item in items:
        claim = item["claim"]
        context = todo_context(lines, item["line"]).lower()
        normalized = re.sub(r"[^a-z0-9]+", " ", claim.lower()).strip()
        if normalized in seen_claims:
            first = seen_claims[normalized]
            add_finding(
                rule="duplicate-todo-item",
                severity="Low",
                item=item,
                evidence=f"Line {item['line']} duplicates line {first['line']} after normalization.",
                impact="Duplicate todo items can make completion accounting ambiguous.",
                fix=f"Merge or differentiate duplicate todo item from line {first['line']}: {claim}",
            )
        else:
            seen_claims[normalized] = item

        if item["status"] == "checked" and re.search(r"\b(blocked|deferred|remaining|open|todo|needs?|missing)\b", claim, flags=re.I):
            add_finding(
                rule="checked-item-contains-open-work",
                severity="Medium",
                item=item,
                evidence="The item is checked but still contains wording that indicates open or blocked work.",
                impact="The runner may trust an incomplete claim and skip required implementation.",
                fix=f"Reconcile completed status for line {item['line']}; either uncheck it or add the missing work as explicit unchecked subitems.",
            )

        if re.search(r"\b(deploy|production|release|publish|laravel cloud)\b", claim, flags=re.I) and not re.search(
            r"\b(rollback|deploy(?:ment)? pointer|post-?deploy|cloud queue|pending|running|recovery)\b",
            context,
            flags=re.I,
        ):
            add_finding(
                rule="deploy-item-lacks-rollback-gate",
                severity="High",
                item=item,
                evidence="The item references deploy/release/production work but nearby todo text does not mention rollback, deployment queue, or post-deploy verification.",
                impact="An overnight run could deploy without a recorded rollback or deployment-safety gate.",
                fix=f"Add deploy preflight, rollback pointer, and post-deploy verification steps for line {item['line']}: {claim}",
            )

        if pattern_matches(claim, CLASSIFICATION_PATTERNS["ui_browser_work"]) and not re.search(
            r"\b(chromemcp|browser|screenshot|visual|viewport|mobile|desktop|overflow|console)\b",
            context,
            flags=re.I,
        ):
            add_finding(
                rule="ui-item-lacks-browser-evidence",
                severity="Medium",
                item=item,
                evidence="The item is UI/browser-facing but nearby todo text does not require browser, visual, or viewport evidence.",
                impact="The runner could mark visible UX work complete without real browser proof.",
                fix=f"Add ChromeMCP browser evidence, visual QA, and viewport checks for line {item['line']}: {claim}",
            )

        if pattern_matches(claim, CLASSIFICATION_PATTERNS["destructive_cutover"]) and not re.search(
            r"\b(approval|rollback|backup|restore|manifest|explicit)\b",
            context,
            flags=re.I,
        ):
            add_finding(
                rule="destructive-item-lacks-approval-rollback",
                severity="High",
                item=item,
                evidence="The item appears destructive or cutover-related but nearby todo text does not require explicit approval and rollback evidence.",
                impact="The runner could perform destructive work without current-thread authorization or recovery instructions.",
                fix=f"Add explicit approval, backup, rollback, and verification requirements before line {item['line']} can be executed.",
            )

        if re.search(r"\b(all|every|global|full|across|complete|entire)\b", claim, flags=re.I) and not re.search(
            r"\b(matrix|inventory|surface|scope|sample|evidence|checklist|coverage)\b",
            context,
            flags=re.I,
        ):
            add_finding(
                rule="broad-item-lacks-coverage-matrix",
                severity="Medium",
                item=item,
                evidence="The item makes a broad/global claim but nearby todo text does not define a coverage matrix, inventory, or bounded scope.",
                impact="The runner may over-claim completion after checking only a narrow sample.",
                fix=f"Define a bounded coverage matrix or surface inventory for line {item['line']}: {claim}",
            )

    status = "passed" if not any(f["verification_status"] == "verified" for f in findings) else "needs-fixes"
    return {
        "status": status,
        "captured_at": now(),
        "todo_file": todo_file,
        "item_count": len(items),
        "checked_count": sum(1 for item in items if item["status"] == "checked"),
        "unchecked_count": sum(1 for item in items if item["status"] == "unchecked"),
        "findings": findings,
    }


def write_todo_review_report(root: Path, review: dict[str, Any]) -> Path:
    reports = reports_dir(root)
    reports.mkdir(parents=True, exist_ok=True)
    todo_label = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(review["todo_file"])).strip("-")
    digest = hashlib.sha1(json.dumps(review, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    path = reports / f"overnight-todo-adversarial-review-{todo_label}-{digest}.json"
    path.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def run_adversarial_todo_review(root: Path, todo_file: str, *, apply: bool) -> dict[str, Any]:
    review = build_adversarial_todo_review(root, todo_file)
    if apply:
        additions = add_todo_review_fixes(root, todo_file, review["findings"])
        review["applied_fixes"] = additions
        if additions:
            review["status"] = "fixed"
    else:
        review["applied_fixes"] = []
    report = write_todo_review_report(root, review)
    review["report_path"] = str(report.relative_to(root))
    return review


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
        "side_change_candidates": [entry for entry in entries],
        "side_change_policy": SIDE_CHANGE_POLICY,
    }


def has_marker(root: Path, marker: str) -> bool:
    return (root / marker).exists()


def detect_modules(root: Path) -> list[dict[str, Any]]:
    modules = []
    for name, definition in MODULE_DEFINITIONS.items():
        matched = [marker for marker in definition["markers"] if has_marker(root, marker)]
        if not matched:
            continue
        deploy_queue_markers = [
            marker for marker in definition.get("deploy_queue_markers", ()) if has_marker(root, marker)
        ]
        modules.append(
            {
                "name": name,
                "label": definition["label"],
                "matched_markers": matched,
                "deploy_queue_markers": deploy_queue_markers,
                "deploy_rules": list(definition["deploy_rules"]),
                "suggested_checks": list(definition["suggested_checks"]),
            }
        )
    if not modules:
        modules.append(
            {
                "name": "generic",
                "label": "Generic",
                "matched_markers": [],
                "deploy_queue_markers": [],
                "deploy_rules": [
                    "Apply generic deploy safety: explicit authorization, focused tests/builds, rollback notes, and post-deploy verification.",
                    "Do not assume Laravel, WordPress, Node, or another stack-specific deploy command unless the repository provides it.",
                ],
                "suggested_checks": [],
            }
        )
    return modules


def module_names(preflight: dict[str, Any]) -> set[str]:
    return {module.get("name") for module in preflight.get("modules") or []}


def detect_laravel_cloud_queue(root: Path) -> dict[str, Any]:
    cloud = root / "bin/cloud"
    if not cloud.exists():
        return {
            "status": "not-applicable",
            "reason": "No bin/cloud CLI found.",
        }
    environment_list = run_command(
        [str(cloud), "environment:list", "--json", "--fields=id,name,status,currentDeploymentId"],
        cwd=root,
        timeout=30,
    )
    if environment_list["status"] != "passed" or not environment_list.get("stdout"):
        return {
            "status": "unknown",
            "command": environment_list["command"],
            "stderr": environment_list.get("stderr"),
            "reason": "Unable to inspect Laravel Cloud environments.",
        }
    try:
        environments = json.loads(environment_list["stdout"])
    except json.JSONDecodeError:
        return {
            "status": "unknown",
            "command": environment_list["command"],
            "reason": "Laravel Cloud environment output was not JSON.",
        }
    if not isinstance(environments, list) or not environments:
        return {
            "status": "unknown",
            "command": environment_list["command"],
            "reason": "Laravel Cloud returned no environments.",
        }
    environment = next((item for item in environments if item.get("status") == "running"), environments[0])
    environment_id = environment.get("id")
    if not environment_id:
        return {
            "status": "unknown",
            "environment": environment,
            "reason": "Laravel Cloud environment id was unavailable.",
        }
    deployments = run_command(
        [
            str(cloud),
            "deployment:list",
            str(environment_id),
            "--json",
            "--fields=id,status,commitHash,commitMessage,startedAt,finishedAt,failureReason",
        ],
        cwd=root,
        timeout=30,
    )
    if deployments["status"] != "passed" or not deployments.get("stdout"):
        return {
            "status": "unknown",
            "environment": environment,
            "command": deployments["command"],
            "stderr": deployments.get("stderr"),
            "reason": "Unable to inspect Laravel Cloud deployments.",
        }
    try:
        deployment_items = json.loads(deployments["stdout"])
    except json.JSONDecodeError:
        return {
            "status": "unknown",
            "environment": environment,
            "command": deployments["command"],
            "reason": "Laravel Cloud deployment output was not JSON.",
        }
    blocking_statuses = {
        "build.pending",
        "build.running",
        "deployment.pending",
        "deployment.running",
        "pending",
        "running",
    }
    active = None
    if isinstance(deployment_items, list):
        active = next(
            (
                item
                for item in deployment_items
                if str(item.get("status") or "").lower() in blocking_statuses
            ),
            None,
        )
    return {
        "status": "blocked" if active else "passed",
        "environment": environment,
        "active_deployment": active,
        "reason": "Pending/running Laravel Cloud deployment found." if active else "No pending/running Laravel Cloud deployment found.",
    }


def module_preflight_checks(root: Path, modules: list[dict[str, Any]], classifications: list[str]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    if "deploy" not in classifications:
        return checks
    names = {module["name"] for module in modules}
    if "laravel" in names:
        checks["laravel_cloud_queue"] = detect_laravel_cloud_queue(root)
    if "wordpress" in names:
        checks["wordpress_cutover_manifest"] = {
            "status": "required-before-cutover",
            "fields": ["current", "backup", "restore_command", "check"],
            "reason": "WordPress deploy/cutover work needs a rollback manifest before active plugin/theme replacement.",
        }
    return checks


def find_chromemcp_roots(root: Path) -> list[str]:
    env_home = os.environ.get("CHROMEMCP_HOME")
    candidates = [
        Path(env_home) if env_home else None,
        Path.home() / "ChromeMCP",
        Path.home() / ".codex/plugins/rizonetech-local/plugins/chromemcp-browser",
        root / "plugins/chromemcp-browser",
    ]
    found = []
    for candidate in candidates:
        if candidate and candidate.exists() and str(candidate) not in found:
            found.append(str(candidate))
    cli = shutil.which("chromemcp")
    if cli:
        cli_home = str(Path(cli).resolve().parent)
        if cli_home not in found:
            found.append(cli_home)
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
        return "chromemcp up && chromemcp status"
    return "Install or enable the ChromeMCP Browser plugin, then run: chromemcp up && chromemcp status"


def required_gates(preflight: dict[str, Any]) -> set[str]:
    classifications = set(preflight.get("classifications") or [])
    dangerous = set(preflight.get("dangerous_operations") or [])
    modules = module_names(preflight)
    required = {"implemented_review", "implemented", "automated_tests", "feature_gate", "todo_history_updated"}
    if "ui_browser_work" in classifications:
        required.update({"browser_verification", "visual_qa", "workflow_matrix", "browser_handoff"})
    if "deploy" in classifications:
        required.update({"production_deploy", "rollback_plan"})
    if "wordpress" in modules and dangerous:
        required.update({"destructive_approval", "rollback_plan"})
    if "laravel" in modules and "deploy" in classifications:
        required.add("production_deploy")
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


def build_preflight(root: Path, todo_file: str | None, *, no_browser: bool = False) -> dict[str, Any]:
    todo_path = resolve_todo(root, todo_file)
    if todo_file and (todo_path is None or not todo_path.exists()):
        raise SystemExit(f"Todo file not found: {todo_file}")
    text = todo_path.read_text(encoding="utf-8") if todo_path and todo_path.exists() else ""
    todo_items = parse_todo_items(root, todo_file) if todo_file else {"checked": [], "unchecked": [], "blockers": []}
    classification = classify_text(text)
    modules = detect_modules(root)
    module_checks = module_preflight_checks(root, modules, classification["classifications"])
    if no_browser:
        chrome: dict[str, Any] = {"status": "not-applicable", "reason": "--no-browser"}
    else:
        chrome = chromemcp_health(root)
    module_blockers = [
        {"check": name, **check}
        for name, check in module_checks.items()
        if check.get("status") == "blocked"
    ]
    preflight_status = (
        "passed"
        if (no_browser or chrome["status"] == "passed") and not module_blockers
        else "blocked"
    )
    return {
        **classification,
        "status": preflight_status,
        "captured_at": now(),
        "todo_file": todo_file,
        "todo_file_exists": bool(todo_path and todo_path.exists()),
        "todo_items": {
            "checked_count": len(todo_items["checked"]),
            "unchecked_count": len(todo_items["unchecked"]),
            "checked": todo_items["checked"],
        },
        "git": git_snapshot(root),
        "modules": modules,
        "module_checks": module_checks,
        "module_blockers": module_blockers,
        "chromemcp": chrome,
        "notes": [
            "Project modules are detected from repository markers. Apply only the module rules that match this repository.",
            "Every checked todo item must be verified against current code/evidence before trusting it.",
            SIDE_CHANGE_POLICY,
            "ChromeMCP is preferred for user-facing verification.",
            "If ChromeMCP is blocked, browser/UI completion gates must remain blocked until real evidence is captured.",
        ],
    }


RESUME_PRESERVED_KEYS = (
    "notes",
    "blockers",
    "slices",
    "completed_slices",
    "artifacts",
    "rollback_manifest",
)


def resumable_state(root: Path, todo_file: str, *, resume: bool) -> dict[str, Any]:
    """Return the prior state to resume from, or {} for a fresh start.

    Resuming only applies when --resume was passed and the existing state file
    belongs to the SAME todo file; otherwise fall back to a normal start with a
    printed note so unattended relaunches stay safe.
    """
    if not resume:
        return {}
    prior = read_state(root)
    if not prior:
        print(f"--resume requested but no prior state exists; starting fresh: {todo_file}")
        return {}
    if prior.get("todo_file") != todo_file:
        print(
            "--resume requested but prior state is for a different todo file "
            f"({prior.get('todo_file')}); starting fresh: {todo_file}"
        )
        return {}
    return prior


def command_start(args: argparse.Namespace) -> None:
    root = repo_root()
    no_browser: bool = getattr(args, "no_browser", False)
    prior_state = resumable_state(root, args.todo_file, resume=getattr(args, "resume", False))
    todo_review = run_adversarial_todo_review(root, args.todo_file, apply=True)
    preflight = build_preflight(root, args.todo_file, no_browser=no_browser)

    # When --no-browser is set and the todo contains UI-looking work, warn loudly.
    ui_waived = no_browser and "ui_browser_work" in preflight.get("classifications", [])
    if ui_waived:
        print(
            "WARNING: UI/browser-looking items detected in the todo but browser "
            "verification was explicitly waived via --no-browser. "
            "Browser gates (browser_verification, visual_qa) will be marked "
            "not-applicable. The waiver is recorded in state."
        )

    # Determine initial chromemcp state block.
    if no_browser:
        chromemcp_state: dict[str, Any] = {
            "required_for_user_facing": False,
            "status": "not-applicable",
            "waived": True,
            "waiver_reason": "--no-browser flag passed at start",
            "method": "not-applicable",
            "evidence": [preflight["chromemcp"]],
            "blockers": [],
            "report_paths": [],
            "screenshot_paths": [],
            "routes": [],
            "viewports": [],
            "final_visible_handoff": False,
        }
    else:
        chromemcp_state = {
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
        }

    # Build blank gates; then override browser-dependent gates as not-applicable when waived.
    gates = blank_gates(preflight)
    if no_browser:
        for gate_name in ("browser_verification", "visual_qa"):
            if gate_name in gates:
                gates[gate_name]["status"] = "not-applicable"
                gates[gate_name]["required"] = False
                gates[gate_name].setdefault("evidence", []).append({
                    "at": now(),
                    "note": "Waived via --no-browser" + (" (UI items detected)" if ui_waived else ""),
                })

    state = {
        "active": True,
        "started_at": now(),
        "updated_at": now(),
        "todo_file": args.todo_file,
        "no_browser": no_browser,
        "current_slice": None,
        "status": "started" if preflight["status"] == "passed" else "preflight_blocked",
        "preflight": preflight,
        "todo_adversarial_review": todo_review,
        "modules": preflight["modules"],
        "module_checks": preflight["module_checks"],
        "gates": gates,
        "slices": {},
        "notes": [],
        "completed_slices": [],
        "blockers": [],
        "artifacts": [],
        "checked_item_review": {
            "status": "pending" if preflight["todo_items"]["checked_count"] else "not-applicable",
            "items": {
                item["claim_id"]: {
                    "line": item["line"],
                    "claim": item["claim"],
                    "status": "pending",
                    "evidence": [],
                    "missing_items": [],
                    "updated_at": None,
                }
                for item in preflight["todo_items"]["checked"]
            },
        },
        "chromemcp_failures": {},
        "chromemcp": chromemcp_state,
        "visual_qa": {"status": "pending", "checks": [], "evidence": [], "screenshot_paths": [], "blockers": []},
        "workflow_matrix": {"status": "pending", "matrix_paths": [], "routes": [], "viewports": [], "states": []},
        "deploy": {"status": "pending" if "deploy" in preflight["classifications"] else "not-applicable", "evidence": [], "blockers": []},
        "commit_push": {"status": "pending", "commit_sha": None, "branch": None, "evidence": [], "blockers": []},
        "rollback_manifest": {},
        "next_action": "Read the adversarial todo review report, reconcile the codebase, and start the first unblocked slice.",
    }
    if prior_state:
        for key in RESUME_PRESERVED_KEYS:
            if key in prior_state:
                state[key] = prior_state[key]
        state["resumed_at"] = now()
        state["resumed_from_started_at"] = prior_state.get("started_at")
    write_state(root, state)
    if prior_state:
        print(
            f"Resumed Overnight Runner: {args.todo_file} "
            f"(preserved {', '.join(RESUME_PRESERVED_KEYS)})"
        )
    print(f"Started Overnight Runner: {args.todo_file}")
    print(f"Adversarial todo review: {todo_review['status']} ({len(todo_review['findings'])} findings, {len(todo_review.get('applied_fixes') or [])} fixes)")
    print(f"Adversarial todo review report: {todo_review['report_path']}")
    print("Preflight classifications: " + ", ".join(preflight["classifications"]))
    print("Modules: " + ", ".join(module["name"] for module in preflight["modules"]))
    if no_browser:
        print("ChromeMCP: not-applicable (--no-browser)")
        if ui_waived:
            print("WARNING: UI-looking items detected; browser verification waived via --no-browser.")
    else:
        print(f"ChromeMCP: {preflight['chromemcp']['status']}")
        if preflight.get("module_blockers"):
            print("Module blockers: " + ", ".join(blocker["check"] for blocker in preflight["module_blockers"]))
        if preflight["chromemcp"]["status"] != "passed":
            print("ChromeMCP blocker recorded; non-browser work may continue when safe.")
            print("Recovery: " + preflight["chromemcp"].get("recovery", "not available"))


def command_preflight(args: argparse.Namespace) -> None:
    root = repo_root()
    preflight = build_preflight(root, args.todo_file)
    print(json.dumps(preflight, indent=2, sort_keys=True))


def command_todo_review(args: argparse.Namespace) -> None:
    root = repo_root()
    review = run_adversarial_todo_review(root, args.todo_file, apply=args.apply)
    state = read_state(root)
    if state:
        state["todo_adversarial_review"] = review
        state["updated_at"] = now()
        write_state(root, state)
    print(json.dumps(review, indent=2, sort_keys=True))


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
    name = normalize_gate_name(name.strip())
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


def append_missing_items_to_todo(
    root: Path,
    todo_file: str,
    line_number: int,
    missing_items: list[str],
    *,
    completed: bool = False,
) -> list[dict[str, Any]]:
    todo_path = resolve_todo(root, todo_file)
    if not todo_path or not todo_path.exists():
        raise SystemExit(f"Todo file not found: {todo_file}")
    lines = todo_path.read_text(encoding="utf-8").splitlines()
    if line_number < 1 or line_number > len(lines):
        raise SystemExit(f"Todo line does not exist: {line_number}")
    parent = lines[line_number - 1]
    indent = todo_line_indent(parent) + "  "
    existing = set(lines)
    additions = []
    added_claims = []
    for item in missing_items:
        text = item.strip()
        if not text:
            continue
        marker = "x" if completed else " "
        prefix = "Remediated gap from completed claim" if completed else "Missing from completed claim"
        claim = f"{prefix}: {text}"
        addition = f"{indent}- [{marker}] {claim}"
        if addition not in existing:
            additions.append(addition)
            existing.add(addition)
            added_claims.append({"claim": claim, "claim_id": claim_id(claim)})
    if not additions:
        return []
    lines[line_number:line_number] = additions
    todo_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return added_claims


def command_checked_review(args: argparse.Namespace) -> None:
    root = repo_root()
    state = ensure_state(root)
    todo_file = args.todo_file or state.get("todo_file")
    if not todo_file:
        raise SystemExit("No todo file supplied and no active run todo_file found.")
    items = parse_todo_items(root, todo_file)["checked"]
    item = next((candidate for candidate in items if candidate["line"] == args.line), None)
    if item is None:
        raise SystemExit(f"No checked todo item found at line {args.line}.")
    if args.status in {"missing-added", "remediated"} and not args.missing:
        raise SystemExit(f"--status {args.status} requires at least one --missing item.")
    if args.status == "remediated" and not (args.evidence or args.note or args.command):
        raise SystemExit("--status remediated requires --evidence, --note, or --command proving the gap was implemented.")
    added_claims: list[dict[str, Any]] = []
    if args.add_missing and args.missing:
        added_claims = append_missing_items_to_todo(
            root,
            todo_file,
            args.line,
            args.missing,
            completed=args.status == "remediated",
        )
    review = state.setdefault("checked_item_review", {"status": "pending", "items": {}})
    reviewed = review.setdefault("items", {}).setdefault(
        item["claim_id"],
        {
            "line": item["line"],
            "claim": item["claim"],
            "status": "pending",
            "evidence": [],
            "missing_items": [],
            "updated_at": None,
        },
    )
    reviewed["line"] = item["line"]
    reviewed["claim"] = item["claim"]
    reviewed["status"] = args.status
    reviewed["updated_at"] = now()
    if args.evidence or args.note:
        reviewed.setdefault("evidence", []).append(
            {
                "at": now(),
                "note": args.note,
                "evidence": args.evidence or [],
                "command": args.command,
            }
        )
    append_unique(reviewed.setdefault("missing_items", []), args.missing)
    if args.status == "remediated":
        reviewed["remediated_at"] = now()
        reviewed["remediation_note"] = "Missing work was implemented before this checked claim was accepted."
        for added in added_claims:
            review.setdefault("items", {})[added["claim_id"]] = {
                "line": None,
                "claim": added["claim"],
                "status": "passed",
                "evidence": [
                    {
                        "at": now(),
                        "note": args.note or "Remediated as part of parent checked-claim verification.",
                        "evidence": args.evidence or [],
                        "command": args.command,
                    }
                ],
                "missing_items": [],
                "updated_at": now(),
                "parent_claim_id": item["claim_id"],
            }
    current_ids = {candidate["claim_id"] for candidate in parse_todo_items(root, todo_file)["checked"]}
    statuses = [
        entry.get("status", "pending")
        for claim, entry in review.get("items", {}).items()
        if claim in current_ids
    ]
    if not current_ids:
        review["status"] = "not-applicable"
    elif statuses and all(status in {"passed", "remediated"} for status in statuses) and len(statuses) == len(current_ids):
        review["status"] = "passed"
        update_gate(state, "implemented_review=passed", "All checked todo claims reviewed and any discovered gaps remediated.")
    elif any(status == "failed" for status in statuses):
        review["status"] = "failed"
        update_gate(state, "implemented_review=failed", "At least one checked todo claim failed verification.")
    elif any(status == "blocked" for status in statuses):
        review["status"] = "blocked"
        update_gate(state, "implemented_review=blocked", "At least one checked todo claim is blocked.")
    else:
        review["status"] = "pending"
    state["updated_at"] = now()
    write_state(root, state)
    print(f"Reviewed checked todo line {args.line}: {args.status}")


def todo_unchecked_and_blocked(root: Path, todo_file: str | None, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    items = parse_todo_items(root, todo_file)
    return items["checked"][:limit], items["unchecked"][:limit], items["blockers"][:limit]


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
    todo_file = state.get("todo_file")
    todo_review = state.get("todo_adversarial_review") or {}
    if todo_file:
        if not todo_review:
            errors.append("adversarial todo review has not been run")
        elif not todo_review.get("report_path"):
            errors.append("adversarial todo review did not record a report_path")
        elif todo_review.get("status") == "needs-fixes":
            errors.append("adversarial todo review has verified findings that were not added back to the todo")
    current_checked = parse_todo_items(root, todo_file)["checked"] if todo_file else []
    review = state.get("checked_item_review") or {}
    reviewed_items = review.get("items") or {}
    for item in current_checked:
        entry = reviewed_items.get(item["claim_id"])
        if not entry:
            errors.append(f"checked todo line {item['line']} has not been verified: {item['claim']}")
            continue
        status = entry.get("status", "pending")
        if status in {"passed", "remediated"}:
            if status == "remediated" and not entry.get("missing_items"):
                errors.append(f"checked todo line {item['line']} is remediated but has no missing_items recorded")
            continue
        if status == "missing-added":
            errors.append(
                f"checked todo line {item['line']} has gaps added but not remediated: {item['claim']}"
            )
            continue
        if status == "blocked" and allow_blocked:
            continue
        errors.append(f"checked todo line {item['line']} verification is {status}: {item['claim']}")

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
    ui_required = (state.get("gates") or {}).get("browser_verification", {}).get("required")
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
    # Echo --no-browser waiver so completion claims stay honest.
    chromemcp_state = state.get("chromemcp") or {}
    if chromemcp_state.get("waived"):
        print("NOTE: browser verification waived via --no-browser (recorded at start)")
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
    modules = state.get("modules") or (state.get("preflight") or {}).get("modules") or []
    lines = [
        "## Run Handoff",
        "",
        "- Modules: " + (", ".join(module.get("name", "unknown") for module in modules) if modules else "not recorded"),
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
    start.add_argument(
        "--no-browser",
        dest="no_browser",
        action="store_true",
        help=(
            "Skip the ChromeMCP health probe and mark browser gates not-applicable; "
            "use for todo runs with no UI/browser work."
        ),
    )
    start.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Preserve notes, blockers, slices, completed slices, artifacts, and "
            "the rollback manifest from an existing state for the SAME todo file "
            "while refreshing preflight, adversarial review, and timestamps. "
            "Falls back to a normal start when no matching prior state exists."
        ),
    )
    start.set_defaults(func=command_start)

    preflight = sub.add_parser("preflight", help="Classify a todo and probe ChromeMCP.")
    preflight.add_argument("todo_file", nargs="?")
    preflight.set_defaults(func=command_preflight)

    todo_review = sub.add_parser("todo-review", help="Adversarially review a todo file and optionally add missing guardrail items.")
    todo_review.add_argument("todo_file")
    todo_review.add_argument("--apply", action="store_true", help="Add verified missing guardrail items back into the todo file.")
    todo_review.set_defaults(func=command_todo_review)

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

    checked_review = sub.add_parser("checked-review", help="Record verification for an existing checked todo item.")
    checked_review.add_argument("--todo-file")
    checked_review.add_argument("--line", type=int, required=True, help="1-based line number of the checked todo item.")
    checked_review.add_argument(
        "--status",
        required=True,
        choices=["passed", "missing-added", "remediated", "failed", "blocked"],
        help="Verification result for the completed claim.",
    )
    checked_review.add_argument("--evidence", action="append", help="Current code, command, URL, artifact, or note proving the claim.")
    checked_review.add_argument("--missing", action="append", help="Missing work discovered while verifying this completed claim.")
    checked_review.add_argument(
        "--add-missing",
        action="store_true",
        help="Append --missing items to the todo. With --status remediated they are added as checked remediation items.",
    )
    checked_review.add_argument("--command", help="Verification command used for this claim.")
    checked_review.add_argument("--note", help="Short verification note.")
    checked_review.set_defaults(func=command_checked_review)

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
