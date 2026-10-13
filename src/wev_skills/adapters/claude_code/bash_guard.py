"""Judge one Bash command line for the PreToolUse hook: ``deny``, ``ask`` or no opinion.

The hook never answers ``allow`` and never reads the approval store: for a command that
needs approval the answer is always ``ask``, and the person's answer in Claude Code's
permission prompt is the approval for that call.

Whatever the hook cannot read with certainty goes to the person: an environment assignment
(``deny`` in plan mode), a word the shell would rewrite (expansion, glob, brace list,
``~user``), a program that runs text, a directory change it cannot follow, and a line too
long to analyze within the hook's timeout.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.claude_code import engine_cli
from wev_skills.core.contracts import Mode, PermissionDecision, PermissionOutcome, RiskLevel
from wev_skills.security import commands, git_rules, untrusted
from wev_skills.security.permissions import PermissionPolicy
from wev_skills.security.redact import redact
from wev_skills.security.shell import SimpleCommand, split_commands

ASK = "ask"
DENY = "deny"
NO_OPINION = ""
SEVERITY = (NO_OPINION, ASK, DENY)
MAX_COMMAND_CHARS = 20_000
MAX_WORDS = 2000
MAX_REASON_CHARS = 600
MAX_SHOWN_COMMAND = 200
CD_COMMANDS = frozenset({"cd", "pushd"})
CD_UNKNOWN = frozenset({"popd"})
ENVIRONMENT_COMMANDS = frozenset(
    {"env", "export", "declare", "typeset", "readonly", "local", "set", "unset", "shopt", "hash"}
)
"""Shell words that change variables or lookup for what runs after them, plus ``env``."""
GIT_DIRECTORY_OPTION = "-C"
OUTCOME_DECISIONS = {
    PermissionOutcome.ALLOW: NO_OPINION,
    PermissionOutcome.NEEDS_APPROVAL: ASK,
    PermissionOutcome.DENY: DENY,
}


@dataclass(frozen=True)
class HookVerdict:
    """What the Bash pre-check says: ``""`` (no opinion), ``ask`` or ``deny``, and why."""

    decision: str = NO_OPINION
    reason: str = ""


@dataclass(frozen=True)
class GuardContext:
    """The run the command is judged under: its mode, risk, policy, directory and root."""

    mode: Mode
    risk: RiskLevel
    policy: PermissionPolicy
    cwd: str
    root: str


def _reason(key: str, **params: object) -> str:
    return i18n.t(f"hooks.reason.{key}", **params)


def _ask(key: str, **params: object) -> HookVerdict:
    return HookVerdict(ASK, _reason(key, **params))


def _restrict(mode: Mode, key: str, **params: object) -> HookVerdict:
    """``deny`` in plan mode, ``ask`` otherwise."""
    return HookVerdict(DENY if mode is Mode.PLAN else ASK, _reason(key, **params))


def shown(argv: Sequence[str]) -> str:
    """A command as it may appear in a reason: redacted, without control characters, short."""
    text = untrusted.sanitize(redact(shlex.join(argv))).replace("\n", " ")
    return text[:MAX_SHOWN_COMMAND]


def _resolve(cwd: str, target: str) -> str:
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))


def next_directory(argv: Sequence[str], cwd: str | None) -> str | None:
    """The directory after ``argv`` ran; ``None`` once it cannot be known (``cd -``, ``popd``)."""
    name = argv[0] if argv else ""
    if cwd is None or name in CD_UNKNOWN:
        return None
    if name not in CD_COMMANDS:
        return cwd
    operands = [arg for arg in argv[1:] if not arg.startswith("-") or arg == "-"]
    if not operands:
        return os.path.expanduser("~") if name == "cd" else None
    return None if operands[0] == "-" or len(operands) > 1 else _resolve(cwd, operands[0])


def git_directory(argv: Sequence[str], cwd: str) -> str:
    """Where ``git -C <dir> ...`` works; ``cwd`` for anything else."""
    if not argv or commands.program_name(argv) != "git":
        return cwd
    options, _ = git_rules.split_global(tuple(argv[1:]))
    place = cwd
    for index, option in enumerate(options[:-1]):
        if option == GIT_DIRECTORY_OPTION:
            place = _resolve(place, options[index + 1])
    return place


def _inside(root: str, path: str) -> bool:
    real_root, real = os.path.realpath(root), os.path.realpath(path)
    return real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep)


def _from_policy(decision: PermissionDecision, part: SimpleCommand, compound: bool) -> HookVerdict:
    reason = decision.reason
    if compound and part.argv:
        reason = _reason("part", reason=reason, command=shown(part.argv))
    return HookVerdict(OUTCOME_DECISIONS[decision.outcome], reason)


def _maximal(views: Sequence[Sequence[str]]) -> list[tuple[str, ...]]:
    """``views`` without those that are the tail of a longer one: a wrapper yields every
    suffix of its argv, and scanning the longest covers them all."""
    kept: list[tuple[str, ...]] = []
    for view in sorted({tuple(view) for view in views}, key=len, reverse=True):
        if not any(longer[len(longer) - len(view) :] == view for longer in kept):
            kept.append(view)
    return kept


def _engine_verdicts(argv: Sequence[str], cwd: str) -> list[HookVerdict]:
    """``ask`` when the argv, or anything it wraps or inlines (``nohup``, ``timeout``,
    ``sh -c '...'``), names the engine together with one of its sensitive commands."""
    views = _maximal(commands.expand(tuple(argv)).commands)
    codes = (engine_cli.mentioned_reason(view, cwd) for view in views)
    found = next((code for code in codes if code is not None), None)
    return [_ask(found)] if found is not None else []


def _program_verdicts(
    part: SimpleCommand, context: GuardContext, cwd: str, compound: bool
) -> list[HookVerdict]:
    """Verdicts for the argv of one simple command run in ``cwd``."""
    argv, mode = part.argv, context.mode
    found = _engine_verdicts(argv, cwd)
    if part.dynamic or part.unresolved:
        found.append(_ask("unresolved", command=shown(argv)))
    elif engine_cli.engine_args(argv, cwd) is not None:
        return found
    name = commands.program_name(argv)
    if name in ENVIRONMENT_COMMANDS:
        found.append(_restrict(mode, "environment", command=shown(argv)))
    if name in CD_COMMANDS or name in CD_UNKNOWN:
        return found
    place = git_directory(argv, cwd)
    if place != cwd and not _inside(context.root, place):
        found.append(_ask("git_outside", directory=shown([place])))
    decision = context.policy.check_command(argv, place, mode, context.risk, consume=False)
    return [*found, _from_policy(decision, part, compound)]


def judge_part(
    part: SimpleCommand, context: GuardContext, cwd: str | None, compound: bool
) -> list[HookVerdict]:
    """Every verdict for one simple command: assignments, its argv and each redirection."""
    if cwd is None:
        return [_ask("directory_unknown")]
    found: list[HookVerdict] = []
    if part.assignments:
        names = ", ".join(part.assignments)[:MAX_SHOWN_COMMAND]
        found.append(_restrict(context.mode, "assignment", names=untrusted.sanitize(names)))
    if part.argv:
        found.extend(_program_verdicts(part, context, cwd, compound))
    elif part.unresolved:
        found.append(_ask("unresolved", command=""))
    for target in part.redirects:
        found.append(_from_policy(context.policy.check_path(target, cwd), part, compound))
    return found


def word_count(parts: Sequence[SimpleCommand]) -> int:
    return sum(len(part.argv) + len(part.redirects) + len(part.assignments) for part in parts)


def split_bounded(command: str) -> tuple[SimpleCommand, ...] | None:
    """The parts of ``command``; ``None`` when it is too long, has too many words or cannot
    be split with certainty. The caps keep the hook far inside its timeout."""
    if len(command) > MAX_COMMAND_CHARS:
        return None
    parts = split_commands(command)
    if parts is None or word_count(parts) > MAX_WORDS:
        return None
    return parts


def _located(parts: Sequence[SimpleCommand], cwd: str) -> tuple[list[Path], list[Path]]:
    """``(paths the words name, directories the command runs in)``, as the command sees them."""
    named: list[Path] = []
    places: list[Path] = []
    place: str | None = cwd
    for part in parts:
        base = place if place is not None else cwd
        if part.argv:
            base = git_directory(part.argv, base)
        words = [*part.argv[1:], *part.redirects]
        values = [word.split("=", 1)[-1] for word in words]
        named += [Path(_resolve(base, value)) for value in {*words, *values} if value]
        places.append(Path(base))
        place = next_directory(part.argv, place)
        places += [Path(place)] if place is not None else []
    return named, places


def command_paths(parts: Sequence[SimpleCommand], cwd: str) -> tuple[Path, ...]:
    """Every word that may name a file or directory, resolved as the command would see it,
    plus each directory the command runs in.

    Used to find the run that owns what the command touches, wherever it is started from.
    """
    named, places = _located(parts, cwd)
    return tuple(dict.fromkeys([*named, *places]))


def target_paths(parts: Sequence[SimpleCommand], cwd: str) -> tuple[Path, ...]:
    """Only the paths the words name. A run whose root lies inside one of them is touched
    too (``rm -rf <parent of the repository>``); the directory a command merely runs in
    is not such a target."""
    return tuple(dict.fromkeys(_located(parts, cwd)[0]))


def target_unknown(parts: Sequence[SimpleCommand]) -> bool:
    """Some word comes from a variable, so the path it names cannot be known here."""
    return any(part.expands or part.dynamic for part in parts)


def _needs_shell(part: SimpleCommand, cwd: str | None) -> bool:
    engine = cwd is not None and engine_cli.engine_args(part.argv, cwd) is not None
    return bool(part.redirects) or not engine


def decide_command(command: str, context: GuardContext) -> HookVerdict:
    """Judge a Bash command line; the most restrictive verdict over its parts wins."""
    parts = split_bounded(command)
    if parts is None:
        key = "too_large" if len(command) > MAX_COMMAND_CHARS else "untokenizable"
        return _ask(key)
    compound = len(parts) > 1 or any(part.redirects for part in parts)
    verdicts: list[HookVerdict] = []
    cwd: str | None = context.cwd
    for part in parts:
        verdicts.extend(judge_part(part, context, cwd, compound))
        cwd = next_directory(part.argv, cwd)
    if context.mode is Mode.PLAN and compound and any(_needs_shell(p, context.cwd) for p in parts):
        verdicts.append(_ask("plan_shell"))
    return max(
        verdicts, key=lambda verdict: SEVERITY.index(verdict.decision), default=HookVerdict()
    )
