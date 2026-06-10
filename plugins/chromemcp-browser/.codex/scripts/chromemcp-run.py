#!/usr/bin/env python3
"""ChromeMCP evidence wrapper — delegates to the installed safe_runner via module invocation."""

import os
import subprocess
import sys


def main() -> int:
    chromemcp_home = os.environ.get("CHROMEMCP_HOME", os.path.expanduser("~/ChromeMCP"))
    safe_runner = os.path.join(chromemcp_home, "mcp", "client", "safe_runner.py")

    if not os.path.isfile(safe_runner):
        print(
            f"chromemcp-run: safe_runner.py not found at {safe_runner}\n"
            "Install ChromeMCP:\n"
            "  git clone https://github.com/rizonetech/ChromeMCP\n"
            "  bash scripts/install.sh --from-source",
            file=sys.stderr,
        )
        return 127

    env = dict(os.environ)
    env["PYTHONPATH"] = chromemcp_home

    return subprocess.call(
        [sys.executable, "-m", "mcp.client.safe_runner"] + sys.argv[1:],
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
