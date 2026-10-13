"""Small filesystem helpers shared by modules that persist JSON on disk."""

from __future__ import annotations

import errno
import fcntl
import os
import stat
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import StateConflict

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
LOCK_TIMEOUT_SECONDS = 30.0
LOCK_POLL_SECONDS = 0.02
IGNORE_FILE = ".gitignore"
IGNORE_EVERYTHING = "*\n"


def _missing_dirs(path: Path) -> tuple[Path, ...]:
    """``path`` and its ancestors that do not exist yet, outermost first."""
    missing: list[Path] = []
    current = path
    while not os.path.lexists(current):
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    return tuple(reversed(missing))


def ensure_private_dir(path: Path) -> Path:
    """Create ``path`` and any missing parents, each readable only by the current user.

    ``mkdir(parents=True, mode=...)`` gives the mode to the leaf only and leaves the
    parents to the umask, so every missing directory is created one by one here.
    Directories that already exist keep the mode they have.
    """
    for directory in _missing_dirs(path):
        try:
            os.mkdir(directory, PRIVATE_DIR_MODE)
        except FileExistsError:
            continue  # another process created it first: it is not ours to change
        os.chmod(directory, PRIVATE_DIR_MODE)  # the umask may have removed owner bits
    if not path.is_dir():
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(path))
    return path


def atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` so readers see either the old file or the new one, never a partial write."""
    ensure_private_dir(path.parent)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, PRIVATE_FILE_MODE)
        os.replace(tmp_name, path)
    except BaseException:
        _remove_quietly(tmp_name)
        raise


def append_line(path: Path, line: str) -> None:
    """Append one line under an exclusive lock so concurrent writers do not interleave."""
    ensure_private_dir(path.parent)
    with locked(path), open(path, "a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, PRIVATE_FILE_MODE)


def ensure_ignored_dir(path: Path) -> Path:
    """Create a private directory that git ignores entirely (a ``.gitignore`` holding ``*``).

    The file is written only when missing, so a person's own version is kept.
    """
    ensure_private_dir(path)
    ignore = path / IGNORE_FILE
    if not ignore.exists():
        atomic_write_text(ignore, IGNORE_EVERYTHING)
    return path


def _open_lock_file(lock_path: Path) -> int:
    """Open (creating it private) the lock file and tighten one of ours that is too open."""
    descriptor = os.open(lock_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, PRIVATE_FILE_MODE)
    try:
        status = os.fstat(descriptor)
        is_too_open = stat.S_IMODE(status.st_mode) & ~PRIVATE_FILE_MODE != 0
        if is_too_open and status.st_uid == os.geteuid():
            os.fchmod(descriptor, PRIVATE_FILE_MODE)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _acquire(descriptor: int, path: Path, timeout: float) -> None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                message = i18n.t("state.error.lock_timeout", path=str(path), seconds=timeout)
                raise StateConflict(
                    "lock_timeout", message, {"path": str(path), "timeout_seconds": timeout}
                ) from None
            time.sleep(LOCK_POLL_SECONDS)


@contextmanager
def locked(path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold an exclusive advisory lock tied to ``path`` (POSIX only) for the block.

    Waits at most ``timeout`` seconds for another process to release it, then raises
    ``StateConflict`` (``lock_timeout``) instead of hanging forever.
    """
    ensure_private_dir(path.parent)
    descriptor = _open_lock_file(path.with_name(f".{path.name}.lock"))
    try:
        _acquire(descriptor, path, timeout)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _remove_quietly(name: str) -> None:
    try:
        os.unlink(name)
    except FileNotFoundError:
        return
