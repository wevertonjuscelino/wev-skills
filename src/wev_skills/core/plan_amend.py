"""Plan changes after work has started: refused unless they are a recorded amendment.

Once a task has ever been started, its acceptance criteria, checks, ``read_only`` flag, risk
and files are what its work is being judged against. ``plan set`` refuses to change them
unless the caller passes ``--amend --reason TEXT``. An amendment is recorded (a decision, a
``plan.amended`` audit event and an entry the delivery report lists with before and after)
and resets the task's verification: a running task must be checked again and a verified one
goes back to pending. This records the change; it does not prevent it: whoever can run
``plan set`` can amend. Adding tasks and changing tasks that never started stays free.
"""

from __future__ import annotations

from dataclasses import replace

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import Plan, PlanTask, TaskStatus
from wev_skills.core.engine import Engine, restamp_started
from wev_skills.core.errors import ValidationError
from wev_skills.state.model import RunState, TaskRecord, reopen, with_decision
from wev_skills.state.records import FieldChange, PlanAmendment

SOURCE = "plan-amend"
EVENT = "plan.amended"
GUARDED_FIELDS = ("acceptance_criteria", "checks", "check_links", "read_only", "risk", "files")
AMEND_STEP = "wev plan set --file <plan.json> --amend --reason <text> --run {run}"

Changes = dict[str, tuple[FieldChange, ...]]


def ever_started(record: TaskRecord) -> bool:
    """The task was started at least once, even if a person reopened it since."""
    waiting = record.status in progress.WAITING
    return record.starts > 0 or bool(record.attempts) or bool(record.started_at) or not waiting


def _shown(task: PlanTask, field: str) -> tuple[str, ...]:
    """One guarded field as text, the way the report prints it."""
    value = getattr(task, field)
    if field == "check_links":
        return tuple(f"{link.command} => {'; '.join(link.criteria)}" for link in value)
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    return (str(getattr(value, "value", value)).lower(),)


def _task_changes(old: PlanTask, new: PlanTask) -> tuple[FieldChange, ...]:
    pairs = ((name, _shown(old, name), _shown(new, name)) for name in GUARDED_FIELDS)
    return tuple(
        FieldChange(name, before, after) for name, before, after in pairs if before != after
    )


def changes(state: RunState, plan: Plan) -> Changes:
    """Guarded fields the new plan changes, per task that has ever been started."""
    current = {task.id: task for task in (state.plan.tasks if state.plan else ())}
    found: Changes = {}
    for task in plan.tasks:
        record = state.tasks.get(task.id)
        if task.id not in current or record is None or not ever_started(record):
            continue
        changed = _task_changes(current[task.id], task)
        if changed:
            found[task.id] = changed
    return found


def refuse_unamended(state: RunState, found: Changes, reason: str | None) -> None:
    """Without ``--amend`` a change to a started task is refused; with it a reason is needed."""
    if reason is not None and not reason.strip():
        raise ValidationError("amend_reason_required", i18n.t("orch.error.amend_reason"))
    if not found or reason is not None:
        return
    listed = "; ".join(
        f"{task_id} ({', '.join(change.field for change in items)})"
        for task_id, items in found.items()
    )
    details = {
        "changes": {
            task_id: {change.field: change.to_dict() for change in items}
            for task_id, items in found.items()
        },
        "next_step": AMEND_STEP.format(run=state.run_id),
    }
    message = i18n.t("orch.error.plan_amendment", tasks=listed)
    raise ValidationError("plan_amendment_required", message, details)


def _reset(state: RunState, task_id: str, stamp: str, note: str) -> RunState:
    """What was verified was verified against the old plan: it has to be shown again."""
    status = state.tasks[task_id].status
    if status is TaskStatus.VERIFIED:
        return reopen(state, task_id, stamp, note)
    return restamp_started(state, task_id, stamp) if status is TaskStatus.RUNNING else state


def apply(engine: Engine, state: RunState, found: Changes, reason: str) -> RunState:
    """Record one amendment per task (with a decision) and reset each task's verification."""
    stamp, text = engine.stamp(), engine.clean(reason).strip()
    moved = state
    for task_id, items in found.items():
        fields = ", ".join(change.field for change in items)
        note = i18n.t("orch.decision.amended", task=task_id, fields=fields)
        status = moved.tasks[task_id].status.value
        amendment = PlanAmendment(stamp, task_id, text, items, status)
        moved = replace(moved, plan_amendments=(*moved.plan_amendments, amendment))
        moved = _reset(moved, task_id, stamp, note)
        moved = with_decision(moved, engine.decision(moved.phase, note, (text,), SOURCE))
    return moved


def audit_data(found: Changes, reason: str) -> dict[str, object]:
    return {
        "reason": reason,
        "tasks": {
            task_id: [change.to_dict() for change in items] for task_id, items in found.items()
        },
    }
