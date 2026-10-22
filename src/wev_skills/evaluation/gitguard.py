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


def shared_git_dir(runner: Runner, root: Path) -> Path:
    out = run_git(runner, root, "rev-parse", "--git-common-dir").stdout.strip()
    return (root / out).resolve()


def _entry(digest: Any, path: Path, name: str) -> None:
    try:
        info = os.lstat(path)
    except OSError:
        digest.update(f"{name}\0missing\0".encode())
        return
    if stat.S_ISLNK(info.st_mode):
        digest.update(f"{name}\0link\0{os.readlink(path)}\0".encode())
    elif stat.S_ISREG(info.st_mode):
        digest.update(f"{name}\0file\0".encode() + path.read_bytes() + b"\0")
    else:
        digest.update(f"{name}\0other\0{stat.S_IFMT(info.st_mode)}\0".encode())


def fingerprint(gitdir: Path) -> str:
    """Names and bytes of the watched files and trees; symlinks are recorded, not followed."""
    digest = hashlib.sha256()
    for name in WATCHED_FILES:
        _entry(digest, gitdir / name, name)
    for top in WATCHED_DIRS:
        base = gitdir / top
        _entry(digest, base, top)
        for folder, dirs, names in os.walk(base):
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
        if fingerprint(gitdir) != before:
            raise GitTampered("git_config_changed", i18n.t("evaluation.scoring.git_config_changed"))

    return check
