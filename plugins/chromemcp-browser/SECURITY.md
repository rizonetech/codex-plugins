# Security policy

## Supported versions

ChromeMCP is in active development and has not yet cut a stable release.
The supported version is **`main`**. Security fixes are applied to `main`
and rolled into the next release.

| Version | Supported |
|---------|-----------|
| `main`  | ✅        |
| `0.1.0` | ⚠ pre-release; upgrade to `main` |
| < 0.1.0 | ❌        |

## Reporting a vulnerability

**Please do not open a public issue for security reports.** Instead, use
one of:

1. **GitHub Private Vulnerability Reporting** — preferred — at
   [`Security` → `Report a vulnerability`](https://github.com/rizonetech/codex-plugins/security) on this repo.
2. **Email** — `security@rizonetech.com`. PGP welcome but not required.

What we ask of you:

- Give us a reasonable description of the issue with reproduction steps.
- Allow up to **5 business days** for acknowledgement and up to **30 days**
  for a fix on critical issues (`CVSS ≥ 7.0`). Lower-severity issues may
  take longer.
- Practice **coordinated disclosure**: please do not publish details
  publicly until a fix is released, or until 90 days have elapsed,
  whichever comes first.

Out of scope:

- Bugs in **Chrome itself** — report to <https://crbug.com/>.
- Bugs in **`@playwright/mcp`** upstream — report to
  <https://github.com/microsoft/playwright-mcp/security>.
- Bugs in **Playwright core** — report to
  <https://github.com/microsoft/playwright/security>.
- Issues that require an attacker who already has root/Administrator on
  the affected machine.

## Threat model

ChromeMCP is designed for **a single trusted developer running on their
own machine.** Its threat model is calibrated for that case:

### What ChromeMCP defends against

- **Casual same-host processes** — rogue install scripts (`npm install`,
  `pip install`), telemetry agents, sibling containers sharing host
  loopback, browser extensions executing fetch — cannot drive a
  signed-in Chrome through the MCP endpoint without supplying the
  per-machine bearer token at `~/.config/chromemcp/token`. The token is
  mode `0600` (owner-readable only) and is unique to the install.
- **Network attackers** — the MCP server listens only on loopback
  (`127.0.0.1:8931`). The Windows-side bridge exposes Chrome's CDP port
  to the WSL distro subnet only, gated by a Defender firewall rule that
  excludes the public internet.
- **WSL guests from other distros** — the firewall rule on the Windows
  host pins `RemoteAddress` to the active WSL distro's subnet (see
  [`launcher/Setup-WSL-Portproxy.ps1`](launcher/Setup-WSL-Portproxy.ps1)).

### What ChromeMCP does NOT defend against

- **Co-resident attackers with shell access on the same machine.** A
  user logged in as the same UID can read the token file at
  `~/.config/chromemcp/token` and authenticate as a legitimate client.
  This is consistent with the Unix permission model — the token is just
  another file owned by you.
- **Co-resident processes scanning loopback for the upstream port.** The
  auth proxy at `127.0.0.1:8931` validates bearer tokens, but the
  `@playwright/mcp` server it wraps also listens on `127.0.0.1:8932`
  with **no authentication of its own**. A determined attacker on the
  same host could connect to port 8932 directly and bypass the proxy.
  This is a known limitation: `@playwright/mcp` does not support
  Unix-domain sockets, and TCP loopback ports are reachable to any
  process running as any UID on the machine.

  *Mitigation:* if your threat model includes co-resident attackers,
  do not run ChromeMCP. Multi-tenant hosts are an explicit non-goal
  (see [`todo/production-readiness.md`](todo/production-readiness.md#what-chromemcp-isnt-going-to-be-and-thats-fine)).

- **A user who copies the token to another machine.** The token is a
  shared secret — anyone who can read it can use it. Treat it like an
  SSH private key. Rotate it (`./mcp-token --rotate && ./mcp-down &&
  ./mcp-up`) if you suspect leak.

- **Chrome itself.** CDP gives full control over the browser: cookies,
  saved passwords, navigation history, the DOM of every signed-in tab.
  If you grant an MCP client access to your ChromeMCP server, you are
  granting it access to all of that. Audit the clients you trust.

### Recommended deployment posture

- **Do** run ChromeMCP on a personal dev machine where you control which
  processes run as your UID.
- **Do** rotate the auth token if you share screen recordings, paste
  config snippets in public, or move between machines.
- **Don't** run ChromeMCP on a CI runner, a shared dev VM, a jumpbox,
  or any host where other people have shell access as your UID. The
  threat model is single-user dev box.
- **Don't** set `MCP_NO_AUTH=1` outside of one-off local debugging.
  The proxy logs a warning on every request when this is set, but the
  warning is not a substitute for auth.

## Bearer token storage and rotation

- **Location:** `$XDG_CONFIG_HOME/chromemcp/token` (default
  `~/.config/chromemcp/token`).
- **Format:** 64-character lowercase hex (256 bits of `crypto.randomBytes`).
- **Permissions:** mode `0600`, parent directory mode `0700`.
- **Auto-generation:** the first `./mcp-up` (or first `./mcp-token`)
  creates the token if absent.
- **Rotation:** `./mcp-token --rotate && ./mcp-down && ./mcp-up`. All
  connected clients must be reconfigured with the new token.
- **Override at runtime:** set `MCP_AUTH_TOKEN=...` in the server's env
  to use a token that's not persisted to disk.
