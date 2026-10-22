#!/usr/bin/env python3
"""Stand-in for ``claude -p``: appends argv, cwd and environment as one JSON line to
$FAKE_LOG, prints $FAKE_CLAUDE_STDOUT (default {"result": "done"}) and $FAKE_CLAUDE_STDERR,
sleeps $FAKE_CLAUDE_SLEEP and exits with $FAKE_CLAUDE_EXIT."""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> int:
    with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as log:
        call = {"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)}
        log.write(json.dumps(call) + "\n")
    time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP", "0")))
    sys.stdout.write(os.environ.get("FAKE_CLAUDE_STDOUT", '{"result": "done"}'))
    sys.stderr.write(os.environ.get("FAKE_CLAUDE_STDERR", ""))
    return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
