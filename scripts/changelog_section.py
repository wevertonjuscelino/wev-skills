#!/usr/bin/env python3
"""Print the body of one version's section of CHANGELOG.md.

Usage: ``changelog_section.py VERSION [CHANGELOG]``. Standard library only. The section runs from
the line after ``## [VERSION]`` to the next ``## [`` heading or the link definitions at the end of
the file. Exits 1 when the section is missing or empty and 2 on a usage error.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
HEADING = "## ["
LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s+\S+")


def section(text: str, version: str) -> str | None:
    """Return the stripped body of ``## [version]``, or ``None`` when it is absent or empty."""
    wanted = f"{HEADING}{version}]"
    body: list[str] = []
    inside = False
    for line in text.splitlines():
        if inside and (line.startswith(HEADING) or LINK_DEFINITION.match(line)):
            break
        if inside:
            body.append(line)
        elif line == wanted or line.startswith(wanted + " "):
            inside = True
    result = "\n".join(body).strip()
    return result or None


def main(argv: list[str]) -> int:
    args = argv[1:]
    if len(args) not in (1, 2):
        print("usage: changelog_section.py VERSION [CHANGELOG]", file=sys.stderr)
        return 2
    path = Path(args[1]) if len(args) == 2 else DEFAULT_CHANGELOG
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        print(f"changelog_section: cannot read {path}: {error}", file=sys.stderr)
        return 1
    found = section(text, args[0])
    if found is None:
        print(f"changelog_section: no non-empty section for {args[0]} in {path}", file=sys.stderr)
        return 1
    print(found)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
