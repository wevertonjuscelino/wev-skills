"""Path confinement: keep file access inside a root and away from protected paths."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import PermissionDenied

PathLike = str | os.PathLike[str]

CASE_INSENSITIVE = sys.platform == "darwin" or sys.platform.startswith("win")
"""The default file systems of macOS (APFS, HFS+) and Windows ignore case, so ``.GIT``
reaches ``.git``. Located entries are then compared casefolded; on Linux, exactly."""
HOME_TILDE, CWD_TILDE, OLDPWD_TILDE = "~", "~+", "~-"


def _escape(path: PathLike, root: PathLike) -> PermissionDenied:
    message = i18n.t("security.error.path_escape", path=str(path), root=str(root))
    return PermissionDenied("path_escape", message, {"path": str(path), "root": str(root)})


def resolve_within(root: PathLike, path: PathLike) -> Path:
    """Resolve ``path`` (relative to ``root``) following symlinks; refuse anything outside ``root``.

    Covers ``..`` traversal, absolute paths, symlinks pointing outside and symlinked
    parent directories. The check is made at call time: a symlink swapped in between
    this call and the later file access is not covered (time-of-check/time-of-use).
    """
    try:
        resolved_root = Path(root).resolve()
        resolved = (resolved_root / Path(path)).resolve()
    except (OSError, ValueError, RuntimeError) as exc:
        raise _escape(path, root) from exc
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise _escape(path, root)
    return resolved


def fold(text: str) -> str:
    """``text`` as the file system compares it: casefolded where case is ignored."""
    return text.casefold() if CASE_INSENSITIVE else text


def same_place(left: str, right: str) -> bool:
    """Whether two absolute paths name one place: equal as written, or, where the platform
    ignores case, equal casefolded and confirmed by the file system. A case-sensitive volume
    on macOS keeps ``Repo`` and ``repo`` apart; a path that cannot be read is not the same."""
    if left == right:
        return True
    if fold(left) != fold(right):
        return False
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def place_within(path: str, root: str) -> bool:
    """Whether ``path`` is ``root`` or lies under it: its ancestor at the depth of ``root``
    is the same place as ``root`` (``same_place``)."""
    parts, depth = Path(path).parts, len(Path(root).parts)
    return len(parts) >= depth and same_place(str(Path(*parts[:depth])), str(Path(root)))


def _tilde_base(prefix: str, cwd: PathLike) -> str | None:
    if prefix == HOME_TILDE:
        return os.path.expanduser(HOME_TILDE)
    if prefix == CWD_TILDE:
        return os.fspath(cwd)
    if prefix == OLDPWD_TILDE:
        return os.environ.get("OLDPWD") or None
    return None


def expand_home(path: PathLike, cwd: PathLike) -> str:
    """``path`` with a leading ``~``, ``~+`` (``cwd``) or ``~-`` (``$OLDPWD``) expanded, as
    the shell would. ``~user`` and ``~-`` without ``$OLDPWD`` stay literal: the shell check
    asks for those words."""
    text = os.fspath(path)
    prefix, sep, rest = text.partition("/")
    base = _tilde_base(prefix, cwd) if prefix.startswith(HOME_TILDE) else None
    if base is None:
        return text
    return os.path.join(base, rest) if sep else base


def home_spellings(path: PathLike, cwd: PathLike) -> list[str]:
    """``path`` as written and with its tilde expanded. Without a shell (``wev exec``)
    ``~+/x`` is the relative path ``./~+/x``, so a check keeps both spellings."""
    text = os.fspath(path)
    return list(dict.fromkeys((text, expand_home(text, cwd))))


def _forms(base: Path, path: PathLike) -> list[str]:
    """Lexical and symlink-resolved absolute spellings of ``path`` under ``base``, as
    written and with its tilde expanded."""
    forms: list[str] = []
    for spelling in home_spellings(path, base):
        joined = base / Path(spelling)
        forms.append(os.path.normpath(os.path.abspath(joined)))
        try:
            forms.append(str(joined.resolve()))
        except OSError, ValueError, RuntimeError:
            continue
    return forms


def _components(form: str, roots: Iterable[str]) -> list[str]:
    for root in roots:
        if form == root or form.startswith(root.rstrip(os.sep) + os.sep):
            return [part for part in Path(os.path.relpath(form, root)).parts if part != "."]
    return list(Path(form).parts)


def is_protected(path: PathLike, root: PathLike, protected_paths: Iterable[str]) -> bool:
    """True when ``path`` is, or lies inside, one of ``protected_paths``.

    An entry without a separator (``.git``) matches that name as any path component,
    case-insensitively and with ``fnmatch`` wildcards. An entry with a separator is a
    location relative to ``root`` (or absolute). Both the literal and the
    symlink-resolved path are checked, so a symlink to a protected file is protected. A
    leading ``~``, ``~+`` or ``~-`` is expanded. On a case-insensitive platform located
    entries are compared casefolded. The match is by path: the file need not exist.
    """
    try:
        base = Path(root)
        targets = _forms(base, path)
        roots = _forms(base, ".")
    except OSError, ValueError, RuntimeError:
        return True
    for entry in protected_paths:
        if not entry:
            continue
        if os.sep not in entry and "/" not in entry:
            names = [part.casefold() for form in targets for part in _components(form, roots)]
            if any(fnmatchcase(name, entry.casefold()) for name in names):
                return True
            continue
        anchors = [fold(form) for form in _forms(base, entry)]
        if any(_within(fold(t), a) for t in targets for a in anchors):
            return True
    return False


def _within(path: str, anchor: str) -> bool:
    return path == anchor or path.startswith(anchor.rstrip(os.sep) + os.sep)


GLOB_CHARS = frozenset("*?[")


def has_glob(text: str) -> bool:
    return any(char in GLOB_CHARS for char in text)


def _glob_hit(name: str, part: str, hidden: bool) -> bool:
    """``part`` can name ``name``; with ``hidden`` false a part that does not start with a
    dot never names a dotted name, as in the shell's own expansion."""
    if not hidden and name.startswith(".") and not part.startswith("."):
        return False
    return fnmatchcase(name, part)


def glob_may_match_protected(
    pattern: PathLike, root: PathLike, protected: Iterable[str], *, hidden: bool = True
) -> bool:
    """True when ``pattern``, read as a glob, can name a protected path.

    Programs such as ``find``, ``git`` and ``rg`` expand patterns themselves, so a literal
    ``.e*`` reaches a protected file without ever spelling its name. Each component of the
    pattern is matched against the protected names; a located entry (one with a separator)
    is matched component by component from ``root``. ``hidden=False`` is for a word the
    shell itself expands: its ``*``, ``?`` and ``[`` skip names that start with a dot.
    """
    text = os.fspath(pattern)
    if not has_glob(text):
        return False
    parts = [part.casefold() for part in Path(os.path.normpath(text)).parts if part != os.sep]
    base = os.path.normpath(os.path.abspath(root))
    for entry in protected:
        if not entry:
            continue
        if os.sep not in entry and "/" not in entry:
            if any(_glob_hit(entry.casefold(), part, hidden) for part in parts):
                return True
            continue
        located = os.path.normpath(os.path.join(base, entry))
        target = os.path.normpath(os.path.join(base, text))
        wanted, given = Path(located).parts, Path(target).parts
        pairs = list(zip(wanted, given, strict=False))
        if len(given) >= len(wanted) and all(_glob_hit(fold(w), fold(g), hidden) for w, g in pairs):
            return True
    return False
