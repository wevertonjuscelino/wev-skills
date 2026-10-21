"""Path confinement: keep file access inside a root and away from protected paths."""

from __future__ import annotations

import os
from collections.abc import Iterable
from fnmatch import fnmatchcase
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import PermissionDenied

PathLike = str | os.PathLike[str]


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


def _home(path: PathLike) -> str:
    """``path`` with a leading ``~`` or ``~/`` expanded, as the shell would."""
    text = os.fspath(path)
    return os.path.expanduser(text) if text == "~" or text.startswith("~/") else text


def _forms(base: Path, path: PathLike) -> list[str]:
    """Lexical and symlink-resolved absolute spellings of ``path`` under ``base``."""
    joined = base / Path(_home(path))
    forms = [os.path.normpath(os.path.abspath(joined))]
    try:
        forms.append(str(joined.resolve()))
    except OSError, ValueError, RuntimeError:
        return forms
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
    leading ``~/`` is expanded. The match is by path: the file need not exist.
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
        anchors = _forms(base, entry)
        if any(t == a or t.startswith(a.rstrip(os.sep) + os.sep) for t in targets for a in anchors):
            return True
    return False


GLOB_CHARS = frozenset("*?[")


def has_glob(text: str) -> bool:
    return any(char in GLOB_CHARS for char in text)


def glob_may_match_protected(pattern: PathLike, root: PathLike, protected: Iterable[str]) -> bool:
    """True when ``pattern``, read as a glob, can name a protected path.

    Programs such as ``find``, ``git`` and ``rg`` expand patterns themselves, so a literal
    ``.e*`` reaches a protected file without ever spelling its name. Each component of the
    pattern is matched against the protected names; a located entry (one with a separator)
    is matched component by component from ``root``.
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
            if any(fnmatchcase(entry.casefold(), part) for part in parts):
                return True
            continue
        located = os.path.normpath(os.path.join(base, entry))
        target = os.path.normpath(os.path.join(base, text))
        wanted, given = Path(located).parts, Path(target).parts
        pairs = list(zip(wanted, given, strict=False))
        if len(given) >= len(wanted) and all(fnmatchcase(w, g) for w, g in pairs):
            return True
    return False
