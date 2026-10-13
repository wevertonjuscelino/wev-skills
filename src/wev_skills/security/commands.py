"""Command parsing and risk classification (allow/deny matching lives in ``patterns``).

This module is a deny-oriented heuristic. It recognizes common destructive,
privileged, external-effect and network commands so that accidents are caught
before they run, and it errs on the side of asking for approval. It is NOT a
sandbox: a program it does not know, a script file, an alias, or a renamed
binary can still do anything the operating system lets the process do.
Isolation has to come from the environment (containers, OS permissions).

The executor in this project never runs a shell, so ``parse`` refuses command
strings whose meaning depends on one instead of running them wrongly.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import reduce

from wev_skills import i18n
from wev_skills.core.errors import PermissionDenied
from wev_skills.security import command_tables as tables
from wev_skills.security import git_rules
from wev_skills.security.risk import SAFE, Argv, CommandRisk, has_flag, has_long, risk

__all__ = [
    "MAX_UNWRAP_DEPTH",
    "Argv",
    "CommandRisk",
    "Expansion",
    "classify",
    "classify_expansion",
    "expand",
    "has_shell_syntax",
    "is_assignment",
    "normalize",
    "parse",
    "program_name",
    "risk",
]

MAX_UNWRAP_DEPTH = 4
_CONTROL_CHARS = ";&|<>\n\r"
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")


@dataclass(frozen=True)
class Expansion:
    """Every command an argv may end up running, plus codes for parts that defy analysis."""

    commands: tuple[Argv, ...]
    opaque: tuple[str, ...] = ()


def _deny(code: str, **params: object) -> PermissionDenied:
    details = {key: str(value) for key, value in params.items()}
    return PermissionDenied(code, i18n.t(f"security.error.{code}", **params), details)


def is_assignment(token: str) -> bool:
    """``NAME=value``: what a shell reads as an environment assignment before a command."""
    return _ASSIGNMENT.match(token) is not None


def _shell_syntax(command: str) -> str | None:
    """First shell control token that is active (not literal) in ``command``, if any."""
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "'":
            quote = "" if char == "'" else quote
        elif char == "\\":
            index += 1
        elif char == "`" or command.startswith("$(", index):
            return "`" if char == "`" else "$("
        elif quote == '"':
            quote = "" if char == '"' else quote
        elif char in "'\"":
            quote = char
        elif char in _CONTROL_CHARS:
            return char
        index += 1
    return None


def has_shell_syntax(command: str) -> bool:
    return _shell_syntax(command) is not None


def parse(command: str | Sequence[str], allow_shell: bool = False) -> Argv:
    """Turn a command string or argv into a validated argv tuple (never runs anything)."""
    if isinstance(command, str):
        if "\x00" in command:
            raise _deny("nul_byte")
        token = None if allow_shell else _shell_syntax(command)
        if token is not None:
            raise _deny("shell_syntax", token=repr(token))
        try:
            argv = tuple(shlex.split(command))
        except ValueError as exc:
            raise _deny("unparseable", detail=str(exc)) from exc
    else:
        argv = tuple(command)
        if any(not isinstance(item, str) for item in argv):
            raise _deny("not_strings")
    if not argv or not argv[0].strip():
        raise _deny("empty_command")
    if any("\x00" in item for item in argv):
        raise _deny("nul_byte")
    return argv


def program_name(argv: Sequence[str]) -> str:
    """Lower-cased basename of the program, so ``/bin/RM`` is treated as ``rm``."""
    return os.path.basename(argv[0].rstrip("/")).lower() if argv else ""


def normalize(argv: Sequence[str]) -> Argv:
    return (program_name(argv), *argv[1:]) if argv else ()


def _canonical(name: str) -> str:
    """Drop a version suffix: ``python3.12`` -> ``python``, ``pip3`` -> ``pip``."""
    return re.sub(r"[\d.]+$", "", name) or name


def _kill(args: Argv) -> CommandRisk:
    for index, arg in enumerate(args):
        value = arg.split("=", 1)[-1] if arg.startswith("--signal=") else arg
        named = arg.startswith("-") or (index > 0 and args[index - 1] in ("-s", "--signal", "-n"))
        if named and value.lstrip("-").upper().removeprefix("SIG") in ("9", "KILL"):
            return risk("d", "kill")
    return SAFE


def _curl_sends(args: Argv) -> bool:
    methods = [args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-X", "--request")]
    methods += [a[2:] for a in args if a.startswith("-X") and len(a) > 2]
    methods += [a.split("=", 1)[1] for a in args if a.startswith("--request=")]
    return has_flag(args, "dFT", tables.CURL_SEND) or any(
        method.upper() not in ("GET", "HEAD") for method in methods
    )


def _env(args: Argv) -> CommandRisk:
    """``env`` that sets, clears or splits anything changes what the next program does."""
    first = args[0] if args else ""
    changes = first.startswith("-") or is_assignment(first)
    return risk("u", "env_assignment") if changes else SAFE


Handler = Callable[[Argv], CommandRisk]


def _when(condition: Callable[[Argv], bool], flags: str, code: str) -> Handler:
    return lambda args: risk(flags, code) if condition(args) else SAFE


_HANDLERS: dict[str, Handler] = {
    "git": git_rules.classify_git,
    "kill": _kill,
    "env": _env,
    "curl": _when(_curl_sends, "xn", "upload"),
    "wget": _when(lambda a: any(x.startswith(tables.WGET_SEND) for x in a), "xn", "upload"),
    "rm": _when(lambda a: has_flag(a, "rRf") or has_long(a, tables.RM_LONG), "d", "rm"),
    "rsync": _when(lambda a: has_long(a, tables.RSYNC_DELETE), "d", "rsync_delete"),
    **dict.fromkeys(
        ("chmod", "chown", "chgrp"),
        _when(lambda a: has_flag(a, "R", ("--recursive",)), "d", "recursive_perms"),
    ),
    "find": _when(lambda a: "-delete" in a, "d", "find_delete"),
    **dict.fromkeys(
        ("awk", "gawk", "mawk"),
        _when(lambda a: any("system(" in x or "|" in x for x in a), "u", "inline_code"),
    ),
    **dict.fromkeys(
        ("docker", "podman"),
        _when(lambda a: "--privileged" in a or "--pid=host" in a, "p", "privileged"),
    ),
    # tmux accepts unambiguous prefixes such as ``kill-ser``.
    "tmux": _when(
        lambda a: any(len(x) >= 8 and "kill-server".startswith(x) for x in a), "d", "tmux_kill"
    ),
}


def _subcommand_risks(name: str, args: Argv) -> list[CommandRisk]:
    table = tables.SUBCOMMANDS.get(name, {})
    words = [arg for arg in args if not arg.startswith("-")]
    runs = {" ".join(words[i : i + size]) for size in (1, 2) for i in range(len(words))}
    return [risk(*table[run]) for run in sorted(runs & set(table))]


def _embeds_shell(name: str, args: Argv) -> bool:
    """One argument that is itself a command line (``"ls | head"``) for a program that is
    not known to take patterns or prose."""
    known = (tables.TEXT_ARGUMENT_PROGRAMS, tables.SHELLS, tables.SQL_CLIENTS, tables.INTERPRETERS)
    if any(name in group for group in known):
        return False
    return any(any(c.isspace() for c in arg) and _shell_syntax(arg) is not None for arg in args)


def _direct(argv: Argv) -> CommandRisk:
    """Risk of one concrete argv, without looking inside wrappers."""
    name, args = _canonical(program_name(argv)), argv[1:]
    found = _subcommand_risks(name, args)
    found += [risk(*tables.ALWAYS[name])] if name in tables.ALWAYS else []
    found += [risk("d", "raw_write")] if name.startswith("mkfs") else []
    found += [_HANDLERS[name](args)] if name in _HANDLERS else []
    found += [risk("u", "env_assignment")] if is_assignment(argv[0]) else []
    found += [risk("u", "embedded_shell")] if _embeds_shell(name, args) else []
    sql = name in tables.SQL_CLIENTS
    if sql and any(tables.SQL_DROP.search(tables.SQL_COMMENT.sub(" ", a)) for a in args):
        found.append(risk("dx", "sql"))
    return reduce(CommandRisk.merge, found, SAFE)


def _leading_options(args: Argv) -> Argv:
    """Interpreter options: everything before ``-m`` or the first script-like argument."""
    kept: list[str] = []
    for index, arg in enumerate(args):
        follows_flag = index > 0 and args[index - 1].startswith("-")
        if arg == "-m" or not (arg.startswith("-") or follows_flag):
            break
        kept.append(arg)
    return tuple(kept)


def _env_split(args: Argv) -> list[str]:
    """Texts ``env -S`` would split into a command (``-S text`` and ``-Stext``)."""
    texts = [args[i + 1] for i, a in enumerate(args[:-1]) if a in tables.ENV_SPLIT]
    texts += [a[2:] for a in args if a.startswith("-S") and len(a) > 2]
    return texts + [a.split("=", 1)[1] for a in args if a.startswith("--split-string=")]


def _inline(view: Argv) -> tuple[list[str], list[Argv], list[str]]:
    """Inline shell texts, derived commands and opaque codes carried by one argv."""
    name, args = _canonical(program_name(view)), view[1:]
    options = _leading_options(args)
    if name == "eval":
        return [" ".join(args)], [], []
    if name == "env":
        texts = _env_split(args)
        return texts, [], ["inline_shell"] if texts else []
    if name in tables.SHELLS:
        hits = [
            i
            for i, a in enumerate(options)
            if a.startswith("-") and "c" in a[1:] and not a.startswith("--")
        ]
        script = [] if hits or len(options) == len(args) else ["script_file"]
        return [args[i + 1] for i in hits[:1] if i + 1 < len(args)], [], script
    if name in tables.INTERPRETERS:
        at = len(options)
        module = args[at + 1 :] if args[at : at + 1] == ("-m",) else ()
        letters = tables.INTERPRETERS[name]
        inline = has_flag(options, letters, tables.INTERPRETER_LONG) or args[:1] == ("eval",)
        return [], [module] if module else [], ["inline_code"] if inline else []
    if name == "git":
        options, command = git_rules.split_global(args)
        return [], [("git", *command)] if options and command else [], []
    return [], [], []


def expand(argv: Sequence[str], _depth: int = 0) -> Expansion:
    """Unwrap wrappers (``sudo``, ``env``, ``xargs``...) and inline ``sh -c`` style commands."""
    base = tuple(argv)
    if _depth > MAX_UNWRAP_DEPTH:
        return Expansion((base,), ("too_deep",))
    name = _canonical(program_name(base))
    starts = list(range(1, len(base))) if name in tables.WRAPPERS else []
    if name == "find":
        starts = [i + 1 for i, arg in enumerate(base) if arg in tables.FIND_EXEC]
    views = [base] + [base[start:] for start in starts if base[start:]]
    found: list[Argv] = list(views)
    opaque: list[str] = ["runs_text"] if name == "find" and starts else []
    spaced = [a for a in base[1:] if any(c.isspace() for c in a)]
    texts = spaced if name in tables.STRING_WRAPPERS else []
    derived: list[Argv] = []
    for view in views:
        inline_texts, inline_commands, codes = _inline(view)
        texts, derived, opaque = texts + inline_texts, derived + inline_commands, opaque + codes
    for text in texts:
        try:
            derived.append(parse(text))
        except PermissionDenied:
            opaque.append("inline_shell")
    for command in derived:
        inner = expand(command, _depth + 1)
        found, opaque = found + list(inner.commands), opaque + list(inner.opaque)
    return Expansion(tuple(dict.fromkeys(found)), tuple(dict.fromkeys(opaque)))


def classify_expansion(expansion: Expansion) -> CommandRisk:
    opaque = [risk("u", code) for code in expansion.opaque]
    return reduce(CommandRisk.merge, [*map(_direct, expansion.commands), *opaque], SAFE)


def classify(argv: Sequence[str]) -> CommandRisk:
    """Heuristic risk of ``argv``, including anything it wraps. See the module docstring."""
    return classify_expansion(expand(parse(argv)))
