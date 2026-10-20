"""EXECUTE, first half: which tasks may start now, and starting one."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.core import (
    agent_rules,
    baseline,
    plan_flow,
    planning,
    progress,
    run_budget,
    shown_lessons,
    steps,
    tool_select,
)
from wev_skills.core.contracts import Mode, PlanTask, TaskStatus
from wev_skills.core.engine import REQUESTER, Change, Engine, refuse_finished, task_action
from wev_skills.core.errors import ApprovalRequired, PermissionDenied, ValidationError
from wev_skills.core.task_contract import lessons_shown
from wev_skills.governance.approvals import ApprovalStatus, approval_id
from wev_skills.guards.events import handoff_event
from wev_skills.state.model import (
    Phase,
    RunState,
    with_decision,
    with_guard_event,
    with_phase,
    with_task_status,
    without_pending_approval,
)
from wev_skills.verification.engine import checks_from_contract


def _refuse_plan_mode(state: RunState) -> None:
    refuse_finished(state)
    if state.mode is Mode.PLAN:
        step = steps.next_step(state)
        raise PermissionDenied("plan_mode", i18n.t("orch.error.plan_mode"), {"next_step": step})


def _with_plan(engine: Engine, state: RunState) -> RunState:
    """The state with a plan: a single synthesized task when the strategy needs no plan.

    A run that needs no plan still needs something to check the work with. When no check
    was discovered, the caller must supply them in a plan; a task without checks could
    never be verified.
    """
    if state.plan is not None:
        return state
    step = f"wev plan set --file {steps.PLAN_FILE} --run {state.run_id}"
    if state.strategy is None or state.strategy.needs_plan:
        raise ValidationError(
            "plan_required", i18n.t("orch.error.plan_required"), {"next_step": step}
        )
    if steps.needs_checks(state):
        message = i18n.t("orch.hint.supply_checks")
        raise ValidationError("checks_required", message, {"next_step": step})
    return plan_flow.adopt_plan(engine, planning.synthesize_plan(state), "plan.synthesized")


def _request_approval(engine: Engine, state: RunState, task: PlanTask) -> str:
    reason = i18n.t("orch.approval.task_reason", task=task.id, title=task.title)
    action = task_action(state.run_id, task.id)
    request = engine.services.approvals.request(
        action, progress.task_risk(state, task), engine.clean(reason), REQUESTER
    )
    return request.id


def _split_awaiting(
    engine: Engine, state: RunState, awaiting: list[PlanTask]
) -> tuple[dict[str, str], dict[str, str]]:
    """Approval id per task now pending, and tasks whose approval a human denied."""
    pending: dict[str, str] = {}
    denied: dict[str, str] = {}
    for task in awaiting:
        status = engine.approval_status(task_action(state.run_id, task.id))
        if status is ApprovalStatus.DENIED:
            denied[task.id] = i18n.t("orch.defer.denied", task=task.id)
        else:
            pending[task.id] = _request_approval(engine, state, task)
    return pending, denied


def next_tasks(engine: Engine) -> dict[str, Any]:
    """Contracts of the tasks that may start now; refuses in plan mode or on a guard trip."""
    initial = engine.load()
    _refuse_plan_mode(initial)
    state = engine.reconciled(_with_plan(engine, initial))
    engine.refuse_tripped(state)
    approvals = engine.services.approvals
    offered, awaiting, deferred = planning.select_startable(
        state,
        lambda task: approvals.is_granted(task_action(state.run_id, task.id)),
        lambda task_id: engine.attempt_limit(state, task_id),
    )
    pending, denied = _split_awaiting(engine, state, awaiting)
    step = f"wev task start {offered[0].id} --run {state.run_id}" if offered else None
    tools = tool_select.compute(engine, state, [task.id for task in offered])

    def change(current: RunState) -> RunState:
        moved = tool_select.store(engine, engine.reconciled(current), tools)
        for task in offered:
            if moved.tasks[task.id].status is TaskStatus.PENDING:
                moved = with_task_status(moved, task.id, TaskStatus.READY)
        for task_id, pending_id in pending.items():
            moved = engine.note_approval(moved, pending_id, task_id, progress.KIND_TASK)
        return with_phase(moved, Phase.EXECUTE)

    ids = list(pending.values())
    data = {"offered": [task.id for task in offered], "pending_approvals": ids}
    after = engine.commit(change, "task.next", data, step, base=state)
    fields = engine.step_fields(after, step)
    if not offered and ids:
        details = {"approval_ids": ids, **fields}
        message = i18n.t("orch.error.approval", ids=", ".join(ids))
        raise ApprovalRequired("approval_required", message, details)
    return {
        "run_id": after.run_id,
        "tasks": [engine.contract(after, task.id).to_dict() for task in offered],
        "awaiting_approval": ids,
        "deferred": [{"task_id": k, "reason": v} for k, v in {**deferred, **denied}.items()],
        **fields,
    }


def _approval_needed(engine: Engine, state: RunState, task: PlanTask) -> tuple[str, ...] | None:
    """The action whose grant the start will spend; ``ApprovalRequired`` when not granted.

    Nothing is spent here: the grant is consumed inside the write that marks the task
    RUNNING, so a start that loses a race does not burn the approval.
    """
    if not progress.needs_approval(state, task):
        return None
    action = task_action(state.run_id, task.id)
    if engine.services.approvals.is_granted(action):
        return action
    if engine.approval_status(action) is ApprovalStatus.DENIED:
        denied = approval_id(action)
        refused = {
            "task_id": task.id,
            "approval_id": denied,
            "next_step": steps.denied_step(state, task.id, denied),
        }
        message = i18n.t("orch.error.gate_denied", task=task.id, id=denied)
        raise PermissionDenied("approval_denied", message, refused)
    pending = _request_approval(engine, state, task)
    engine.commit(
        lambda current: engine.note_approval(current, pending, task.id, progress.KIND_TASK),
        "task.approval_requested",
        {"task_id": task.id, "approval_id": pending},
    )
    step = steps.approval_step(pending)
    details = {"approval_ids": [pending], "next_step": step, "next_steps": [step]}
    raise ApprovalRequired("approval_required", i18n.t("orch.error.approval", ids=pending), details)


def _refuse_unstartable(engine: Engine, state: RunState, task: PlanTask) -> None:
    busy = [other for other in planning.running_tasks(state) if other.id != task.id]
    limit = engine.attempt_limit(state, task.id)
    problem = planning.startable_problem(
        state, task, busy, explicit=True, attempt_limit=lambda _task_id: limit
    )
    if problem is None:
        return
    details: dict[str, Any] = {"task_id": task.id}
    record = state.tasks[task.id]
    if record.starts >= limit and record.status not in progress.WAITING:
        details["next_step"] = steps.reopen_step(state, task.id)
        raise ValidationError("attempts_exhausted", problem, details)
    raise ValidationError("task_not_startable", problem, details)


def _refuse_agent(engine: Engine, state: RunState, task: PlanTask) -> None:
    """The assigned agent must still be allowed the run's mode and the task's risk."""
    spec = engine.spec_of(state, task.id)
    if spec is None:
        return
    problem = agent_rules.refusal(spec, state.mode, progress.task_risk(state, task))
    if problem is not None:
        details = {"task_id": task.id, "agent_id": spec.id}
        raise PermissionDenied("agent_not_permitted", problem, details)


def _mark_running(engine: Engine, state: RunState, task: PlanTask) -> tuple[RunState, int]:
    """One read-validate-write: validate against ``state`` and mark the task RUNNING."""
    checks = checks_from_contract(engine.contract(state, task.id))
    units = len(checks) if engine.services.config.harness.baseline_checks else 0
    run_budget.require(engine, state, units=units, attempts=1)
    _refuse_unstartable(engine, state, task)
    _refuse_agent(engine, state, task)
    action = _approval_needed(engine, state, task)
    record = state.tasks[task.id]
    attempt = record.starts + 1
    now, stamp = engine.now(), engine.stamp()
    tools = tool_select.compute(engine, state, [task.id])
    spec = engine.services.agents.resolved(record.agent_id)
    shown = lessons_shown(state, task, spec)
    text = i18n.t(
        "orch.decision.start",
        task=task.id,
        attempt=attempt,
        agent=record.agent_id,
        model=record.model,
    )

    def change(current: RunState) -> RunState:
        if action is not None and not engine.services.approvals.consume(action):
            pending = approval_id(action)
            message = i18n.t("orch.error.approval", ids=pending)
            raise ApprovalRequired("approval_required", message, {"approval_ids": [pending]})
        moved = with_task_status(current, task.id, TaskStatus.RUNNING, stamp)
        moved = tool_select.store(engine, moved, tools)
        started = replace(
            moved.tasks[task.id],
            starts=attempt,
            baseline=None,
            tree_changed=None,
        )
        moved = replace(moved, tasks={**moved.tasks, task.id: started})
        event = handoff_event(task.id, now, "orchestrator", record.agent_id)
        moved = with_guard_event(moved, event.to_dict())
        if action is not None:
            moved = without_pending_approval(moved, approval_id(action))
        return with_phase(with_decision(moved, engine.decision(Phase.EXECUTE, text)), Phase.EXECUTE)

    data = {
        "task_id": task.id,
        "attempt": attempt,
        "agent_id": record.agent_id,
        "model": record.model,
        "lessons_shown": list(shown),
    }
    return _commit_start(engine, state, change, data), attempt


def _commit_start(
    engine: Engine, state: RunState, change: Change, data: dict[str, Any]
) -> RunState:
    """Commit the start, then record the shown lessons, while the agent's lessons are still
    those its contract shows (see ``shown_lessons``). The start stands when only the record
    fails: that start goes uncounted and the failure is audited."""
    with shown_lessons.current_lessons(engine.services, data["agent_id"]):
        committed = engine.commit(change, "task.started", data, base=state)
        try:
            shown_lessons.record(engine.store, data)
        except OSError as exc:
            failure = {"run_id": committed.run_id, "task_id": data["task_id"], "error": str(exc)}
            engine.services.audit.append("lessons.shown_failed", failure)
    return committed


def start_task(engine: Engine, task_id: str) -> dict[str, Any]:
    """Mark a task RUNNING under the same rules ``next_tasks`` applies, and hand it off.

    The baseline (the task's checks, run before any work) is taken after the task is
    marked RUNNING, so a start that loses a race runs nothing.
    """
    state = engine.load()
    _refuse_plan_mode(state)
    task = progress.plan_task(state, task_id)
    engine.refuse_tripped(state)
    started, attempt = _mark_running(engine, state, task)
    after = baseline.take(engine, started, task_id)
    record = after.tasks[task_id]
    taken = record.baseline
    return {
        "run_id": after.run_id,
        "task_id": task_id,
        "status": record.status.value,
        "attempt": attempt,
        "agent_id": record.agent_id,
        "model": record.model,
        "baseline": taken.to_dict() if taken else None,
        "contract": engine.contract(after, task_id).to_dict(),
        **engine.step_fields(after),
    }
