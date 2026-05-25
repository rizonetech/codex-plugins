---
name: claude-code-adversarial-review
description: Ask Claude Code to adversarially review Codex changes, then verify Claude's findings with file-line evidence before fixing, rejecting, or accepting them.
---

# Claude Code Adversarial Review

Use this skill when the user asks for Claude Code adversarial review, Claude review of Codex work, external review of Codex changes, review of a TODO section Codex completed, or verification of Claude's review findings.

The workflow is intentionally two-party:

1. Claude Code performs the adversarial review of Codex's changes.
2. Codex verifies every Claude finding against the repository before acting.

Claude is the skeptical reviewer. Codex is responsible for evidence, triage, fixes, and final accountability.

## Review Contract

- Do not present Codex self-review as the adversarial review.
- Ask Claude Code to review the real diff, commit, PR patch, TODO section, and relevant surrounding code.
- Treat Claude's findings as claims, not facts.
- Verify each Claude finding against concrete code paths, callers, configuration, tests, or runtime behavior.
- Classify each Claude finding as `Fix`, `Reject`, `Accept`, or `Question`.
- Treat verified `Critical` and `High` findings as blockers until fixed or explicitly rejected with evidence.
- Keep scope bounded to the requested diff or TODO section unless a changed contract creates wider risk.
- Do not request unrelated refactors, style churn, or speculative features.

## Prepare The Claude Review

Gather the smallest complete review context:

```bash
git status --short
git diff --stat
git diff --name-only
git diff
```

If the review targets a commit, branch, or PR, inspect that comparison instead of only the working tree. If the user gives a TODO file or section, read the TODO file and identify the changed files it references.

When code has already been committed, compare the implementation against its base branch or parent commit. When the base is unclear, state the assumption and use the most defensible local comparison.

If the `claude` CLI is available, run Claude Code non-interactively from the repository root. Use a prompt shaped like this:

```bash
claude -p '<prompt>'
```

Prompt Claude with:

```text
[review-kind: adversarial]

You are reviewing Codex changes as an external adversarial reviewer.

Scope:
- Review only the provided diff/TODO/commit scope unless a changed contract creates wider risk.
- Look for real bugs, regressions, security issues, missing rollback/error handling, concurrency problems, broken wiring, data loss, and insufficient tests.
- Do not give style-only feedback unless it hides a defect.
- Every finding must include severity, file:line, evidence, impact, and a concrete fix or rejection test.
- If no actionable issues exist, say so directly and list residual risks separately.

Review target:
<describe diff, commit range, TODO section, or PR>
```

Prefer passing Claude enough context to inspect files itself. If Claude CLI is unavailable, blocked, or unauthenticated, stop with `BLOCKED` and give the exact Claude prompt the user can run manually.

## Claude Checklist

Ask Claude to apply this checklist according to the stack and touched behavior:

- Functional correctness, edge cases, off-by-one behavior, empty/null/malformed input.
- Regressions in callers, contracts, public APIs, command behavior, routes, config, schemas, and generated artifacts.
- Wiring and lifecycle issues: registration, initialization order, dependency injection, middleware, hooks, cron/jobs, queues, deploy scripts.
- Error paths: rollback, cleanup, partial failure, retry behavior, idempotency, resource leaks.
- Security: authz/authn, crafted input, injection, secrets, SSRF, CSRF, XSS, DoS, privilege boundaries.
- Data correctness: migrations, schema compatibility, destructive operations, concurrency, transactions, locking, stale reads.
- Boundary behavior: integer limits, parsing, serialization, path handling, encoding, timezones, locale, ABI/struct layout when relevant.
- Memory or low-level safety when applicable: null dereference, use-after-free, double free, uninitialized data, alignment, sign extension.
- Performance risks: hot path allocations, N+1 queries, unbounded loops, O(n2) behavior, large payloads.
- Test adequacy for changed behavior, especially failure modes and contract boundaries.

For UI/browser claims, require real browser evidence when the task depends on it. Prefer ChromeMCP-visible verification if available; headless or raw CDP evidence is diagnostic and should not replace a required visible browser check.

## Verify Claude Findings

Before reporting or fixing a Claude finding, try to disprove it:

- Open the cited file and line; confirm the cited code exists.
- Search for callers, guards, feature flags, middleware, validators, generated paths, framework guarantees, and tests.
- Check whether a lock, transaction, auth check, sanitizer, or invariant is provided by the caller.
- Distinguish impossible states from merely non-obvious states.
- Treat uncertainty as `Question`, not as a verified defect.
- Do not mark a finding `Fix` only because Claude said it confidently.

Common rejects:

- A race that cannot occur because the path is single-threaded or externally serialized.
- A missing null check where construction or validation makes null impossible.
- A buffer or length concern covered by a static assertion or bounded parser.
- A dead-code claim without checking generated calls, reflection, hooks, routes, or external entry points.

## Verified Findings Format

Lead with verified findings. Order by severity. Use this shape:

```text
[High] Title
Claude claim: Short summary of Claude's finding.
Verdict: Fix | Reject | Accept | Question
File/line: path/to/file.ext:123
Evidence: What Codex verified in the repository.
Impact: What breaks, who is affected, and when.
Required fix or rejection test: The specific change or evidence needed to close it.
```

Severity rubric:

- `Critical`: data loss, auth bypass, remote exploit, production outage, destructive deploy risk.
- `High`: core workflow regression, serious security bug, broken build/test path, lost write, race, rollback failure.
- `Medium`: edge-case incorrectness, incomplete error handling, compatibility risk, missing test for non-trivial changed behavior.
- `Low`: maintainability, minor performance, naming, local style, or small test hygiene issue.

If Claude returns no actionable findings, Codex must still inspect the diff enough to verify that the no-finding result is plausible. Say what was checked.

## Fix And Re-Review Loop

If the user asks Codex to fix verified findings:

1. Fix root causes with the smallest safe code change.
2. Run relevant tests or targeted verification.
3. Ask Claude Code to re-review the updated diff or the fixed findings.
4. Verify Claude's new findings or confirmations.
5. Repeat up to three rounds for unresolved `Critical` or `High` issues.
6. Escalate clearly if a blocker remains unresolved after three rounds.

Do not weaken assertions, delete tests, or narrow checks merely to make the review pass.

## Final Verdict

End with exactly one verdict:

- `PASS`: Claude found no actionable issues, Codex verification agrees, and no material test gaps remain.
- `PASS WITH LOWS`: only Low findings or minor residual risks remain.
- `NEEDS FIXES`: Medium or higher verified findings remain.
- `BLOCKED`: Claude review could not run, or required context, build, tests, credentials, or browser access is missing.

Also include the Claude command or manual prompt used, key files or commands Codex inspected, and any residual risk that a maintainer should still understand.
