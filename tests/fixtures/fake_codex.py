#!/usr/bin/env python3
"""Stand-in for the ``codex`` CLI: records argv, fails on demand. Never touches ~/.codex.

FAKE_CODEX_LOG: file that receives one JSON argv per line.
FAKE_CODEX_FAIL: argv prefix as words (e.g. "plugin add"); a matching call exits 1.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    args = sys.argv[1:]
    with open(os.environ["FAKE_CODEX_LOG"], "a", encoding="utf-8") as log:
        log.write(json.dumps(args) + "\n")
    fail = os.environ.get("FAKE_CODEX_FAIL", "").split()
    if fail and args[: len(fail)] == fail:
        sys.stderr.write("fake codex: failing on demand\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
