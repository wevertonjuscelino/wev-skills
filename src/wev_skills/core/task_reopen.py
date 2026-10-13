"""Human reopening of a task: the only way forward once its attempts are used up."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import TaskStatus
from wev_skills.core.engine import Engine
from wev_skills.core.errors import ValidationError
from wev_skills.guards.events import reset_event
from wev_skills.state.model import RunState, reopen, with_guard_event, without_blocker

SOURCE = "task-reopen"
NOT_REOPENABLE = (TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING)


def reopen_task(
    engine: Engine, task_id: str, reason: str, operator: str, confirmation: str
) -> dict[str, Any]:
    """Send a task back to PENDING with its attempt count reset, on a person's say-so.

    The attempt history stays in the record; the count that the limit applies to starts
    again from zero, and the guard counts the task's events afresh. Only the CLI command,
    which demands a person, should call this.
    """
    text = engine.clean(reason).strip()
    if not text:
        raise ValidationError("reason_required", i18n.t("orch.error.reopen_reason"))
    state = engine.load()
    record = progress.task_record(state, task_id)
    if record.status in NOT_REOPENABLE:
        message = i18n.t("orch.error.not_reopenable", task=task_id, status=record.status.value)
        raise ValidationError("task_not_reopenable", message, {"task_id": task_id})
    stamp, now = engine.stamp(), engine.now()
    previous = record.starts
    note = i18n.t("orch.decision.reopened", operator=operator, reason=text, attempts=previous)

    def change(current: RunState) -> RunState:
        moved = current
        old = current.tasks[task_id].result
        for blocker in old.blockers if old else ():
            moved = without_blocker(moved, blocker)
        moved = reopen(moved, task_id, stamp, engine.clean(note))
        fresh = replace(
            moved.tasks[task_id], starts=0, block_reason="", baseline=None, tree_changed=None
        )
        moved = replace(moved, tasks={**moved.tasks, task_id: fresh})
        return with_guard_event(moved, reset_event(task_id, now).to_dict())

    audit = {
        "task_id": task_id,
        "reason": text,
        "operator": operator,
        "confirmation": confirmation,
        "previous_attempts": previous,
    }
    after = engine.commit(change, "task.reopened", audit, base=state)
    return {
        "run_id": after.run_id,
        **audit,
        "status": after.tasks[task_id].status.value,
        **engine.step_fields(after),
    }
