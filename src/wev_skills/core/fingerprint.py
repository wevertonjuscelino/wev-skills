"""A hash of the working tree, used to tell whether anything changed between two moments.

Inside a git repository it covers the commit, the status, staged and unstaged diffs and the
size and modification time of untracked files. Outside one it falls back to a bounded walk
of the directory. Excluded paths (the state directory) never count: the engine's own
records must not look like work.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence

from wev_skills.core.ports import Runner

GIT_TIMEOUT_SECONDS = 30.0
STATUS_ARGV = ("git", "status", "--porcelain")
HEAD_ARGV = ("git", "rev-parse", "HEAD")
DIFF_ARGVS = (("git", "diff"), ("git", "diff", "--cached"))
UNTRACKED_ARGV = ("git", "ls-files", "--others", "--exclude-standard")
FS_PREFIX = "fs:"
NO_TREE = "fs:unreadable"
MAX_WALK_FILES = 20000
SKIPPED_DIRECTORIES = frozenset({".git"})
_STATUS_PREFIX_LEN = 3
_QUOTE = '"'


def _git(runner: Runner, argv: Sequence[str], cwd: str) -> str | None:
    try:
        result = runner.run(tuple(argv), cwd, GIT_TIMEOUT_SECONDS, None)
    except OSError:
        return None
    if result.timed_out or result.exit_code != 0:
        return None
    return result.stdout


def _prefixes(exclude: Sequence[str]) -> tuple[str, ...]:
    cleaned = (os.path.normpath(path) for path in exclude if path)
    return tuple(path for path in cleaned if path not in (".", "") and not os.path.isabs(path))


def _excluded(path: str, prefixes: Sequence[str]) -> bool:
    plain = os.path.normpath(path.strip().strip(_QUOTE))
    return any(plain == prefix or plain.startswith(prefix + os.sep) for prefix in prefixes)


def _kept_status(porcelain: str, prefixes: Sequence[str]) -> str:
    lines = porcelain.splitlines()
    return "\n".join(line for line in lines if not _excluded(line[_STATUS_PREFIX_LEN:], prefixes))


def _stat_line(root: str, relative: str) -> str:
    try:
        info = os.lstat(os.path.join(root, relative))
    except OSError:
        return f"{relative}:gone"
    return f"{relative}:{info.st_size}:{info.st_mtime_ns}"


def _untracked(listing: str, cwd: str, prefixes: Sequence[str]) -> str:
    names = sorted(name for name in listing.splitlines() if name and not _excluded(name, prefixes))
    return "\n".join(_stat_line(cwd, name) for name in names)


def _diff_argv(base: Sequence[str], prefixes: Sequence[str]) -> tuple[str, ...]:
    if not prefixes:
        return tuple(base)
    return (*base, "--", ".", *(f":(exclude){prefix}" for prefix in prefixes))


def _walk_fingerprint(cwd: str, prefixes: Sequence[str]) -> str:
    """Hash of (path, size, mtime) for up to ``MAX_WALK_FILES`` files under ``cwd``."""
    digest = hashlib.sha256()
    seen = 0
    for directory, subdirs, files in os.walk(cwd):
        relative_dir = os.path.relpath(directory, cwd)
        subdirs[:] = sorted(
            name
            for name in subdirs
            if name not in SKIPPED_DIRECTORIES
            and not _excluded(os.path.join(relative_dir, name), prefixes)
        )
        for name in sorted(files):
            relative = os.path.normpath(os.path.join(relative_dir, name))
            if _excluded(relative, prefixes):
                continue
            digest.update(_stat_line(cwd, relative).encode("utf-8", errors="replace") + b"\0")
            seen += 1
            if seen >= MAX_WALK_FILES:
                return FS_PREFIX + digest.hexdigest()
    return FS_PREFIX + digest.hexdigest()


def head_commit(runner: Runner, cwd: str) -> str:
    """The commit ``HEAD`` names at ``cwd``; empty outside a repository or before a commit."""
    return (_git(runner, HEAD_ARGV, cwd) or "").strip()


def tree_fingerprint(runner: Runner, cwd: str, exclude: Sequence[str] = ()) -> str:
    """Hash of the tree at ``cwd``; ``exclude`` lists paths relative to ``cwd`` to ignore."""
    prefixes = _prefixes(exclude)
    status = _git(runner, STATUS_ARGV, cwd)
    if status is None:
        return _walk_fingerprint(cwd, prefixes) if os.path.isdir(cwd) else NO_TREE
    parts = [_git(runner, HEAD_ARGV, cwd) or "", _kept_status(status, prefixes)]
    parts.extend(_git(runner, _diff_argv(argv, prefixes), cwd) or "" for argv in DIFF_ARGVS)
    parts.append(_untracked(_git(runner, UNTRACKED_ARGV, cwd) or "", cwd, prefixes))
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", errors="replace"))
        digest.update(b"\0")
    return digest.hexdigest()
