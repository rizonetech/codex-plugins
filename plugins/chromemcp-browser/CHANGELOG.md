# Changelog

All notable changes to ChromeMCP are recorded here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- ChromeMCP Browser now defaults Codex to the isolated ChromeMCP stack at
  `http://localhost:8941/mcp` with token path
  `~/.config/chromemcp-codex/token`. This keeps Codex browser work separate
  from the default Claude/shared ChromeMCP instance on `8931/9222`.
- `chromemcp-run` now honors `CODEX_CHROMEMCP_LANE`, allowing concurrent Codex
  overnight runs to target different ChromeMCP lanes without sharing tabs,
  profiles, ports, or token files.

### Verified Chrome versions

- **Last verified-working Chrome**: `148.0.7778.98` (Windows stable, 2026-05-19).
- **Supported range** (warning-free): Chrome major `140` through `150`.
  Setting `MCP_CHROME_MIN_MAJOR` / `MCP_CHROME_MAX_MAJOR` overrides the
  range locally. `mcp/start.sh` prints the live version and warns
  (without failing) when out of range — see [`docs/chrome-pinning.md`](docs/chrome-pinning.md)
  for how to pin Chrome on Windows Enterprise.

### Changed

- **Improved Codex plugin installation** so `scripts/install-codex-plugin.sh`
  now creates a tokenized user-local marketplace copy under
  `~/.codex/plugins/chromemcp-local/` instead of requiring users to hand-edit
  the tracked plugin `.mcp.json`. The repository copy keeps the `<TOKEN>`
  placeholder so bearer tokens stay out of git.
- **Pinned `@playwright/mcp` to `0.0.75`** (was `0.0.74`). The 0.0.75 release
  contains only bug fixes — no MCP tool-name or argument changes — so this is
  a safe minor bump for existing clients. Tracks roadmap initiative
  [`G1`](todo/production-readiness.md#g1-pin-to-a-stable-playwright-mcp-release).
- **Overrode the transitive `playwright-core` and `playwright` dependencies to
  `1.60.0`** (stable) via the `overrides` field in [`mcp/package.json`](mcp/package.json).
  Every published version of `@playwright/mcp` from `0.0.59` through `0.0.75`
  declares an `-alpha-` build of `playwright-core` as a direct dependency.
  Until upstream ships a release with stable-deps, we hold the transitive at
  a known-good stable.

### Notes for upgraders

- Run `cd mcp && rm -rf node_modules package-lock.json && npm install` once
  to refresh the lockfile against the new pin and overrides. After that,
  `npm ci` works as expected.
- `npm ls` will report `playwright-core@1.60.0 overridden` — that is the
  intended outcome of this change, not a warning.
- The override is conservative: `1.60.0` matches the *minor* version that
  `@playwright/mcp@0.0.74` was originally requesting in alpha form, so the
  surface area between requested and resolved is small. If a future
  `@playwright/mcp` release fixes the alpha-pin upstream, drop the
  `overrides` block.

### Verified

- `bash scripts/test-codex-plugin.sh` validates the Codex plugin manifest,
  marketplace metadata, tokenized installer output, and unified CLI commands.
- `npm ci` produces `node_modules/playwright-core/package.json` with
  `"version": "1.60.0"` (no `-alpha-`, no `-beta-`).
- `bash mcp/test.sh` exits clean — `initialize`, `browser_tabs(list)`, and
  `browser_snapshot` all return successfully against a live Chrome via CDP.
- `bash mcp/demo-visible.sh` exits clean — opens a new tab, captures a
  screenshot, and closes the tab without leaving Chrome in a bad state.

## [0.1.0] — 2026-05-09

- Initial public layout: WSL↔Windows bridge (`Setup-Bridge.cmd` +
  `Setup-WSL-Portproxy.ps1`), MCP server wrapper (`mcp/start.sh`), Codex
  local plugin (`plugins/chromemcp-browser`), and convenience wrappers
  (`mcp-up`, `mcp-down`, `chrome`, `setup-bridge`).
