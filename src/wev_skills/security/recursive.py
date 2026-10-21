"""Recursive readers: a program that walks a directory reads what is inside it.

``cat <protected file>`` is denied by the policy. ``grep -r``, ``rg``, ``find``, ``tar``,
``zip``, ``cp -r`` and ``rsync`` given a directory that contains a protected path reach the
same content without naming it. ``protected_inside`` finds that case so the policy can ask.

Like the rest of ``security`` this is a heuristic. It knows the programs and options listed
here, it looks at directories that exist when the command is judged, and it walks at most
``MAX_ENTRIES`` entries (a larger tree is treated as holding a protected path). ``rg`` skips
hidden files unless told otherwise, so for it a hidden protected name does not count
without ``--hidden``, ``-.`` or ``-uu``. Exclusion options (``--exclude-dir``) are not read.
Located entries are compared casefolded where the platform ignores case (``paths.fold``).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from fnmatch import fnmatchcase

from wev_skills.security.paths import fold
from wev_skills.security.risk import has_flag, has_long

MAX_ENTRIES = 20_000
HIDDEN_PREFIX = "."

Rule = Callable[[Sequence[str]], bool]


def _always(_args: Sequence[str]) -> bool:
    return True


def _grep(args: Sequence[str]) -> bool:
    recurse = any(arg.replace("=", " ").split()[-1:] == ["recurse"] for arg in args)
    return (
        has_flag(args, "rR")
        or has_long(args, ("--recursive", "--dereference-recursive"))
        or (recurse and (has_flag(args, "d") or has_long(args, ("--directories",))))
    )


def _copies(args: Sequence[str]) -> bool:
    return has_flag(args, "rRa") or has_long(args, ("--recursive", "--archive"))


RECURSIVE_READERS: dict[str, Rule] = {
    "grep": _grep,
    "egrep": _grep,
    "fgrep": _grep,
    "rgrep": _always,
    "rg": _always,
    "find": _always,
    "tar": _always,
    "gtar": _always,
    "bsdtar": _always,
    "zip": _always,
    "cp": _copies,
    "rsync": _copies,
}
IMPLICIT_CWD = {"grep": 1, "egrep": 1, "fgrep": 1, "rgrep": 1, "rg": 1, "find": 0}
"""Readers that walk the working directory when no path operand is given, with how many
operands they take before a path (the pattern of a search)."""


def _reads_hidden(name: str, args: Sequence[str]) -> bool:
    """``rg`` leaves hidden entries out unless asked; every other reader walks them."""
    if name != "rg":
        return True
    unrestricted = sum(arg.count("u") for arg in args if arg.startswith("-") and arg[1:2] == "u")
    return has_flag(args, ".") or has_long(args, ("--hidden",)) or unrestricted >= 2


def _matches(name: str, entries: Sequence[str]) -> str | None:
    folded = name.casefold()
    return next((entry for entry in entries if fnmatchcase(folded, entry.casefold())), None)


def _walk(directory: str, names: Sequence[str], hidden: bool) -> str | None:
    """The first entry under ``directory`` whose name is protected; the directory itself
    when the walk is cut short (the tree is too large to clear)."""
    seen = 0
    for current, subdirs, files in os.walk(directory):
        kept = [n for n in (*subdirs, *files) if hidden or not n.startswith(HIDDEN_PREFIX)]
        for name in kept:
            if _matches(name, names) is not None:
                return os.path.join(current, name)
        seen += len(kept)
        if seen > MAX_ENTRIES:
            return directory
        subdirs[:] = sorted(n for n in subdirs if hidden or not n.startswith(HIDDEN_PREFIX))
    return None


def _located(directory: str, root: str, entries: Sequence[str], hidden: bool) -> str | None:
    """A protected location (an entry with a separator) that lies inside ``directory``."""
    prefix = fold(directory.rstrip(os.sep) + os.sep)
    for entry in entries:
        anchor = os.path.realpath(os.path.join(root, entry))
        if not fold(anchor).startswith(prefix) or not os.path.lexists(anchor):
            continue
        below = fold(anchor)[len(prefix) :].split(os.sep)
        if hidden or not any(part.startswith(HIDDEN_PREFIX) for part in below):
            return anchor
    return None


def contains_protected(
    directory: str, root: str, protected: Sequence[str], hidden: bool = True
) -> str | None:
    """A protected path inside ``directory`` (not the directory itself), or ``None``."""
    real = os.path.realpath(directory)
    plain = [entry for entry in protected if entry and os.sep not in entry and "/" not in entry]
    names = [entry for entry in plain if hidden or not entry.startswith(HIDDEN_PREFIX)]
    places = [entry for entry in protected if entry and (os.sep in entry or "/" in entry)]
    located = _located(real, root, places, hidden)
    return located or (_walk(real, names, hidden) if names else None)


def _directories(name: str, args: Sequence[str], cwd: str) -> list[str]:
    """Existing directories among the operands; the working directory when a reader that
    defaults to it was given nothing but its pattern."""
    operands = [arg for arg in args if arg and not arg.startswith("-")]
    spellings = dict.fromkeys(s for arg in operands for s in (arg, os.path.expanduser(arg)))
    paths = [os.path.join(cwd, spelling) for spelling in spellings]
    existing = [path for path in paths if os.path.lexists(path)]
    found = [path for path in existing if os.path.isdir(path)]
    implicit = name in IMPLICIT_CWD and not existing and len(operands) <= IMPLICIT_CWD[name]
    return found or ([cwd] if implicit else [])


def protected_inside(
    argv: Sequence[str], cwd: str, protected: Sequence[str]
) -> tuple[str, str] | None:
    """``(directory, protected path inside it)`` when ``argv`` is a recursive reader given a
    directory that holds a protected path; ``None`` otherwise."""
    name = os.path.basename(argv[0]).lower() if argv else ""
    rule = RECURSIVE_READERS.get(name)
    args = list(argv[1:])
    if rule is None or not rule(args):
        return None
    hidden = _reads_hidden(name, args)
    for directory in _directories(name, args, cwd):
        found = contains_protected(directory, cwd, protected, hidden)
        if found is not None:
            return directory, found
    return None
