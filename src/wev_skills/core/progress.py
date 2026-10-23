"""Pure questions about a run state: risk, freshness of evidence, approvals, guard verdict.

What to do next is answered in ``core.steps``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from wev_skills import i18n
from wev_skills.core import contracts
from wev_skills.core.contracts import GuardAction, PlanTask, RiskLevel, TaskStatus, higher_risk
from wev_skills.core.errors import NotFound
from wev_skills.guards.events import GuardEvent, GuardEventKind, effective_events
from wev_skills.guards.execution import RULE_NONE, SEVERITY, GuardLimits, GuardVerdict, evaluate
from wev_skills.state.model import RunState, TaskRecord
from wev_skills.state.records import ApprovalNote, ReviewRecord, VerificationRecord

RISK_RANK = contracts.RISK_RANK
"""Alias of the one table in ``core.contracts``, kept for callers outside the core."""
__all__ = ["RISK_RANK", "RULE_NONE"]
LimitsFor = Callable[[str], GuardLimits]
EXHAUSTED = "attempts_exhausted"
"""``TaskRecord.block_reason`` of a task blocked because it used every attempt."""
KIND_TASK, KIND_COMMAND = "task", "command"
BLOCKING_ACTIONS = (GuardAction.STOP, GuardAction.ASK_HUMAN)
IDENTICAL_RULE = "identical_commands"
IGNORED_LOOP_RULE = "ignored_loop"
IGNORED_LOOP_LIMIT = 2
"""Consecutive commands that leave the identical-command rule tripped before a human is asked."""
SETTLED = (TaskStatus.VERIFIED, TaskStatus.NOT_EXECUTED)
STARTED = (
    TaskStatus.RUNNING,
    TaskStatus.PARTIAL,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED,
    TaskStatus.VERIFIED,
)
RETRYABLE = (TaskStatus.FAILED, TaskStatus.PARTIAL)
WAITING = (TaskStatus.PENDING, TaskStatus.READY)
VERIFIED_VALUE = TaskStatus.VERIFIED.value


def plan_task(state: RunState, task_id: str) -> PlanTask:
    tasks = state.plan.tasks if state.plan else ()
    for task in tasks:
        if task.id == task_id:
            return task
    raise NotFound(
        "unknown_task", i18n.t("orch.error.unknown_task", task=task_id), {"task_id": task_id}
    )


def task_record(state: RunState, task_id: str) -> TaskRecord:
    plan_task(state, task_id)
    return state.tasks[task_id]


def task_risk(state: RunState, task: PlanTask) -> RiskLevel:
    """The higher of the run classification and the task's own risk."""
    run_risk = state.classification.risk if state.classification else RiskLevel.LOW
    return higher_risk(task.risk, run_risk)


def needs_approval(state: RunState, task: PlanTask) -> bool:
    gated = state.strategy is not None and state.strategy.needs_approval
    return gated or task_risk(state, task) is RiskLevel.HIGH


def latest_verification(state: RunState, task_id: str) -> VerificationRecord | None:
    found = [v for v in state.verifications if v.task_id == task_id]
    return found[-1] if found else None


def fresh_verification(state: RunState, task_id: str) -> VerificationRecord | None:
    """The latest verification, only when it was produced after the task last started."""
    latest = latest_verification(state, task_id)
    started = state.tasks[task_id].started_at if task_id in state.tasks else ""
    if latest is None or not started or latest.at <= started:
        return None
    return latest


def latest_review(state: RunState, task_id: str) -> ReviewRecord | None:
    found = [r for r in state.reviews if r.task_id == task_id]
    return found[-1] if found else None


def review_required(state: RunState) -> bool:
    return state.strategy is not None and state.strategy.needs_independent_review


def review_accepted(state: RunState, task_id: str) -> bool:
    review = latest_review(state, task_id)
    record = state.tasks.get(task_id)
    if review is None or record is None or not review.accepted:
        return False
    # The tree the task recorded must still be the one the reviewer saw, and a redone
    # task needs a new review even when its tree comes out identical.
    bound = review.fingerprint and review.fingerprint == recorded_tree(state, task_id)
    return bool(bound) and review.at >= record.finished_at


def task_complete(state: RunState, task_id: str) -> bool:
    """VERIFIED and, when the strategy asks for it, accepted by an independent reviewer."""
    record = state.tasks.get(task_id)
    if record is None or record.status is not TaskStatus.VERIFIED:
        return False
    return not review_required(state) or review_accepted(state, task_id)


def lacks_work(state: RunState, task: PlanTask) -> bool:
    """VERIFIED although no file changed since the task started, and it is not read-only."""
    record = state.tasks.get(task.id)
    if record is None or record.status is not TaskStatus.VERIFIED or task.read_only:
        return False
    return record.tree_changed is False


def run_complete(state: RunState) -> bool:
    """Every task verified (and reviewed when required), each with work to show for it."""
    tasks = state.plan.tasks if state.plan else ()
    done = all(task_complete(state, task.id) for task in tasks)
    return bool(tasks) and done and not any(lacks_work(state, task) for task in tasks)


def nothing_left(state: RunState) -> bool:
    """No task can still be worked on: each is complete or was deliberately not executed."""
    tasks = state.plan.tasks if state.plan else ()
    return bool(tasks) and all(
        task_complete(state, task.id) or state.tasks[task.id].status is TaskStatus.NOT_EXECUTED
        for task in tasks
    )


def exhausted(state: RunState, task_id: str) -> bool:
    record = state.tasks.get(task_id)
    return record is not None and record.block_reason == EXHAUSTED


def _note_is_stale(state: RunState, note: ApprovalNote) -> bool:
    """Nothing waits for the approval any more: its task is gone from the plan or settled,
    or (for a command) the task's checks all passed in a verification made after it was
    asked, which happens when the check that needed it was replaced."""
    if not note.task_id:
        return False
    record = state.tasks.get(note.task_id)
    in_plan = state.plan is not None and any(t.id == note.task_id for t in state.plan.tasks)
    if record is None or not in_plan or record.status in SETTLED:
        return True
    fresh = fresh_verification(state, note.task_id)
    passed_since = fresh is not None and fresh.all_met and fresh.at > note.at
    return note.kind == KIND_COMMAND and passed_since


def _pending_notes(state: RunState) -> tuple[ApprovalNote, ...]:
    """One note per pending approval id; an id recorded without a note gets a bare one."""
    known = {note.id: note for note in state.approval_notes}
    return tuple(
        known.get(pending, ApprovalNote(pending, "", KIND_COMMAND, ""))
        for pending in state.pending_approvals
    )


def live_approvals(state: RunState) -> tuple[ApprovalNote, ...]:
    """Pending approvals something still waits for."""
    return tuple(note for note in _pending_notes(state) if not _note_is_stale(state, note))


def stale_approvals(state: RunState) -> tuple[ApprovalNote, ...]:
    """Pending approvals nothing waits for any more (a changed plan, a settled task)."""
    return tuple(note for note in _pending_notes(state) if _note_is_stale(state, note))


def verified_trees(state: RunState) -> list[tuple[str, str]]:
    """``(task id, tree fingerprint)`` of every ``verified`` record, oldest first."""
    found = []
    for event in state.guard_events:
        kind, status = event.get("kind"), event.get("status")
        fingerprint = str(event.get("fingerprint") or "")
        if kind == GuardEventKind.TASK_ATTEMPT.value and status == VERIFIED_VALUE and fingerprint:
            found.append((str(event.get("task_id", "")), fingerprint))
    return found


def recorded_tree(state: RunState, task_id: str) -> str:
    """The tree fingerprint of the task's last ``verified`` record, ``""`` when it has none."""
    found = [tree for owner, tree in verified_trees(state) if owner == task_id]
    return found[-1] if found else ""


def changed_after_verification(state: RunState, tree: str) -> tuple[str, ...]:
    """Verified tasks whose verification the tree no longer matches ("verified, then changed").

    The tree is compared with the one seen at the latest ``verified`` record of the run. A
    difference while a task is running is that task's work. Otherwise something changed
    after the last verification and the engine cannot tell what, so every verified task
    counts until its checks pass again on the tree as it is now.
    """
    seen = verified_trees(state)
    running = any(record.status is TaskStatus.RUNNING for record in state.tasks.values())
    if not tree or not seen or running or seen[-1][1] == tree:
        return ()
    tasks = state.plan.tasks if state.plan else ()
    verified = [t.id for t in tasks if state.tasks[t.id].status is TaskStatus.VERIFIED]
    return tuple(task_id for task_id in verified if not _passes_on(state, task_id, tree))


def _passes_on(state: RunState, task_id: str, tree: str) -> bool:
    latest = latest_verification(state, task_id)
    return latest is not None and latest.all_met and latest.fingerprint == tree


def unresolved_dependencies(state: RunState, task: PlanTask) -> tuple[str, ...]:
    return tuple(
        dep
        for dep in task.depends_on
        if dep not in state.tasks or state.tasks[dep].status is not TaskStatus.VERIFIED
    )


def guard_events(state: RunState, task_id: str | None = None) -> tuple[GuardEvent, ...]:
    recorded = (GuardEvent.from_dict(dict(event)) for event in state.guard_events)
    events = effective_events(recorded)
    return events if task_id is None else tuple(e for e in events if e.task_id == task_id)


def _identical_tripped(verdict: GuardVerdict) -> bool:
    others = verdict.details.get("other_rules", [])
    return verdict.rule == IDENTICAL_RULE or any(o.get("rule") == IDENTICAL_RULE for o in others)


def _ignored_loop_streak(events: Sequence[GuardEvent], limits: GuardLimits) -> int:
    """Trailing commands after each of which the identical-command rule was tripped."""
    streak = 0
    for end in range(len(events), 0, -1):
        if events[end - 1].kind is GuardEventKind.BUDGET:
            continue
        if events[end - 1].kind is not GuardEventKind.COMMAND:
            break
        if not _identical_tripped(evaluate(events[:end], limits, now=events[end - 1].at)):
            break
        streak += 1
        if streak >= IGNORED_LOOP_LIMIT:
            break
    return streak


def task_verdict(
    events: Sequence[GuardEvent],
    limits: GuardLimits,
    now: float | None = None,
    unresolved: Sequence[str] = (),
) -> GuardVerdict:
    """The guard verdict for one task's events.

    The guard itself only advises a change of strategy when a command repeats. When that
    advice is ignored (the rule stays tripped on consecutive commands), the verdict here
    becomes ASK_HUMAN so the orchestrator stops handing out work.
    """
    verdict = evaluate(events, limits, now=now, unresolved_dependencies=unresolved)
    if verdict.action in BLOCKING_ACTIONS or not _identical_tripped(verdict):
        return verdict
    no_timeout = replace(limits, task_timeout_seconds=None)
    if _ignored_loop_streak(events, no_timeout) < IGNORED_LOOP_LIMIT:
        return verdict
    reason = i18n.t("orch.guard.ignored_loop", limit=IGNORED_LOOP_LIMIT)
    details = {**verdict.details, "advised": verdict.action.value, "advised_rule": verdict.rule}
    reasons = (reason, *verdict.reasons)
    return GuardVerdict(GuardAction.ASK_HUMAN, IGNORED_LOOP_RULE, reasons, details)


def _budget_verdict(events: Sequence[GuardEvent], limits: GuardLimits) -> GuardVerdict:
    """The run-level budget: every command of every task counts against one total."""
    spent = tuple(event for event in events if event.kind is GuardEventKind.BUDGET)
    return evaluate(spent, replace(limits, task_timeout_seconds=None))


def run_verdict(
    state: RunState, limits: GuardLimits, now: float, task_limits: LimitsFor | None = None
) -> GuardVerdict:
    """The most severe verdict over every task that is not settled, plus the run budget.

    Events of settled tasks (verified, not executed) are history, not a live loop. Events
    recorded without a task are judged without the task timeout, which is per task.
    ``task_limits`` gives the limits of one task (its agent may lower them and set a budget
    of its own); ``limits.budget_units`` is the budget of the whole run.
    """
    everything = guard_events(state)
    groups: dict[str, list[GuardEvent]] = {}
    for event in everything:
        record = state.tasks.get(event.task_id)
        if record is None or record.status not in SETTLED:
            groups.setdefault(event.task_id, []).append(event)
    verdicts = [_budget_verdict(everything, limits)]
    unscoped = replace(limits, budget_units=None)
    for task_id, events in groups.items():
        known = task_id in state.tasks
        own = task_limits(task_id) if known and task_limits is not None else unscoped
        scoped = own if known else replace(own, task_timeout_seconds=None)
        verdicts.append(task_verdict(events, scoped, now=now if known else None))
    return min(verdicts, key=lambda verdict: SEVERITY.index(verdict.action))
