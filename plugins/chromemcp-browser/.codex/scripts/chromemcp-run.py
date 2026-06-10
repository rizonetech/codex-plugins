#!/usr/bin/env python3
"""ChromeMCP evidence wrapper — delegates to the installed 'chromemcp' CLI."""

import os
import subprocess
import sys


def main() -> int:
    args = sys.argv[1:] or ["test"]
    chromemcp = os.path.expanduser("~/.local/bin/chromemcp")
    if not os.path.isfile(chromemcp):
        # Fall back to PATH lookup.
        chromemcp = "chromemcp"
    return subprocess.call([chromemcp] + args)


if __name__ == "__main__":
    raise SystemExit(main())
