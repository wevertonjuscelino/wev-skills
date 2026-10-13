"""Which task a ``wev exec`` command acts for, and what the task's agent may run.

In plan mode nothing changes: the policy accepts read-only commands only. In an execute run
a command acts for a task that is RUNNING, because the task decides the risk the command
runs under and whose permissions apply:

- ``--task`` must name a running task; pending, finished and unknown ids are refused with
  the running tasks named.
- Without ``--task`` the only running task is used and the output says so. With none
  running, or with several, only a read-only command is accepted (and belongs to no task).

So an agent's ``may_mutate: false`` cannot be skipped by leaving ``--task`` out or by naming
a task that is not running. What stays open: with two tasks running, the caller chooses
which one a command is for; the engine cannot tell which agent is typing.

A read-only agent may also run, by exact argv, the task's declared checks and the check
commands discovered in the repository: running the test suite is how a reviewer verifies.
Those commands still go through the policy, so one that needs approval still needs it.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.core import agent_rules, progress, steps
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel, TaskStatus
from wev_skills.core.engine import Engine
from wev_skills.core.errors import PermissionDenied
from wev_skills.state.model import RunState

UNKNOWN_STATUS = "unknown"


@dataclass(frozen=True)
class ExecTarget:
    """The task a command acts for (``""`` for none) and the risk it runs under."""

    task_id: str
    risk: RiskLevel
    implied: bool = False
    """``--task`` was omitted and the only running task was used."""
    read_only: bool = False
    """The command is on the read-only list: it changes nothing, so it is not progress
    and does not count toward the no-progress window."""


def running_ids(state: RunState) -> list[str]:
    return [key for key, record in state.tasks.items() if record.status is TaskStatus.RUNNING]


def is_read_only(engine: Engine, state: RunState, argv: Sequence[str], risk: RiskLevel) -> bool:
    """What plan mode would accept: the read-only allowlist, with no write or run option."""
    decision = engine.services.policy.check_command(
        tuple(argv), engine.cwd(state), Mode.PLAN, risk, consume=False
    )
    return decision.outcome is not PermissionOutcome.DENY


def _refusal(
    code: str, state: RunState, running: Sequence[str], **params: object
) -> PermissionDenied:
    names = ", ".join(running) or i18n.t("orch.exec.none_running")
    message = i18n.t(f"orch.exec.{code}", running=names, **params)
    details = {
        "running": list(running),
        "next_step": f"wev task next --run {state.run_id}",
        **{key: str(value) for key, value in params.items()},
    }
    return PermissionDenied(f"exec_{code}", message, details)


def _named(state: RunState, task_id: str, running: Sequence[str]) -> str:
    if task_id in running:
        return task_id
    record = state.tasks.get(task_id)
    status = record.status.value if record is not None else UNKNOWN_STATUS
    raise _refusal("task_not_running", state, running, task=task_id, status=status)


def _run_risk(state: RunState) -> RiskLevel:
    return state.classification.risk if state.classification else RiskLevel.LOW


def _plan_mode(state: RunState, task_id: str | None) -> ExecTarget:
    """Plan mode: no task runs; a named task only labels the evidence."""
    if not task_id:
        return ExecTarget("", _run_risk(state), read_only=True)
    risk = progress.task_risk(state, progress.plan_task(state, task_id))
    return ExecTarget(task_id, risk, read_only=True)


def resolve(
    engine: Engine, state: RunState, task_id: str | None, argv: Sequence[str]
) -> ExecTarget:
    """The target of ``argv``; ``PermissionDenied`` when the rules above refuse it."""
    if state.mode is Mode.PLAN:
        return _plan_mode(state, task_id)
    running = running_ids(state)
    chosen = _named(state, task_id, running) if task_id else ""
    implied = not task_id and len(running) == 1
    chosen = running[0] if implied else chosen
    if chosen:
        risk = progress.task_risk(state, progress.plan_task(state, chosen))
        return ExecTarget(chosen, risk, implied, is_read_only(engine, state, argv, risk))
    if not is_read_only(engine, state, argv, _run_risk(state)):
        code = "task_required" if running else "no_running_task"
        raise _refusal(code, state, running, command=engine.clean(shlex.join(argv)))
    return ExecTarget("", _run_risk(state), read_only=True)


def verification_commands(engine: Engine, state: RunState, task_id: str) -> set[tuple[str, ...]]:
    """Argvs a read-only agent may run to verify: the task's checks and the discovered ones."""
    declared = engine.contract(state, task_id).checks
    discovered = tuple(suggestion.command for suggestion in steps.suggestions_of(state))
    found: set[tuple[str, ...]] = set()
    for command in (*declared, *discovered):
        try:
            found.add(tuple(shlex.split(command)))
        except ValueError:
            continue
    return found - {()}


def refuse_read_only_agent(
    engine: Engine, state: RunState, target: ExecTarget, argv: Sequence[str]
) -> None:
    """An agent whose spec says ``may_mutate: false`` runs read-only commands and the
    verification commands of its task; everything else is refused."""
    spec = engine.spec_of(state, target.task_id) if target.task_id else None
    if spec is None or agent_rules.permissions_of(spec).may_mutate or target.read_only:
        return
    if state.mode is not Mode.PLAN and tuple(argv) in verification_commands(
        engine, state, target.task_id
    ):
        return
    message = i18n.t("orch.agent.read_only", agent=spec.id, task=target.task_id)
    details = {"task_id": target.task_id, "agent_id": spec.id}
    raise PermissionDenied("agent_read_only", message, details)
