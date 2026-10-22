"""Recognize a call to this engine's own CLI and say which of its commands a person decides.

There is no exemption for a program that is merely named ``wev``. A command is the engine
only when its program resolves, by real path, to the plugin's ``bin/wev`` or to the running
interpreter invoked as ``-m wev_skills`` (and no ``wev_skills`` directory in the working
directory shadows the package).

The engine gates its own commands, so most are left to it. The ones listed here change what
the run allows (a decision of the operator, an approval request, a new or finished run,
another configuration, a file written by ``agent``, a remote start or stop, an install into
or an uninstall from a harness), and the two
``jev`` commands that send a file's content to the JEV service (``jev batch`` also writes its
``--out`` file). The hook answers ``ask`` for them so that Claude Code's permission prompt,
which a person answers, stands in front of them.

Those sensitive commands are also recognized by their words, however they are reached
(``mentioned_reason``): behind a wrapper, inside an inline ``sh -c`` script, or as arguments
handed to another program. That net is wider than the exemption on purpose: a program merely
named ``wev`` followed by ``approval grant`` asks too. What it cannot see is the inside of a
script file or of a program: a script that types the command into a pseudo-terminal names
the engine nowhere on the command line the hook reads.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[2]
ENGINE_LAUNCHER = PACKAGE_DIR.parents[1] / "bin" / "wev"
MODULE = PACKAGE_DIR.name
MODULE_FLAG = "-m"
BARE_NAME = ENGINE_LAUNCHER.name
CONFIG_OPTION = "--config"
VALUE_OPTIONS = ("--lang", CONFIG_OPTION)
MIN_ABBREVIATION = 3
OPERATOR_COMMANDS = frozenset(
    {("approval", "grant"), ("approval", "deny"), ("guard", "acknowledge"), ("task", "reopen"),
     ("specialists", "accept"), ("specialists", "retire"), ("run", "adopt")}
)  # fmt: skip
RUN_COMMANDS = frozenset(
    {("run", "start"), ("run", "finish"), ("agent", "create"), ("agent", "export"),
     ("remote", "start"), ("remote", "stop")}
)  # fmt: skip
JEV_COMMANDS = frozenset({("jev", "ask"), ("jev", "batch")})
HARNESS_COMMANDS = frozenset({("harness", "install"), ("harness", "uninstall")})
"""``harness export`` only writes into a directory the person names, so it is left to the engine."""
"""``jev status`` sends nothing and writes nothing, so it is left to the engine."""
REOPEN_COMMAND = ("approval", "request")
REOPEN_OPTION = "--reopen-denied"
REOPEN_MIN = len("--reo")
"""``--re`` is ambiguous for argparse (``--reason``, ``--requested-by``); ``--reo`` is not."""
REASON_OPERATOR = "engine_operator"
REASON_RUN = "engine_run"
REASON_REQUEST = "engine_request"
REASON_CONFIG = "engine_config"
REASON_JEV = "engine_jev"
REASON_HARNESS = "engine_harness"


def _real_program(program: str, cwd: str) -> str | None:
    if os.sep in program or "/" in program:
        return os.path.realpath(os.path.join(cwd, program))
    found = shutil.which(program)
    return os.path.realpath(found) if found else None


def _shadowed(cwd: str) -> bool:
    """A ``wev_skills`` entry in the working directory would be imported instead of this one."""
    local = Path(cwd) / MODULE
    module_file = Path(cwd) / f"{MODULE}.py"
    return module_file.exists() or (local.exists() and local.resolve() != PACKAGE_DIR)


def engine_args(argv: Sequence[str], cwd: str) -> tuple[str, ...] | None:
    """The arguments given to the engine's CLI, or ``None`` when ``argv`` is not a call to it."""
    if not argv:
        return None
    real = _real_program(argv[0], cwd)
    if real is None:
        return None
    if real == os.path.realpath(ENGINE_LAUNCHER):
        return tuple(argv[1:])
    module_call = tuple(argv[1:3]) == (MODULE_FLAG, MODULE)
    if module_call and real == os.path.realpath(sys.executable) and not _shadowed(cwd):
        return tuple(argv[3:])
    return None


def _abbreviates(arg: str, option: str, minimum: int = MIN_ABBREVIATION) -> bool:
    head = arg.split("=", 1)[0]
    return head.startswith("--") and len(head) >= minimum and option.startswith(head)


def _command_words(args: Sequence[str]) -> tuple[str, ...]:
    """The group and subcommand: the first words that are not global options or their values."""
    words: list[str] = []
    index = 0
    while index < len(args) and len(words) < 2:
        arg = args[index]
        takes_value = any(_abbreviates(arg, option) for option in VALUE_OPTIONS) and "=" not in arg
        if not arg.startswith("-"):
            words.append(arg)
        index += 2 if takes_value and not words else 1
    return tuple(words)


def _command_reason(args: Sequence[str]) -> str | None:
    """The reason for the engine command ``args`` name, ``--config`` aside."""
    words = _command_words(args)
    if words in OPERATOR_COMMANDS:
        return REASON_OPERATOR
    if words == REOPEN_COMMAND:
        reopens = any(_abbreviates(arg, REOPEN_OPTION, REOPEN_MIN) for arg in args)
        return REASON_OPERATOR if reopens else REASON_REQUEST
    if words in JEV_COMMANDS:
        return REASON_JEV
    if words in HARNESS_COMMANDS:
        return REASON_HARNESS
    return REASON_RUN if words in RUN_COMMANDS else None


def operator_reason(args: Sequence[str]) -> str | None:
    """Why a person must decide this engine command, or ``None`` to leave it to the engine."""
    if any(_abbreviates(arg, CONFIG_OPTION) for arg in args):
        return REASON_CONFIG
    return _command_reason(args)


def _is_launcher(word: str, cwd: str) -> bool:
    if os.sep not in word and "/" not in word:
        return False
    return os.path.realpath(os.path.join(cwd, word)) == os.path.realpath(ENGINE_LAUNCHER)


def _tail(words: Sequence[str], index: int, cwd: str) -> tuple[str, ...] | None:
    """The words after an engine reference at ``index``; ``None`` when there is none there."""
    if tuple(words[index : index + 2]) == (MODULE_FLAG, MODULE):
        return tuple(words[index + 2 :])
    if words[index] == BARE_NAME or _is_launcher(words[index], cwd):
        return tuple(words[index + 1 :])
    return None


def mentioned_reason(words: Sequence[str], cwd: str) -> str | None:
    """Why a person must decide a command line whose words name the engine (its launcher by
    real path, the bare word ``wev``, or ``-m wev_skills``) followed by a sensitive command.

    One pass over the words: ``--config`` positions are found once, so a long line costs
    time in proportion to its length."""
    configs = [i for i, word in enumerate(words) if _abbreviates(word, CONFIG_OPTION)]
    last_config = configs[-1] if configs else -1
    for index in range(len(words)):
        tail = _tail(words, index, cwd)
        if not tail:
            continue
        follows = last_config >= len(words) - len(tail)
        code = REASON_CONFIG if follows else _command_reason(tail)
        if code is not None:
            return code
    return None
