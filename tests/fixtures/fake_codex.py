#!/usr/bin/env python3
"""Stand-in for the ``codex`` CLI: records argv, fails on demand. Never touches ~/.codex.

FAKE_CODEX_LOG: file that receives one JSON argv per line.
FAKE_CODEX_FAIL: argv prefixes as words, separated by "|" (e.g. "plugin add|plugin remove");
a call matching any of them exits 1.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    args = sys.argv[1:]
    with open(os.environ["FAKE_CODEX_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(args) + "\n")
    prefixes = [p.split() for p in os.environ.get("FAKE_CODEX_FAIL", "").split("|") if p.strip()]
    if any(args[: len(prefix)] == prefix for prefix in prefixes):
        sys.stderr.write("fake codex: failing on demand\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
