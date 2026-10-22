"""A file snapshot of a workspace and a unified diff between two of them, with no git."""

from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path

MAX_FILE_BYTES = 100_000
"""A larger file is compared by digest and summarized by name in the diff."""
MAX_FILES = 5000
Snapshot = dict[str, tuple[bytes, bool]]
"""Per relative path: the content (a digest when the file is large) and whether it is large."""


def take(workspace: Path) -> Snapshot:
    """Every regular file outside ``.git``; links and unreadable files are left out."""
    found: Snapshot = {}
    for folder, dirs, names in os.walk(workspace):
        dirs[:] = [d for d in dirs if d != ".git" and not (Path(folder) / d).is_symlink()]
        for name in names:
            path = Path(folder) / name
            if name == ".git" or path.is_symlink() or len(found) >= MAX_FILES:
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            big = len(data) > MAX_FILE_BYTES
            found[path.relative_to(workspace).as_posix()] = (
                (hashlib.sha256(data).digest(), True) if big else (data, False)
            )
    return found


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8", errors="replace").splitlines(keepends=True)


def diff(before: Snapshot, after: Snapshot) -> str:
    """Unified diff of what changed, new and deleted files included."""
    out: list[str] = []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if old == new:
            continue
        if any(x is not None and (x[1] or b"\0" in x[0]) for x in (old, new)):
            out.append(f"Binary or large file changed: {name}\n")
            continue
        old_lines = _lines(old[0]) if old else []
        new_lines = _lines(new[0]) if new else []
        out.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                f"a/{name}" if old else "/dev/null",
                f"b/{name}" if new else "/dev/null",
            )  # fmt: skip
        )
    return "".join(out)
