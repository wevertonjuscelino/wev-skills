"""Risk of a ``git`` invocation: discarded work, force pushes and configuration that runs code.

git accepts any unique prefix of a long option (``--har`` for ``--hard``), reads aliases and
helper programs from configuration, and several subcommands run a program per commit or per
submodule. The rules here ask whenever one of those is in play.
"""

from __future__ import annotations

from wev_skills.security.risk import SAFE, Argv, CommandRisk, has_flag, has_long, risk

VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"})
CONFIG_OPTIONS = ("--config-env", "--exec-path")
"""Global options that change what git executes; ``-c`` is matched apart (also ``-cKEY=V``)."""
FORCE = (
    "--force",
    "--force-with-lease",
    "--force-if-includes",
    "--mirror",
    "--delete",
    "--prune",
)
NETWORK = ("fetch", "pull", "clone", "ls-remote")
RUNS_PROGRAMS = {
    "rebase": ("--exec",),
    "bisect": (),
    "filter-branch": (),
    "submodule": (),
    "difftool": (),
    "mergetool": (),
}
"""Subcommand -> long options that make it run a program (empty: flagged by its words)."""
RUN_WORDS = {"bisect": "run", "submodule": "foreach"}
KNOWN = frozenset(
    {"add", "am", "apply", "archive", "bisect", "blame", "branch", "bundle", "cat-file",
     "check-ignore", "checkout", "cherry-pick", "clean", "clone", "commit", "config",
     "describe", "diff", "difftool", "fetch", "filter-branch", "for-each-ref", "format-patch",
     "fsck", "gc", "grep", "help", "init", "log", "ls-files", "ls-remote", "ls-tree", "merge",
     "merge-base", "mergetool", "mv", "notes", "pull", "push", "range-diff", "rebase",
     "reflog", "remote", "reset", "restore", "rev-list", "rev-parse", "revert", "rm",
     "shortlog", "show", "show-ref", "sparse-checkout", "stash", "status", "submodule",
     "switch", "symbolic-ref", "tag", "update-index", "update-ref", "version", "whatchanged",
     "worktree"}
)  # fmt: skip
"""Anything else may be an alias or an external ``git-<name>`` program."""


def split_global(args: Argv) -> tuple[Argv, Argv]:
    """``(global options, subcommand and its arguments)`` of a git argv without the program."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in VALUE_OPTIONS else 1
    return args[:index], args[index:]


def sets_config(options: Argv) -> bool:
    """A global option that injects configuration or swaps git's own programs."""
    short = any(option.startswith("-c") and not option.startswith("--") for option in options)
    return short or has_long(options, CONFIG_OPTIONS)


def _operands(rest: Argv) -> Argv:
    return tuple(arg for arg in rest if not arg.startswith("-"))


def _checks_out_paths(rest: Argv) -> bool:
    """``git checkout <rev> <path>`` overwrites files; ``-b <new> <start>`` only makes a branch."""
    creates = has_flag(rest, "bBt") or has_long(rest, ("--track", "--orphan"))
    return not creates and len(_operands(rest)) > 1


def _discards(sub: str, rest: Argv) -> bool:
    forced = has_flag(rest, "f") or has_long(rest, ("--force",))
    staged_only = bool({"-S"} & set(rest)) or has_long(rest, ("--staged",))
    worktree = bool({"-W"} & set(rest)) or has_long(rest, ("--worktree",))
    rules = {
        "reset": has_long(rest, ("--hard", "--merge", "--keep")),
        "clean": not (has_flag(rest, "n") or has_long(rest, ("--dry-run",))),
        "rm": forced or has_flag(rest, "r"),
        "checkout": "--" in rest or "." in rest or forced or _checks_out_paths(rest),
        "switch": forced or has_flag(rest, "C") or has_long(rest, ("--discard-changes",)),
        "restore": not staged_only or worktree,
        "branch": has_flag(rest, "D")
        or (has_flag(rest, "d") or has_long(rest, ("--delete",)))
        and forced,
        "stash": rest[:1] in (("drop",), ("clear",)),
        "reflog": rest[:1] in (("expire",), ("delete",)),
        "worktree": rest[:1] == ("remove",) and forced,
        "update-ref": has_flag(rest, "d"),
    }
    return rules.get(sub, False)


def _runs_programs(sub: str, rest: Argv) -> bool:
    if sub in ("diff", "show", "log", "blame", "grep", "cat-file") and has_long(
        rest, ("--textconv", "--ext-diff")
    ):
        return True
    if sub not in RUNS_PROGRAMS:
        return False
    word = RUN_WORDS.get(sub)
    if word is not None:
        return word in rest
    options = RUNS_PROGRAMS[sub]
    return not options or has_long(rest, options) or has_flag(rest, "x")


def classify_git(args: Argv) -> CommandRisk:
    """Risk of ``git <args>``."""
    options, command = split_global(args)
    found = risk("u", "git_config") if sets_config(options) else SAFE
    if not command:
        return found
    sub, rest = command[0], command[1:]
    if sub not in KNOWN:
        return found.merge(risk("u", "git_unknown"))
    if _runs_programs(sub, rest):
        found = found.merge(risk("u", "git_runs_program"))
    if sub == "push":
        forced = has_flag(rest, "fd") or has_long(rest, FORCE)
        forced = forced or any(arg.startswith(("+", ":")) for arg in rest)
        return found.merge(risk("dxn", "git_push_force") if forced else risk("xn", "git_push"))
    if _discards(sub, rest):
        return found.merge(risk("d", "git_discard"))
    return found.merge(risk("n", "network")) if sub in NETWORK else found
