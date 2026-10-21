"""Moves and removals of a directory that holds a protected path.

``mv ~/.local x`` never names the protected file under it, yet takes it away, and a copy
can then be put in its place. ``uprooted`` finds a program that renames or removes an
operand that is an ancestor of a protected path, so the policy can ask.

A protected location (an entry with a separator) is matched by path, whether it exists or
not. A protected name (``.git``) is found by walking an existing directory, with the limits
of ``security.recursive``. Known programs only: ``mv`` (its sources), ``rm``, ``rmdir``,
``unlink``, ``find`` with ``-delete`` (its start directories) and ``rsync`` with
``--remove-source-files`` (its sources). A symlink operand is not walked, since only the
link is moved or removed, but it is still matched by path, as written and as resolved: a
symlinked ``~/.local`` holds the registry by path. Paths are compared casefolded where the
platform ignores case (``paths.fold``).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

from wev_skills.security import recursive
from wev_skills.security.paths import fold, home_spellings

Operands = Callable[[Sequence[str]], list[str]]
END_OF_OPTIONS = "--"
MV_TARGET_LONG = "--target-directory"
MIN_LONG_PREFIX = len("--t")
FIND_LEADING = frozenset({"-H", "-L", "-P"})
FIND_EXPRESSION_START = frozenset({"(", "!"})


def _operands(args: Sequence[str]) -> list[str]:
    """Words that are not options (everything after ``--`` is an operand)."""
    found: list[str] = []
    ended = False
    for arg in args:
        if not ended and arg == END_OF_OPTIONS:
            ended = True
        elif ended or not arg.startswith("-") or arg == "-":
            found.append(arg)
    return found


def _long_target(arg: str) -> bool:
    """``--target-directory`` or a prefix of it (``--t``, ``--targ=x``), as getopt accepts."""
    name = arg.split("=", 1)[0]
    if len(name) < MIN_LONG_PREFIX or not name.startswith("--"):
        return False
    return MV_TARGET_LONG.startswith(name) or name.startswith(MV_TARGET_LONG)


def _names_target(args: Sequence[str]) -> bool:
    short = (a for a in args if a.startswith("-") and not a.startswith("--"))
    return any(_long_target(a) for a in args) or any("t" in a[1:] for a in short)


def _mv_sources(args: Sequence[str]) -> list[str]:
    """Every operand with ``-t``; else every operand but the destination."""
    operands = _operands(args)
    return operands if _names_target(args) else operands[:-1]


def _find_starts(args: Sequence[str]) -> list[str]:
    if "-delete" not in args:
        return []
    starts: list[str] = []
    for arg in args:
        if not starts and arg in FIND_LEADING:
            continue
        if arg.startswith("-") or arg in FIND_EXPRESSION_START:
            break
        starts.append(arg)
    return starts or ["."]


def _rsync_sources(args: Sequence[str]) -> list[str]:
    return _operands(args)[:-1] if "--remove-source-files" in args else []


REMOVERS: dict[str, Operands] = {
    "mv": _mv_sources,
    "rm": _operands,
    "rmdir": _operands,
    "unlink": _operands,
    "find": _find_starts,
    "rsync": _rsync_sources,
}


def _spellings(path: str) -> list[str]:
    forms = [os.path.normpath(os.path.abspath(path))]
    try:
        forms.append(os.path.realpath(path))
    except OSError, ValueError:
        return forms
    return forms


def _located_below(target: str, root: str, protected: Sequence[str]) -> str | None:
    """A protected location that ``target`` is, or contains, matched by path."""
    targets = [fold(form) for form in _spellings(target)]
    for entry in protected:
        if not entry or (os.sep not in entry and "/" not in entry):
            continue
        joined = (os.path.join(root, spelling) for spelling in home_spellings(entry, root))
        anchors = (anchor for path in joined for anchor in _spellings(path))
        for anchor in anchors:
            folded = fold(anchor)
            if any(folded == t or folded.startswith(t.rstrip(os.sep) + os.sep) for t in targets):
                return anchor
    return None


def _holds(target: str, root: str, protected: Sequence[str]) -> str | None:
    found = _located_below(target, root, protected)
    if found is None and not os.path.islink(target) and os.path.isdir(target):
        found = recursive.contains_protected(target, root, protected)
    return found


def uprooted(argv: Sequence[str], cwd: str, protected: Sequence[str]) -> tuple[str, str] | None:
    """``(operand, protected path under it)`` when ``argv`` moves or removes a directory
    that holds a protected path; ``None`` otherwise."""
    name = os.path.basename(argv[0]).lower() if argv else ""
    rule = REMOVERS.get(name)
    if rule is None:
        return None
    for operand in rule(list(argv[1:])):
        for spelling in home_spellings(operand, cwd):
            found = _holds(os.path.join(cwd, spelling), cwd, protected)
            if found is not None:
                return operand, found
    return None
