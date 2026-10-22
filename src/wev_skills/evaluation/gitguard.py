"""Detect a change to the shared git directory (config, hooks, info) while an agent ran."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core.ports import Runner
from wev_skills.evaluation.workspace import GitTampered, run_git

WATCHED_FILES = ("config", "config.worktree")
WATCHED_DIRS = ("hooks", "info")
MAX_READ_BYTES = 1_000_000
"""A file is hashed up to this many bytes; its size and mode are always recorded."""


def shared_git_dir(runner: Runner, root: Path) -> Path:
    out = run_git(runner, root, "rev-parse", "--git-common-dir").stdout.strip()
    return (root / out).resolve()


def _digest(path: Path) -> tuple[str, int]:
    """Digest of at most ``MAX_READ_BYTES`` of a regular file, and its size; never follows links."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("not a regular file")
        return hashlib.sha256(handle.read(MAX_READ_BYTES)).hexdigest(), info.st_size


def _entry(digest: Any, path: Path, name: str) -> None:
    """Name, kind, mode bits and content of one entry; any error propagates (fail closed)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        digest.update(f"{name}\0missing\0".encode())
        return
    mode = stat.S_IMODE(info.st_mode)
    if stat.S_ISLNK(info.st_mode):
        detail = f"link\0{os.readlink(path)}"
    elif stat.S_ISREG(info.st_mode):
        content, size = _digest(path)
        detail = f"file\0{content}\0{size}"
    else:
        detail = f"other\0{stat.S_IFMT(info.st_mode)}"
    digest.update(f"{name}\0{mode:o}\0{detail}\0".encode())


def _raise(error: OSError) -> None:
    raise error


def fingerprint(gitdir: Path) -> str:
    """Names, modes and content of the watched files and trees; symlinks are recorded, not
    followed. Any error is raised, never skipped."""
    digest = hashlib.sha256()
    for name in WATCHED_FILES:
        _entry(digest, gitdir / name, name)
    for top in WATCHED_DIRS:
        base = gitdir / top
        _entry(digest, base, top)
        for folder, dirs, names in os.walk(base, onerror=_raise):
            dirs.sort()
            for item in (*dirs, *sorted(names)):
                path = Path(folder) / item
                _entry(digest, path, path.relative_to(gitdir).as_posix())
    return digest.hexdigest()


def tamper_guard(runner: Runner, root: Path) -> Callable[[], None]:
    """A check that raises ``GitTampered`` when the watched part of the git dir changed."""
    gitdir = shared_git_dir(runner, root)
    before = fingerprint(gitdir)

    def check() -> None:
        try:
            now: str | None = fingerprint(gitdir)
        except Exception:  # unreadable, vanished or oversized: counts as a change
            now = None
        if now != before:
            raise GitTampered("git_config_changed", i18n.t("evaluation.scoring.git_config_changed"))

    return check
