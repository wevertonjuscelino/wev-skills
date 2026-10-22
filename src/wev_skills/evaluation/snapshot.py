"""A file snapshot of a workspace and a unified diff between two of them, with no git.

The agent controls the workspace, so the snapshot only ever opens regular files (never a
FIFO, device or link), reads a bounded number of bytes and stops at a bounded file count."""

from __future__ import annotations

import difflib
import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_BYTES = 100_000
"""A larger file is compared by a digest of its first bytes plus its size, and summarized."""
MAX_FILES = 5000
MAX_TOTAL_BYTES = 20_000_000
"""Most bytes one snapshot reads in all."""
TRUNCATED_NOTE = "[snapshot truncated: files beyond the cap were not compared]\n"


@dataclass(frozen=True)
class Entry:
    data: bytes  # the content, or a digest when ``big``
    big: bool
    size: int


@dataclass(frozen=True)
class Snapshot:
    files: dict[str, Entry] = field(default_factory=dict)
    truncated: bool = False


def _read(path: Path) -> Entry | None:
    """The entry of a regular file, or ``None``; opened without following links or blocking."""
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            return None
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return Entry(hashlib.sha256(data).digest(), True, info.st_size)
    return Entry(data, False, len(data))


def take(workspace: Path) -> Snapshot:
    """Every regular file outside ``.git``, in sorted order, up to the file and byte caps."""
    found: dict[str, Entry] = {}
    total = 0
    for folder, dirs, names in os.walk(workspace):
        dirs[:] = sorted(d for d in dirs if d != ".git")
        for name in sorted(names):
            if name == ".git":
                continue
            if len(found) >= MAX_FILES:
                return Snapshot(found, True)
            path = Path(folder) / name
            entry = _read(path)
            if entry is not None:
                found[path.relative_to(workspace).as_posix()] = entry
                total += min(entry.size, MAX_FILE_BYTES + 1)
                if total > MAX_TOTAL_BYTES:
                    return Snapshot(found, True)
    return Snapshot(found)


def _lines(data: bytes) -> list[str]:
    return data.decode("utf-8", errors="replace").splitlines(keepends=True)


def _file_diff(name: str, old: Entry | None, new: Entry | None) -> list[str]:
    if any(x is not None and (x.big or b"\0" in x.data) for x in (old, new)):
        sizes = ", ".join(f"{x.size} bytes" for x in (old, new) if x is not None)
        return [f"Binary or large file changed: {name} ({sizes})\n"]
    old_lines = _lines(old.data) if old else []
    new_lines = _lines(new.data) if new else []
    return list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            f"a/{name}" if old else "/dev/null",
            f"b/{name}" if new else "/dev/null",
        )  # fmt: skip
    )


def diff(before: Snapshot, after: Snapshot) -> str:
    """Unified diff of what changed, new and deleted files included. A file missing from a
    snapshot that hit a cap is unknown, not deleted or new, and is left out."""
    out: list[str] = []
    for name in sorted(before.files.keys() | after.files.keys()):
        old, new = before.files.get(name), after.files.get(name)
        if old == new or (old is None and before.truncated) or (new is None and after.truncated):
            continue
        out.extend(_file_diff(name, old, new))
    if before.truncated or after.truncated:
        out.append(TRUNCATED_NOTE)
    return "".join(out)
