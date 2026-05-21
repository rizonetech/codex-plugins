# Pinning Chrome to a known-good version on Windows

Chrome auto-updates by default on Windows. ChromeMCP attaches to the
running Chrome via CDP, so a breaking CDP change between two
`chrome.exe` releases can surface as opaque tool-call errors in MCP
clients without any obvious cause.

This document covers two strategies:

1. **Suppress updates for a window** — keep your current Chrome for
   long enough to ship around a known-bad release.
2. **Pin to a specific major version** — refuse to update past a chosen
   version until you explicitly bump the policy.

Both require Chrome on Windows. On WSL there's no Chrome to pin.

## Quick decision matrix

| You want… | Use |
|---|---|
| Buy time during a regression hunt | `UpdatesSuppressedStartTime` + `UpdatesSuppressedDurationMin` |
| Stay on a specific major across reboots | `TargetVersionPrefix` |
| Disable Google Update entirely (advanced) | `UpdateDefault=0` (not recommended) |

## Where to apply policies

Three equivalent places, choose the one that fits your environment:

1. **Group Policy Editor** (`gpedit.msc`) — Computer Configuration →
   Administrative Templates → Google → Google Update → Applications →
   Google Chrome. Requires the ADMX template; download from
   <https://support.google.com/chrome/a/answer/187202>.
2. **Registry directly** — write the values under
   `HKLM\SOFTWARE\Policies\Google\Update`.
3. **Intune / SCCM** — push the same registry values to managed fleets.

This doc uses **registry paths** for portability. Use `regedit.exe` or a
`.reg` file run from an elevated PowerShell to apply them.

## Strategy 1: suppress updates for a window

Use this when you've verified a specific Chrome works with ChromeMCP and
want to hold there for a few days while a regression is being fixed
upstream.

```reg
Windows Registry Editor Version 5.00

[HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Google\Update]
"UpdatesSuppressedStartTime"="14:00"
"UpdatesSuppressedDurationMin"=dword:00000a8c
```

- `UpdatesSuppressedStartTime` — local-time HH:MM when the suppression
  window starts each day. Example `14:00` = 2 PM.
- `UpdatesSuppressedDurationMin` — duration of the window in minutes,
  as a `DWORD`. `0xa8c` = 2700 = 45 hours, so a single window covers
  ~2 days from each daily start.
- The window resets daily at `UpdatesSuppressedStartTime`. To extend
  past 2 days you have to bump the duration; the policy doesn't cover
  arbitrary date ranges natively.

After importing: open `chrome://policy/`, click *Reload policies*,
confirm both fields show up with the expected values.

## Strategy 2: pin to a specific major version

Use this when you've completed a release-cycle verification and want
Chrome to stay there until ChromeMCP is re-tested against the next
major.

```reg
Windows Registry Editor Version 5.00

[HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Google\Update\{8A69D345-D564-463C-AFF1-A69D9E530F96}]
"TargetVersionPrefix"="148."
```

- The GUID `{8A69D345-D564-463C-AFF1-A69D9E530F96}` is Chrome's
  product code under Google Update. Don't change it.
- `TargetVersionPrefix` is a **string-prefix match**, not a comparison:
  - `"148."` permits any `148.x.y.z` but blocks `149+`.
  - `"148.0.7778."` permits any `148.0.7778.<patch>` only.
  - `"148.0.7778.98"` pins to exactly that build (no auto-rollouts).
- After setting this, Chrome will downgrade if it's *above* the prefix
  on next update check. If you need to allow that downgrade, set
  `RollbackToTargetVersion` = `1` in the same key as well.

Verify in `chrome://policy/` — look for `TargetVersionPrefix` under
*Google Update Policies*.

## Strategy 3: disable Google Update (not recommended)

```reg
[HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Google\Update]
"UpdateDefault"=dword:00000000
```

This stops updates for **all** Google products. Chrome will accumulate
security fixes that don't ship — a real risk for a browser holding
signed-in sessions. Prefer `TargetVersionPrefix` if your goal is
"controlled upgrades."

## Verifying the pin took effect

1. Open `chrome://policy/` and click *Reload policies*.
2. Confirm `UpdatesSuppressedStartTime` / `UpdatesSuppressedDurationMin`
   / `TargetVersionPrefix` appear with the values you set.
3. Open `chrome://settings/help` and watch the update check status.
   *Suspended* / *Update paused* messages indicate the policy is
   active.

## What ChromeMCP checks

`mcp/start.sh` queries CDP `/json/version` after the bridge is up,
parses the major version, and prints one of:

```
Chrome   : Chrome/148.0.7778.98 (supported range: 140-150)
```

or, if outside `[MCP_CHROME_MIN_MAJOR, MCP_CHROME_MAX_MAJOR]`:

```
Chrome   : Chrome/153.0.x.x
  WARN: Chrome major 153 is outside the verified range 140-150.
  Tool calls may behave unexpectedly if upstream CDP changed. Set
  MCP_CHROME_MIN_MAJOR / MCP_CHROME_MAX_MAJOR to silence this warning
  once you've verified the suite at this version, or see
  docs/chrome-pinning.md for how to pin Chrome to a known-good major
  on Windows Enterprise.
```

The warning never blocks startup. If the version is out of the verified
range AND something does break, you have at least one specific signal
to correlate against (`journalctl --user -u chromemcp` or
`mcp/logs/playwright-mcp.log`).

## When ChromeMCP's range moves

We bump `MCP_CHROME_MIN_MAJOR` / `MCP_CHROME_MAX_MAJOR` in
`mcp/start.sh` when:

1. A new Chrome major ships AND the smoke suite still passes against it
   (`bash mcp/tests/run-all.sh` — see [`mcp/tests/COVERAGE.md`](../mcp/tests/COVERAGE.md)).
2. Upstream [Playwright](https://github.com/microsoft/playwright/releases)
   documents support for the new major.
3. We record the new "verified-working" version in `CHANGELOG.md`.

To follow Chrome releases, subscribe to
<https://chromereleases.googleblog.com/> (RSS available) or watch the
[playwright-mcp releases page](https://github.com/microsoft/playwright-mcp/releases)
— upstream tends to bump its supported range in the release notes.
