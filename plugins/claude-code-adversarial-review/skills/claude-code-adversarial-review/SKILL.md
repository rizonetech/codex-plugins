---
name: claude-code-adversarial-review
description: Adversarially review Claude Code changes from Codex with evidence-first severity findings, false-positive discipline, and re-review guidance.
---

# Claude Code Adversarial Review

Use this skill when the user asks Codex to review Claude Code output, a Claude Code PR, a Claude Code diff, a completed TODO section, or any change described as needing an adversarial review.

You are the external reviewer. Claude Code's implementation is not presumed correct, but neither are your suspicions. A finding is valid only when it is verified in the actual repository with file and line evidence.

## Review Contract

- Inspect the real diff, commit, PR patch, TODO section, and relevant surrounding code before reporting findings.
- Do not rely on Claude Code summaries, completion claims, or changelog text as evidence.
- Verify each finding against concrete code paths, callers, configuration, tests, or runtime behavior.
- Classify each potential issue as `Fix`, `Reject`, `Accept`, or `Question`.
- Treat `Critical` and `High` findings as blockers until fixed or explicitly rejected with evidence.
- Keep scope bounded to the requested diff or TODO section unless a changed contract creates wider risk.
- Do not request unrelated refactors, style churn, or speculative features.

## Initial Inspection

Gather the smallest complete review context:

```bash
git status --short
git diff --stat
git diff --name-only
git diff
```

If the review targets a commit, branch, or PR, inspect that comparison instead of only the working tree. If the user gives a TODO file or section, read the TODO file and the changed files it references.

When code has already been committed, compare the implementation against its base branch or parent commit. When the base is unclear, state the assumption and use the most defensible local comparison.

## Adversarial Checklist

Apply the checklist according to the stack and touched behavior:

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

## False-Positive Discipline

Before reporting, try to disprove your own finding:

- Search for callers, guards, feature flags, middleware, validators, and framework guarantees.
- Check whether a lock, transaction, auth check, or sanitizer is provided by the caller.
- Distinguish impossible states from merely non-obvious states.
- Treat uncertainty as an open question or residual risk, not as a defect.
- Do not flag missing tests as a functional bug unless the behavior is unverified and high-risk.

Common rejects:

- A race that cannot occur because the path is single-threaded or externally serialized.
- A missing null check where construction or validation makes null impossible.
- A buffer or length concern covered by a static assertion or bounded parser.
- A dead-code claim without checking generated calls, reflection, hooks, routes, or external entry points.

## Findings Format

Lead with findings. Order by severity. Use this shape:

```text
[High] Title
File/line: path/to/file.ext:123
Evidence: What the code does and how you verified it.
Impact: What breaks, who is affected, and when.
Required fix or rejection test: The specific change or evidence needed to close it.
```

Severity rubric:

- `Critical`: data loss, auth bypass, remote exploit, production outage, destructive deploy risk.
- `High`: core workflow regression, serious security bug, broken build/test path, lost write, race, rollback failure.
- `Medium`: edge-case incorrectness, incomplete error handling, compatibility risk, missing test for non-trivial changed behavior.
- `Low`: maintainability, minor performance, naming, local style, or small test hygiene issue.

If no actionable findings exist, say so clearly and list residual risks or test gaps separately.

## Fix And Re-Review Loop

If the user asks you to fix findings:

1. Fix root causes with the smallest safe code change.
2. Run relevant tests or targeted verification.
3. Re-review the exact previous findings against the updated code.
4. Repeat up to three rounds for unresolved `Critical` or `High` issues.
5. Escalate clearly if a blocker remains unresolved after three rounds.

Do not weaken assertions, delete tests, or narrow checks merely to make the review pass.

## Final Verdict

End with exactly one verdict:

- `PASS`: no actionable findings and no material test gaps.
- `PASS WITH LOWS`: only Low findings or minor residual risks remain.
- `NEEDS FIXES`: Medium or higher actionable findings remain.
- `BLOCKED`: required context, build, tests, credentials, or browser access is missing.

Also include the key files or commands inspected and any residual risk that a maintainer should still understand.
