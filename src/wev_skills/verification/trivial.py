"""Recognize checks that cannot fail: they ran, and they show nothing about the work.

This is a floor, not a proof. It catches the obvious no-ops (``true``, ``:``, ``echo``,
``printf``, ``test`` on constants, ``exit 0`` through an interpreter). A check that is
vacuous in a cleverer way is not caught here; the report says that checks are written by
the agent or the plan author and that the engine does not judge whether they are enough.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence

NO_OP_COMMANDS = frozenset({"true", ":", "echo", "printf"})
TEST_COMMANDS = frozenset({"test", "["})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
WRAPPERS = frozenset({"env", "command", "nice", "time", "builtin"})
INLINE_FLAG = "-c"
_FILE_TEST = re.compile(r"^-(?:[a-hkprsuwxGLNOS]|nt|ot|ef)$")
_SCRIPT_SPLIT = re.compile(r"\s*(?:;|&&|\|\||\n)\s*")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"^python[\d.]*$")
_PYTHON_NO_OP = re.compile(
    r"^(?:pass|(?:import sys\s*;\s*)?(?:sys\.)?exit\(\s*0?\s*\)|raise SystemExit(?:\(\s*0?\s*\))?)$"
)
_EXIT_ZERO = re.compile(r"^exit(?:\s+0)?$")


def _constant_test(args: Sequence[str]) -> bool:
    """A ``test`` whose operands name no file: the outcome is fixed when it is written."""
    return not any(_FILE_TEST.match(arg) for arg in args)


def _trivial_script(script: str) -> bool:
    parts = [part for part in _SCRIPT_SPLIT.split(script.strip()) if part]
    if not parts:
        return True
    for part in parts:
        if _EXIT_ZERO.match(part):
            continue
        try:
            argv = shlex.split(part)
        except ValueError:
            return False
        if not is_trivial(argv):
            return False
    return True


def is_trivial(argv: Sequence[str]) -> bool:
    """True when ``argv`` is a no-op that would pass whatever the state of the work."""
    words = list(argv)
    while words and (words[0] in WRAPPERS or _ASSIGNMENT.match(words[0])):
        words = words[1:]
    if not words:
        return True
    name, args = os.path.basename(words[0]), words[1:]
    if name in NO_OP_COMMANDS:
        return True
    if name in TEST_COMMANDS:
        return _constant_test(args)
    if name in SHELLS and INLINE_FLAG in args:
        script = args[args.index(INLINE_FLAG) + 1 : args.index(INLINE_FLAG) + 2]
        return bool(script) and _trivial_script(script[0])
    if _PYTHON.match(name) and len(args) == 2 and args[0] == INLINE_FLAG:
        return bool(_PYTHON_NO_OP.match(args[1].strip()))
    return False
