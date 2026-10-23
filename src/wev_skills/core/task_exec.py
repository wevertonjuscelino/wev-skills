"""EXECUTE: run one command through the engine and record what happened."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from wev_skills import i18n
from wev_skills.core import exec_target, progress, run_budget, steps
from wev_skills.core.baseline import log_entry
from wev_skills.core.contracts import (
    EvidenceLabel,
    GuardAction,
    RiskLevel,
    RunStatus,
    TaskStatus,
)
from wev_skills.core.engine import REQUESTER, Engine
from wev_skills.core.errors import ApprovalRequired, GuardTripped, PermissionDenied
from wev_skills.execution.executor import CommandRecord, to_evidence, to_guard_event
from wev_skills.guards.events import GuardEvent, GuardEventKind, budget_event, progress_event
from wev_skills.security.redact import redact_argv
from wev_skills.state.model import RunState, with_command, with_evidence, with_guard_event

EXIT_PASSED = 0
EXIT_NOT_PASSED = 1
COMMAND_UNITS = 1.0
"""Budget units one command costs."""


def last_fingerprint(state: RunState, task_id: str) -> str:
    """The tree fingerprint of the latest progress event recorded for ``task_id``."""
    events = progress.guard_events(state, task_id)
    seen = [event.fingerprint for event in events if event.kind is GuardEventKind.PROGRESS]
    return seen[-1] if seen else ""


def progress_events(
    state: RunState, task_id: str, at: float, before: str, after: str
) -> tuple[list[GuardEvent], list[GuardEvent]]:
    """Progress events to record ``(ahead of the command, after it)``.

    The tree is compared with the last fingerprint recorded for the task. A change made
    between two commands (an edit) is progress ahead of the second one, so repeating a test
    while editing is not a loop; a command that itself changes the tree is progress after it.
    """
    ahead = (
        [progress_event(task_id, at, before)] if before != last_fingerprint(state, task_id) else []
    )
    behind = [progress_event(task_id, at, after)] if after != before else []
    return ahead, behind


def _ask_for_approval(
    engine: Engine,
    argv: Sequence[str],
    target: str,
    risk: RiskLevel,
    exc: ApprovalRequired,
) -> ApprovalRequired:
    """Create the request a human can grant, note it in the state, and name that request.

    A grant that ``HEAD`` or the tree has outgrown (``approval_anchor``) is named as stale.
    """
    cwd = str(exc.details.get("cwd", ""))
    stale = engine.services.approvals.is_stale(tuple(argv), cwd)
    message = i18n.t("security.approval.stale_grant", reason=exc.message) if stale else exc.message
    request = engine.services.approvals.request(
        tuple(argv), risk, engine.clean(exc.message), REQUESTER, cwd
    )
    engine.commit(
        lambda current: engine.note_approval(current, request.id, target, progress.KIND_COMMAND),
        "exec.approval_requested",
        {"approval_id": request.id, "argv": list(redact_argv(argv)), "task_id": target},
    )
    step = steps.approval_step(request.id)
    details = {
        "approval_id": request.id,
        "reason": message,
        "next_step": step,
        "next_steps": [step],
        **({"stale_grant": True} if stale else {}),
    }
    return ApprovalRequired("approval_required", message, details)


def polling_accepted(state: RunState, task_id: str | None, target: str) -> bool:
    """``--polling`` counts only for a named RUNNING task that already launched something.

    The engine cannot see a process. What it can check is that the caller named the task,
    that the task is running, and that a command was already recorded for it since it
    started (so there is something to wait for); otherwise the command is counted like any
    other. The guard caps consecutive polls (``limits.max_polling_commands``).
    """
    if task_id is None or not target or state.tasks[target].status is not TaskStatus.RUNNING:
        return False
    started = state.tasks[target].started_at
    return any(
        entry.task_id == target and not entry.baseline and entry.at >= started
        for entry in state.commands
    )


def _run(
    engine: Engine,
    state: RunState,
    argv: Sequence[str],
    target: str,
    risk: RiskLevel,
    timeout: float | None,
) -> CommandRecord:
    executor = engine.services.executor(engine.log_dir())
    try:
        return executor.run(
            tuple(argv),
            engine.cwd(state),
            state.mode,
            risk,
            timeout=timeout,
            task_id=target or None,
        )
    except ApprovalRequired as exc:
        raise _ask_for_approval(engine, argv, target, risk, exc) from exc
    except PermissionDenied as exc:
        denied = {"run_id": state.run_id, "argv": list(redact_argv(argv)), "reason": exc.message}
        engine.services.audit.append("exec.denied", denied)
        raise


def _task_fields(found: exec_target.ExecTarget) -> dict[str, Any]:
    """Which task the command ran for, and a note when it was not named by the caller."""
    fields: dict[str, Any] = {"task_id": found.task_id, "task_implied": found.implied}
    if not found.implied:
        return fields
    return {**fields, "task_note": i18n.t("orch.exec.task_implied", task=found.task_id)}


def exec_command(
    engine: Engine,
    argv: Sequence[str],
    task_id: str | None,
    timeout: float | None,
    polling: bool,
    flaky: bool,
) -> tuple[dict[str, Any], int]:
    """Run one command through the executor; returns the payload and the exit code to use."""
    state = engine.reconciled(engine.load())
    found = exec_target.resolve(engine, state, task_id, argv)
    target, risk = found.task_id, found.risk
    engine.refuse_tripped(state, target or None)
    exec_target.refuse_read_only_agent(engine, state, found, argv)
    accepted = polling and polling_accepted(state, task_id, target)
    run_budget.require(engine, state, units=COMMAND_UNITS)
    before = engine.fingerprint(state)
    record = _run(engine, state, argv, target, risk, timeout)
    after_tree = engine.fingerprint(state)
    event = to_guard_event(record, polling=accepted, flaky=flaky, read_only=found.read_only)
    ran = record.status in (RunStatus.PASSED, RunStatus.FAILED)
    label = EvidenceLabel.TESTED if ran else EvidenceLabel.UNTESTED

    def change(current: RunState) -> RunState:
        ahead, behind = progress_events(current, target, event.at, before, after_tree)
        spent = budget_event(target, event.at, COMMAND_UNITS)
        moved = with_command(current, log_entry(record, target))
        for item in (*ahead, event, spent, *behind):
            moved = with_guard_event(moved, item.to_dict())
        moved = engine.reconciled(moved)
        return with_evidence(moved, target, to_evidence(record, label)) if target else moved

    data = {"task_id": target, "argv": list(record.argv), "status": record.status.value}
    after = engine.commit(change, "exec.ran", {**data, "exit_code": record.exit_code})
    verdict = engine.task_verdict(after, target, now=event.at)
    payload = {
        "run_id": after.run_id,
        **_task_fields(found),
        "record": record.to_dict(),
        "guard": verdict.to_dict(),
        "polling": {"requested": polling, "accepted": accepted},
        **engine.step_fields(after),
    }
    if verdict.action is not GuardAction.CONTINUE:
        return payload, GuardTripped.exit_code
    return payload, EXIT_PASSED if record.status is RunStatus.PASSED else EXIT_NOT_PASSED
