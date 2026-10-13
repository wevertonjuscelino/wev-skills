"""Warnings ``wev plan set`` prints so the plan author can change the plan before work starts.

- A check the policy will not run without an approval (inline interpreter code, a
  destructive command) or will refuse. The author can use a script file or a named test.
- A task file or a check argument that git ignores. Ignored files are outside the tree
  fingerprint by design: a change to them is not seen as work and does not invalidate a
  verification, so evidence that depends on them is weaker than it looks.

Nothing is refused here; these are notes for a person.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import Mode, PermissionOutcome, PlanTask
from wev_skills.core.engine import Engine
from wev_skills.state.model import RunState

CHECK_IGNORE_ARGV = ("git", "check-ignore", "--")
GIT_TIMEOUT_SECONDS = 30.0
MAX_PATHS = 500
NOTE_KEYS = {
    PermissionOutcome.NEEDS_APPROVAL: "orch.plan.warn.approval",
    PermissionOutcome.DENY: "orch.plan.warn.denied",
}


def _argv(command: str) -> tuple[str, ...]:
    try:
        return tuple(shlex.split(command))
    except ValueError:
        return ()


def _check_warnings(engine: Engine, state: RunState, task: PlanTask) -> list[str]:
    """One note per check that will wait for an approval or be refused in execute mode."""
    policy, cwd, risk = engine.services.policy, engine.cwd(state), progress.task_risk(state, task)
    found = []
    for command in task.checks:
        argv = _argv(command)
        if not argv:
            continue
        decision = policy.check_command(argv, cwd, Mode.EXECUTE, risk, consume=False)
        key = NOTE_KEYS.get(decision.outcome)
        if key is not None:
            shown = engine.clean(command)
            found.append(i18n.t(key, task=task.id, command=shown, reason=decision.reason))
    return found


def _candidates(task: PlanTask) -> list[str]:
    """Words that may name a path: the task's files and the operands of its checks."""
    words = [word for command in task.checks for word in _argv(command)[1:]]
    operands = [word for word in words if word and not word.startswith("-")]
    return [*task.files, *operands]


def ignored_paths(engine: Engine, state: RunState, paths: Sequence[str]) -> set[str]:
    """The ones among ``paths`` that git ignores; empty outside a repository or on failure."""
    wanted = [path for path in dict.fromkeys(paths) if path and "\x00" not in path][:MAX_PATHS]
    if not wanted:
        return set()
    try:
        result = engine.services.runner.run(
            (*CHECK_IGNORE_ARGV, *wanted), engine.cwd(state), GIT_TIMEOUT_SECONDS, None
        )
    except OSError:
        return set()
    if result.timed_out or result.exit_code != 0:
        return set()
    return {line.strip().strip('"') for line in result.stdout.splitlines()} & set(wanted)


def _ignored_warnings(engine: Engine, state: RunState, tasks: Sequence[PlanTask]) -> list[str]:
    every = [path for task in tasks for path in _candidates(task)]
    ignored = ignored_paths(engine, state, every)
    found = []
    for task in tasks:
        mine = sorted(set(_candidates(task)) & ignored)
        if mine:
            shown = engine.clean(", ".join(mine))
            found.append(i18n.t("orch.plan.warn.ignored", task=task.id, paths=shown))
    return found


def for_plan(engine: Engine, state: RunState) -> list[str]:
    tasks = state.plan.tasks if state.plan else ()
    checks = [note for task in tasks for note in _check_warnings(engine, state, task)]
    return [*checks, *_ignored_warnings(engine, state, tasks)]
