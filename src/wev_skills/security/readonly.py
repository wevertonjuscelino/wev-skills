"""The read-only command allowlist used by plan mode and by read-only remote hosts.

A command is read-only when its leading tokens are on ``READ_ONLY_COMMANDS`` and none of its
arguments is an option that makes the program write a file, run another program, reach
another machine or change system state. Programs whose scripts can write or execute
(``sed``, ``awk``), that exist to write (``tee``) or to run other programs (``xargs``,
``env``) are deliberately absent, and ``env``/``printenv`` would print secrets.

Like the rest of ``security``, this is a heuristic that reduces accidents, not a sandbox.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence

from wev_skills.security import commands, patterns

# Commands that only read. In plan mode anything else counts as mutating.
READ_ONLY_COMMANDS: tuple[str, ...] = (
    "git status", "git diff", "git log", "git show", "git rev-parse", "git ls-files",
    "git blame", "git branch --show-current", "ls", "cat", "head", "tail", "wc", "pwd",
    "stat", "file", "which", "du", "df", "rg", "grep", "find",
    "uptime", "hostname", "whoami", "id", "date", "uname", "free", "ps", "nproc", "lscpu",
    "ss", "netstat", "systemctl status", "systemctl is-active", "systemctl is-enabled",
    "systemctl is-failed", "journalctl", "docker ps", "docker logs", "kubectl get",
    "kubectl describe", "kubectl logs",
)  # fmt: skip
# Long options that make an otherwise read-only command write files, run programs, reach
# another machine or change state. An argument matches when it is a prefix of the option
# (tools accept abbreviations).
READ_ONLY_FORBIDDEN_OPTIONS: dict[str, tuple[str, ...]] = {
    "git": ("--output", "--ext-diff"),
    "rg": ("--pre", "--pre-glob", "--hostname-bin"),
    "find": ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0",
             "-fprintf", "-fls"),
    "file": ("--compile",),
    "hostname": ("--file", "--boot"),
    "ss": ("--kill", "--diag"),
    "systemctl": ("--host", "--machine"),
    "journalctl": ("--vacuum-size", "--vacuum-time", "--vacuum-files", "--rotate", "--flush",
                   "--sync", "--relinquish-var", "--smart-relinquish-var", "--setup-keys",
                   "--update-catalog", "--cursor-file", "--machine"),
    "kubectl": ("--kubeconfig", "--server", "--cache-dir"),
}  # fmt: skip
# Single-letter options with the same effect; matched inside any ``-abc`` cluster.
READ_ONLY_FORBIDDEN_SHORT: dict[str, str] = {
    "file": "C",
    "hostname": "Fb",
    "ss": "KD",
    "systemctl": "HM",
    "journalctl": "M",
    "kubectl": "s",
}
# A read-only name only counts when it is found through PATH or lives in one of these.
TRUSTED_BIN_DIRS: tuple[str, ...] = (
    "/bin", "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/sbin", "/usr/sbin",
)  # fmt: skip
DATE_OPTIONS = ("-u", "--utc", "--universal", "-R", "--rfc-email")
DATE_PREFIXES = ("+", "-I", "--iso-8601", "--rfc-3339")
PS_SAFE_FLAGS = frozenset(
    {"-A", "-a", "-f", "-l", "-x", "-w", "-ww", "-Af", "-Al", "-ax", "-axf", "a", "x", "u",
     "ax", "aux", "axu", "auxw", "auxww", "axww"}
)  # fmt: skip
"""The only flag spellings allowed. ``-e`` and ``-E`` print process environments on macOS,
and the BSD ``e`` modifier does on Linux and macOS, so no cluster outside this set passes."""
PS_VALUE_FLAGS = {"-p": r"[0-9]+(,[0-9]+)*", "-u": r"[A-Za-z0-9_][A-Za-z0-9_.-]*", "-o": ""}
PS_SAFE_FIELDS = frozenset(
    {"pid", "ppid", "pgid", "uid", "user", "ruser", "comm", "command", "args", "etime", "time",
     "pcpu", "%cpu", "pmem", "%mem", "rss", "vsz", "stat", "state", "tty", "start", "lstart",
     "nice", "ni", "pri"}
)  # fmt: skip

PROCESS_ENVIRON = re.compile(r"/proc/[^/]+/environ")
"""A file that holds a process environment: reading it prints secrets."""

ArgumentRule = Callable[[Sequence[str]], bool]


def _flags_only(args: Sequence[str]) -> bool:
    """No operand at all: ``hostname NAME`` sets the name, ``hostname`` prints it."""
    return all(arg.startswith("-") for arg in args)


def _date_arguments(args: Sequence[str]) -> bool:
    """Only output formats and time-zone flags; a bare operand or ``-s`` sets the clock."""
    return all(arg in DATE_OPTIONS or arg.startswith(DATE_PREFIXES) for arg in args)


def _ps_value(flag: str, value: str) -> bool:
    if flag == "-o":
        fields = [field.split("=", 1)[0] for field in value.split(",")]
        return bool(fields) and all(field in PS_SAFE_FIELDS for field in fields)
    return re.fullmatch(PS_VALUE_FLAGS[flag], value) is not None


def _ps_arguments(args: Sequence[str]) -> bool:
    """Only the fixed safe forms: listed flags, and ``-p``, ``-u``, ``-o`` with plain values."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in PS_VALUE_FLAGS:
            if index + 1 >= len(args) or not _ps_value(arg, args[index + 1]):
                return False
            index += 2
            continue
        if arg not in PS_SAFE_FLAGS:
            return False
        index += 1
    return True


READ_ONLY_ARGUMENT_RULES: dict[str, ArgumentRule] = {
    "hostname": _flags_only,
    "uptime": _flags_only,
    "whoami": _flags_only,
    "nproc": _flags_only,
    "uname": _flags_only,
    "date": _date_arguments,
    "ps": _ps_arguments,
}


def _forbidden_long(arg: str, option: str) -> bool:
    head = arg.split("=", 1)[0]
    return len(head) > 2 and option.startswith(head)


def _forbidden_short(arg: str, letters: str) -> bool:
    cluster = arg.startswith("-") and not arg.startswith("--")
    return cluster and any(letter in arg[1:] for letter in letters)


def is_read_only(argv: Sequence[str]) -> bool:
    """True when ``argv`` is on the read-only allowlist and uses no write/exec option."""
    if not argv or patterns.first_match([argv], READ_ONLY_COMMANDS) is None:
        return False
    directory = os.path.dirname(argv[0])
    if directory and os.path.normpath(directory) not in TRUSTED_BIN_DIRS:
        return False
    name, args = commands.program_name(argv), argv[1:]
    if commands.classify(tuple(argv)).unanalyzable or any(PROCESS_ENVIRON.search(a) for a in args):
        return False
    options = READ_ONLY_FORBIDDEN_OPTIONS.get(name, ())
    if any(_forbidden_long(arg, option) for arg in args for option in options):
        return False
    letters = READ_ONLY_FORBIDDEN_SHORT.get(name, "")
    if any(_forbidden_short(arg, letters) for arg in args):
        return False
    rule = READ_ONLY_ARGUMENT_RULES.get(name)
    return rule is None or rule(args)
