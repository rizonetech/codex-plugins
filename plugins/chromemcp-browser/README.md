# ChromeMCP

A small, opinionated stack that lets agents in **WSL2** drive your **real, signed-in Chrome on Windows** through the Model Context Protocol (MCP).

You launch Chrome once with CDP enabled against a project-local profile, expose that debug port to WSL through a scoped portproxy + firewall rule, and run [Playwright MCP](https://github.com/microsoft/playwright-mcp) as a long-running HTTP/SSE service that any MCP client (Claude Code, Cursor, Continue, etc.) can attach to. Every client shares the same browser session — same tabs, same cookies, same logins.

## Why this exists

Most "browser for agents" setups spin up a throwaway headless Chromium with an empty profile. That's fine for scraping and useless for real work — your agent can't see the sites you're already logged into. ChromeMCP flips that around: the browser is your normal browser, kept alive between sessions, and the MCP server is the disposable bit.

It's also **multi-client by design**. Run Claude Code and Cursor at the same time, both pointing at the same MCP endpoint, both driving the same Chrome window.

ChromeMCP is also **watchable by default**. Browser tool calls focus the visible ChromeMCP Chrome window before they run, so you can monitor what an agent is doing in real time. Set `MCP_VISIBLE_INTERACTIONS=0` before starting the server only if you want ChromeMCP to stay in the background.

## Architecture

```
┌─────────────── Windows host ───────────────┐    ┌──────── WSL2 ────────┐
│                                            │    │                      │
│  Chrome.exe                                │    │  Playwright MCP      │
│  ├─ profile: %LOCALAPPDATA%\ChromeMCP      │    │  (HTTP/SSE server)   │
│  └─ --remote-debugging-port=9222           │    │  localhost:8931/mcp  │
│         │                                  │    │       │              │
│         │ 127.0.0.1:9222 (CDP)             │    │       │              │
│         ▼                                  │    │       ▼              │
│  netsh portproxy ◄───── firewall ──────────┼────┤  CDP client          │
│  (vEthernet WSL IP)    (WSL subnet only)   │    │                      │
│                                            │    │  ▲ ▲ ▲               │
└────────────────────────────────────────────┘    │  │ │ │  MCP clients  │
                                                  │  Claude Code, Cursor,│
                                                  │  Continue, ...       │
                                                  └──────────────────────┘
```

Two things are worth pointing out:

- **The Chrome profile lives in `%LOCALAPPDATA%\ChromeMCP\Profile`, not in this repo.** Browser data is hundreds of MB of SQLite/mmap files accessed at high frequency — it belongs on Windows-native storage, not on a 9p share inside WSL.
- **The portproxy binds only to the WSL vEthernet adapter IP**, and the firewall rule restricts the source to the WSL subnet. CDP is effectively unauthenticated, so network scoping is the security boundary. Your LAN cannot see port 9222.

## Requirements

- Windows 10/11 with WSL2 and Google Chrome installed (Chrome major **140 +**; see [`docs/chrome-pinning.md`](docs/chrome-pinning.md) for pinning on Enterprise)
- A WSL2 distro (tested on Ubuntu)
- Node.js ≥ 18.18 inside WSL
- PowerShell 5.1+ on Windows (ships with Windows by default)
- Administrator rights on Windows for the one-time bridge setup
- Tested with `@playwright/mcp@0.0.75` and `playwright-core@1.60.0` (both pinned exactly in [`mcp/package.json`](mcp/package.json); see [`CHANGELOG.md`](CHANGELOG.md) for upgrade notes)

## Install

```bash
curl -fsSL https://github.com/rizonetech/ChromeMCP/raw/main/scripts/install.sh | bash
```

Installs to `~/.local/share/chromemcp/`, symlinks `chromemcp` into `~/.local/bin/`, and runs `npm ci` against the bundled pin. Override with `CHROMEMCP_PREFIX` / `CHROMEMCP_BIN_DIR` env vars. Pin a specific release with `… | bash -s -- --version v0.1.1`. From a local checkout (e.g. while iterating on the installer itself): `bash scripts/install.sh --from-source`.

After install, `chromemcp` is the single command you'll use:

```text
chromemcp setup-bridge      # one-time Windows-side bridge setup (UAC)
chromemcp chrome            # launch signed-in Chrome with CDP
chromemcp up                # start the MCP server
chromemcp token             # print the bearer token for client config
chromemcp test              # smoke test
chromemcp enable            # optional: install systemd user unit so the
                            # stack auto-restarts on crash + survives logout
chromemcp status            # health report
chromemcp logs --grep error # tail / search logs
chromemcp upgrade           # pull the latest release
chromemcp uninstall         # remove the install
```

`chromemcp help` lists every subcommand.

## Quick start (from a clone)

If you want to develop on the stack instead of consuming the release tarball, clone and run from the working tree:

```bash
./mcp-up                         # brings up the entire stack
bash mcp/test.sh                 # sanity check (optional)
```

That single `./mcp-up` is enough. It pre-flights the upstream CDP endpoint and, if it's not reachable, transparently:

1. Launches Chrome on Windows via `launcher/Launch-Chrome.ps1` (idempotent, no-op if Chrome is already up).
2. Installs the WSL↔Windows bridge via `Setup-Bridge.cmd` if Chrome is up but its debug port isn't reachable from WSL — this pops a one-time UAC prompt on your Windows desktop. Approve it.
3. Starts the Playwright MCP HTTP/SSE service. First run also runs `npm ci` to install dependencies.

The first time, sign in to whichever sites you want the agent to access in the new Chrome window. The profile lives in `%LOCALAPPDATA%\ChromeMCP\Profile` and persists across restarts, so you only sign in once.

By default, ChromeMCP starts Chrome maximized and brings it to the foreground before browser tool calls. This keeps Codex, Claude Code, Cursor, and other MCP clients visibly inspectable while they work.

To opt out of either auto-step (e.g. for CI or restricted environments):

```bash
MCP_NO_AUTO_CHROME=1 ./mcp-up    # don't auto-launch Chrome
MCP_NO_AUTO_BRIDGE=1 ./mcp-up    # don't auto-install the bridge (skip UAC)
MCP_VISIBLE_INTERACTIONS=0 ./mcp-up # don't focus Chrome before tool calls
```

The individual scripts also still work for explicit, manual control:

```bash
./chrome                         # launch Chrome (e.g. with -Force or a custom -Port)
./setup-bridge                   # install the bridge by itself
./setup-bridge /remove           # tear the portproxy + firewall rule down
./mcp-down                       # stop the MCP server
```

## Connecting MCP clients

The MCP server listens at `http://localhost:8931/mcp`. Drop the snippet from [`mcp/client-config.json`](mcp/client-config.json) into your client's MCP config file:

- **Codex** — use the Rizonetech plugin marketplace from the `codex-plugins` repository. Run `scripts/install-rizonetech-local.ps1`, enable `chromemcp-browser@rizonetech-local`, restart Codex, then start ChromeMCP with `./mcp-up`.
- **Claude Code** — `~/.claude.json` (or a project-local `.mcp.json`)
- **Cursor** — `~/.cursor/mcp.json`
- **Continue** — your `config.json`'s `mcpServers` block

Only the inner `mcpServers` entry needs to be merged into existing files. The `/mcp` path uses the modern Streamable HTTP transport; older clients can target `/sse` instead. See [`docs/CLIENTS.md`](docs/CLIENTS.md) for copy-paste client examples.

## Authentication

The MCP endpoint requires a bearer token. The first `./mcp-up` generates one to `~/.config/chromemcp/token` (mode `0600`). To get it:

```bash
./mcp-token                # print the token (generates one if missing)
./mcp-token --header       # print as 'Authorization: Bearer <token>' for curl
./mcp-token --path         # print the token file path
./mcp-token --rotate       # generate a fresh token (restart server after)
```

Drop the token into your MCP client config — replace `<TOKEN>` in the snippet from [`mcp/client-config.json`](mcp/client-config.json):

```json
"headers": { "Authorization": "Bearer <TOKEN>" }
```

Unauthenticated requests return `HTTP 401`. To **disable** auth for local debugging only:

```bash
MCP_NO_AUTH=1 ./mcp-up     # auth bypass; logs a warning on every request
```

See [`SECURITY.md`](SECURITY.md) for the full threat model, including what the auth proxy does and does not defend against.

### Codex local plugin

This repository includes a Codex plugin wrapper so ChromeMCP can be used as a callable browser-tool replacement when the bundled Chrome connector is unavailable.

The easiest install path is from PowerShell at the `codex-plugins` repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-rizonetech-local.ps1
```

The installer generates or reuses the ChromeMCP bearer token, creates a tokenized user-local marketplace copy under `~/.codex/plugins/rizonetech-local/`, and points Codex at that generated marketplace. Then restart Codex.

Add this marketplace and plugin entry to `~/.codex/config.toml`:

```toml
[marketplaces.rizonetech-local]
source_type = "local"
source = '<generated Windows UNC path to ~/.codex/plugins/rizonetech-local>'

[plugins."chromemcp-browser@rizonetech-local"]
enabled = true

[plugins."bashlane@rizonetech-local"]
enabled = true
```

Then restart Codex and run:

```bash
cd /path/to/codex-plugins/plugins/chromemcp-browser
./mcp-up
bash mcp/test.sh
bash scripts/test-codex-plugin.sh
```

The plugin exposes the MCP server as `chromemcp-playwright`. The tracked `plugins/chromemcp-browser/.mcp.json` intentionally keeps `Authorization: Bearer <TOKEN>` so secrets stay out of git; the installer writes the real token only into the generated local marketplace copy. Re-run `scripts/install-rizonetech-local.ps1` after `./mcp-token --rotate`.

See [`docs/CODEX_PLUGIN.md`](docs/CODEX_PLUGIN.md) for redistribution notes and manual install details.

## Repository layout

```
.
├── .agents/plugins/marketplace.json  Local Codex marketplace entry
├── chrome              WSL wrapper → launcher/Launch-Chrome.ps1
├── chrome.cmd          Windows-side double-clickable wrapper
├── setup-bridge        WSL wrapper → Setup-Bridge.cmd (UAC elevation)
├── Setup-Bridge.cmd    Self-elevating wrapper for the portproxy script
├── docs/               Client and Codex plugin setup notes
├── mcp-up / mcp-down   WSL wrappers → mcp/start.sh / mcp/stop.sh
├── launcher/
│   ├── Launch-Chrome.ps1        Launches Chrome with CDP + project profile
│   └── Setup-WSL-Portproxy.ps1  netsh portproxy + Defender rule (admin)
├── mcp/
│   ├── package.json             @playwright/mcp pinned dependency
│   ├── start.sh / stop.sh       Long-running HTTP/SSE service
│   ├── client-config.json       Drop-in snippet for MCP clients
│   ├── test.sh                  Smoke test (initialize + browser_tabs + browser_snapshot)
│   └── demo-visible.sh          Visible-effect demo (opens tab, screenshots, closes)
├── plugins/chromemcp-browser/   Codex plugin wrapper + MCP config
└── scripts/install-codex-plugin.sh  Local Codex config installer
```

Every script is idempotent. Re-running `./chrome` while Chrome is already up does nothing. Re-running `./mcp-up` while the server is healthy reports its endpoint and exits zero. Re-running `./setup-bridge` refreshes the portproxy and firewall rule cleanly.

## Configuration

Sensible defaults; override with environment variables when starting `./mcp-up`:

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `8931` | MCP server listen port |
| `HOST` | `127.0.0.1` | MCP server bind interface |
| `CDP_ENDPOINT` | `http://<wsl-gateway>:9222` | Upstream Chrome CDP URL |

The Chrome side uses `9222` by default; the PowerShell launcher takes `-Port` to change that. If you change Chrome's port, run `Setup-WSL-Portproxy.ps1` directly with a matching `-Port`.

## Process supervision (optional)

By default `./mcp-up` runs the auth-proxy in a `setsid nohup …&` background — fine for foreground dev, but a crash leaves no auto-restart and the PID file lies. To make the MCP server self-healing across crashes and logouts, install it as a systemd user unit:

```bash
./mcp-enable        # install + start chromemcp.service
./mcp-status        # human-readable status
./mcp-down          # routes to 'systemctl --user stop chromemcp'
./mcp-up            # routes to 'systemctl --user start chromemcp'
./mcp-disable       # uninstall the unit; revert to ad-hoc mode
```

When the unit is installed, `./mcp-up` / `./mcp-down` automatically route through `systemctl --user`. Crashes restart in ≤ 10 s (3 s `RestartSec` + a couple of seconds of startup); `StartLimitBurst=5 / IntervalSec=60` prevents restart storms. Tail logs with `journalctl --user -u chromemcp -f`.

**Requirements for the supervised path:**

- systemd must be PID 1 inside the WSL distro. Add to `/etc/wsl.conf`:
  ```ini
  [boot]
  systemd=true
  ```
  Then run `wsl --shutdown` from a Windows PowerShell once. `systemctl --user is-system-running` should print `running` afterwards.
- `loginctl enable-linger $USER` is run by `./mcp-enable` so the service survives logout. If it warns about needing sudo, run `sudo loginctl enable-linger $USER` manually.

## Regression suite

```bash
./mcp-up                          # start the proxy
bash mcp/tests/run-all.sh         # ~21 s, runs all test_*.py against the live stack
```

10 test files exercising 18 of 23 advertised `@playwright/mcp` tools (~78%). Each test opens its own data-URL tab, asserts, then closes — they're self-contained and don't share mutable browser state. Coverage detail + uncovered tools with reasons: [`mcp/tests/COVERAGE.md`](mcp/tests/COVERAGE.md).

CI: [`.github/workflows/smoke.yml`](.github/workflows/smoke.yml) boots a headless Chromium on `ubuntu-latest`, starts the proxy with `MCP_NO_AUTH=1`, and runs `run-all.sh` on every PR + push to `main`.

## Metrics

`GET http://127.0.0.1:8931/metrics` returns Prometheus text exposition format. Unauthenticated (same posture as `/healthz`). Scrape with:

```yaml
- job_name: chromemcp
  scrape_interval: 15s
  static_configs:
    - targets: ['127.0.0.1:8931']
```

A starter Grafana dashboard is at [`docs/grafana-dashboard.json`](docs/grafana-dashboard.json) — tool call rate, p95 latency per tool, CDP reconnects, active sessions, /mcp status breakdown, error rate. Import via Grafana → Dashboards → Import → Upload JSON.

Full metric catalogue with cardinality notes and label semantics: [`docs/METRICS.md`](docs/METRICS.md).

## Logs

How to view logs depends on whether you're running supervised or ad-hoc:

| Mode | Log location | Tail |
|---|---|---|
| Supervised (`./mcp-enable`) | systemd journal | `./mcp-logs` (routes to `journalctl --user -u chromemcp`) |
| Ad-hoc (`./mcp-up` without enable) | `mcp/logs/playwright-mcp.log` + rotated `.1` .. `.MCP_LOG_KEEP` | `./mcp-logs` (file `tail -F`) |

`./mcp-logs` auto-detects the mode. Flags:

| Flag | Effect |
|---|---|
| `--all` / `-a` | (file mode) include rotated files in the tail |
| `--grep <pat>` / `-g` | grep across active + rotated (file) or filter journal output |
| `--file` / `--journal` | force a specific source |
| `--since "10 min ago"` | passed through to `journalctl` |

The proxy's own log lines respect `MCP_LOG_LEVEL` (default `INFO`, also `DEBUG`/`WARN`/`ERROR`) and `MCP_LOG_FORMAT` (`text` default, `json` for one-JSON-object-per-line shape — easy to pipe into `jq`).

In ad-hoc mode the proxy's stdio is redirected to `mcp/logs/playwright-mcp.log`. A sidecar bash rotator runs alongside the proxy, ticking every 30 s (override via `MCP_LOG_ROTATE_INTERVAL_SEC`). When the active log crosses **`MCP_LOG_MAX_MB`** (default `10`), it's rotated via copy-truncate:

```
playwright-mcp.log.5  ← dropped (becomes .6+, removed)
playwright-mcp.log.4  → .5
playwright-mcp.log.3  → .4
playwright-mcp.log.2  → .3
playwright-mcp.log.1  → .2
playwright-mcp.log    → copy to .1, truncate in place
```

The proxy keeps its append-mode FD on the same inode — Linux clamps the next write to offset 0 after the truncate, so no FD reopen is needed. We lose at most the bytes written during the in-flight `cp` window (the same trade-off `logrotate copytruncate` makes).

**Worst-case total directory size** = `(MCP_LOG_KEEP + 1) × MCP_LOG_MAX_MB` plus a small overshoot bounded by `(write_rate × rotate_interval)`. With defaults (`MAX_MB=10`, `KEEP=5`), that's ~60 MB at steady state for the typical Playwright MCP write rate. Tighten with:

```bash
MCP_LOG_MAX_MB=8 MCP_LOG_KEEP=4 ./mcp-up   # cap at ~40 MB
```

Supervised mode does **not** run the file rotator — systemd's journald handles its own size/age caps (`journalctl --user --vacuum-size=...` to tune).

## Reconnection across Chrome crashes

If Chrome on Windows crashes, you close it, or it restarts itself for an update, the `@playwright/mcp` upstream's CDP WebSocket dies and the upstream does not auto-reattach (verified by source inspection of `playwright-core@1.60.0`). ChromeMCP's auth proxy includes a watchdog that handles this:

- Every 10 s the proxy polls `<CDP_ENDPOINT>/json/version`. State and counters are visible at `GET http://127.0.0.1:8931/healthz`:
  ```json
  {"status":"ok","cdp":{"endpoint":"http://172.x.x.x:9222","healthy":true,"downSeconds":0,"reconnects":3}}
  ```
- When CDP goes unreachable, `/mcp` requests immediately return `HTTP 503` + a JSON-RPC error `code: -32099` with `data.downSeconds` so clients can surface a useful "retry in N seconds" message instead of hanging or seeing an opaque CDP socket error.
- After 60 s of CDP down, the proxy fires `./chrome` once to relaunch Chrome on the Windows side (skippable with `MCP_NO_AUTO_CHROME=1`).
- On CDP recovery, the proxy restarts the `@playwright/mcp` child cleanly so it rebuilds the CDP socket against the new Chrome. The auth-proxy itself stays up — public-port HTTP connections from clients are preserved.
- If CDP stays unreachable for 180 s, the proxy exits non-zero so the supervisor (`systemd`, if enabled per *Process supervision*) restarts the whole stack.

Knobs (all optional, sensible defaults):

| Env var                       | Default | Effect |
|-------------------------------|---------|--------|
| `MCP_CDP_PROBE_INTERVAL_MS`   | `10000` | Time between CDP health probes |
| `MCP_CDP_RELAUNCH_AFTER_MS`   | `60000` | After this much CDP downtime, trigger `./chrome` once |
| `MCP_CDP_BAIL_AFTER_MS`       | `180000`| After this much CDP downtime, exit(1) to force supervisor restart |
| `MCP_NO_AUTO_CHROME=1`        | unset   | Suppress the relaunch trigger |
| `MCP_NO_WATCHDOG=1`           | unset   | Disable the watchdog entirely |

## Bridge self-healing across reboots

WSL2's vEthernet gateway IP can change after a Windows reboot, a `wsl --shutdown`, or a Hyper-V reset. When that happens, the bridge that was installed against the *old* IP no longer points anywhere useful — but ChromeMCP detects and recovers automatically.

What `./mcp-up` does on each invocation:

1. Probes Chrome's CDP through the current bridge.
2. If that fails, runs `./chrome` to auto-launch Chrome on the Windows side.
3. If CDP is *still* unreachable, queries the Windows-side `netsh interface portproxy` state and compares its listenaddress to the current WSL gateway IP.
4. **Drift detected** (listenaddress ≠ current gateway): runs `Setup-Bridge.cmd /refresh`, which deletes any stale `netsh portproxy` entries on port 9222 and re-creates a single entry pinned to the current gateway. Approve the UAC prompt once and the bridge is back.
5. **No portproxy entry at all**: runs the first-time `Setup-Bridge.cmd` install path.
6. On success, `./mcp-up` prints `Bridge OK at <IP>:9222` so you can see at a glance which IP the bridge is pinned to.

For an explicit health check without starting the MCP server, run:

```bash
./bridge-check          # report only; exits 0 (healthy), 1 (drift), 2 (missing), 3 (interop broken)
./bridge-check --fix    # report and, on drift, trigger ./setup-bridge /refresh
```

The refresh path requires the UAC prompt because modifying `netsh portproxy` and Defender firewall rules is admin-only on Windows. There's no way to avoid that prompt for the actual change — but the prompt only appears when drift or first-time install is needed, not on every `./mcp-up`.

## Troubleshooting

**`ERROR: Chrome CDP not reachable at http://172.x.x.x:9222`** — `./mcp-up` already tries to auto-launch Chrome and auto-install or auto-refresh the bridge. If you still see this error, either you denied/ignored the UAC prompt, or you have `MCP_NO_AUTO_CHROME` / `MCP_NO_AUTO_BRIDGE` set in your environment. Run `./bridge-check` to see whether the bridge is in `drift` / `missing` / `ok` state, then re-run `./mcp-up` and approve the UAC prompt, or run `./chrome` and `./setup-bridge` explicitly.

**Bridge install reports "Could not find vEthernet (WSL) adapter."** — WSL2 isn't currently running on the Windows side. Open any WSL shell first, then re-run `./setup-bridge`.

**MCP server logs say "browser already in use" or won't connect.** — A previous Playwright MCP process is still attached to Chrome. Run `./mcp-down`, wait a moment, then `./mcp-up`.

**Want to nuke the profile and start fresh?** — Close Chrome, then on Windows delete `%LOCALAPPDATA%\ChromeMCP\Profile`. Next `./chrome` will recreate it.

## License

[MIT](LICENSE) © 2026 [Rizonetech (Pty) Ltd.](https://rizonetech.com)
