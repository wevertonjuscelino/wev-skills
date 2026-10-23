"""VERIFY and REVIEW: record what an agent reports, and what an independent reviewer says.

What ``verified`` requires is in ``core.evidence``. Every start of a task counts against its
attempt limit; a task that fails on its last attempt becomes BLOCKED, and only a person can
reopen it (``core.task_reopen``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from wev_skills import i18n
from wev_skills.core import evidence as evidence_rules
from wev_skills.core import planning, progress, steps
from wev_skills.core.contracts import (
    AttemptRecord,
    EscalationDecision,
    Evidence,
    TaskResult,
    TaskStatus,
)
from wev_skills.core.engine import Change, Engine, set_assignment
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.guards.events import attempt_event
from wev_skills.state.model import (
    Phase,
    RunState,
    reopen,
    with_attempt,
    with_decision,
    with_guard_event,
    with_phase,
    with_result,
    with_task_status,
    without_blocker,
)
from wev_skills.state.records import ReviewRecord

SIGNATURE_LENGTH = 16
FAILED_CHECK = "failed"
UNFINISHED = (TaskStatus.FAILED, TaskStatus.PARTIAL, TaskStatus.BLOCKED)
SELF_DECLARED = "self-declared"
"""A reviewer is whoever the caller names; the engine cannot tell who really reviewed."""
_DIGITS = re.compile(r"\d+")


def error_signature(state: RunState, task_id: str, summary: str) -> str:
    """Stable short hash of what failed: the failing checks, else the normalized summary."""
    fresh = progress.fresh_verification(state, task_id)
    failing = [c for c in fresh.checks if c.state == FAILED_CHECK] if fresh else []
    if failing:
        basis = "\n".join(f"{' '.join(c.argv)}={c.exit_code}" for c in failing)
    else:
        basis = _DIGITS.sub("#", " ".join(summary.lower().split()))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:SIGNATURE_LENGTH]


def _next_model(engine: Engine, state: RunState, task_id: str, failures: int) -> str:
    task = progress.plan_task(state, task_id)
    record = state.tasks[task_id]
    services = engine.services
    spec = services.agents.resolved(record.agent_id)
    choice = planning.escalated_model(
        services.router, services.config.models, state, task, spec, record.model, failures
    )
    return choice.model


def _phase_after(state: RunState, task_id: str) -> Phase:
    if progress.run_complete(state):
        return Phase.DELIVER
    verified = state.tasks[task_id].status is TaskStatus.VERIFIED
    if verified and progress.review_required(state):
        return Phase.REVIEW
    return Phase.EXECUTE


def _escalation(
    engine: Engine, state: RunState, attempt: AttemptRecord
) -> tuple[EscalationDecision | None, str]:
    """For a failed attempt: what the provider decides and the next model if it escalates.

    The model moves up while attempts remain, so the stronger model actually runs.
    """
    if attempt.status is not TaskStatus.FAILED:
        return None, ""
    history = (*state.tasks[attempt.task_id].attempts, attempt)
    limit = engine.attempt_limit(state, attempt.task_id)
    decision = engine.services.provider.should_escalate(history, limit)
    if not decision.escalate or state.tasks[attempt.task_id].starts >= limit:
        return decision, ""
    failures = sum(1 for item in history if item.status is TaskStatus.FAILED)
    return decision, _next_model(engine, state, attempt.task_id, failures)


@dataclass(frozen=True)
class _Outcome:
    result: TaskResult
    attempt: AttemptRecord
    escalation: EscalationDecision | None
    next_model: str
    stale_blockers: tuple[str, ...]
    tree_changed: bool | None
    exhausted: bool
    fingerprint: str = ""


def _settle(state: RunState, outcome: _Outcome) -> RunState:
    """Note whether the tree changed; block the task when its last attempt did not succeed."""
    task_id = outcome.result.task_id
    record = replace(state.tasks[task_id], tree_changed=outcome.tree_changed)
    moved = replace(state, tasks={**state.tasks, task_id: record})
    if not outcome.exhausted:
        return moved
    if moved.tasks[task_id].status is not TaskStatus.BLOCKED:
        moved = with_task_status(moved, task_id, TaskStatus.BLOCKED)
    blocked = replace(moved.tasks[task_id], block_reason=progress.EXHAUSTED)
    return replace(moved, tasks={**moved.tasks, task_id: blocked})


def _apply(engine: Engine, outcome: _Outcome) -> Change:
    """The state change for one recorded outcome."""
    result, attempt, escalation = outcome.result, outcome.attempt, outcome.escalation
    task_id, now, stamp = result.task_id, engine.now(), engine.stamp()

    def change(current: RunState) -> RunState:
        moved = current
        for blocker in outcome.stale_blockers:
            moved = without_blocker(moved, blocker)
        moved = _settle(with_attempt(with_result(moved, result, stamp), attempt), outcome)
        event = attempt_event(
            task_id, now, result.status.value, attempt.error_signature, outcome.fingerprint
        )
        moved = with_guard_event(moved, event.to_dict())
        if escalation is not None:
            text = i18n.t("orch.decision.escalation", task=task_id, action=escalation.action.value)
            source = engine.services.provider.provider_id
            moved = with_decision(
                moved, engine.decision(Phase.EXECUTE, text, escalation.reasons, source)
            )
        if outcome.exhausted:
            text = i18n.t("orch.decision.exhausted", task=task_id, attempts=attempt.attempt)
            moved = with_decision(moved, engine.decision(Phase.EXECUTE, text))
        if outcome.next_model:
            agent_id = moved.tasks[task_id].agent_id
            moved = set_assignment(moved, task_id, agent_id, outcome.next_model)
        return with_phase(moved, _phase_after(moved, task_id))

    return change


def _refuse_bad_record(state: RunState, task_id: str, status: TaskStatus) -> None:
    """``failed`` is the outcome of an attempt, so it needs a task that is RUNNING. A task
    that used all its attempts stays blocked until a person reopens it: recording it
    ``not_executed`` would only make that disappear from the report."""
    current = state.tasks[task_id].status
    if status is TaskStatus.FAILED and current is not TaskStatus.RUNNING:
        message = i18n.t("orch.error.not_running", task=task_id, status=current.value)
        raise ValidationError("task_not_running", message, {"task_id": task_id})
    if status is TaskStatus.NOT_EXECUTED and progress.exhausted(state, task_id):
        message = i18n.t("orch.error.exhausted_record", task=task_id)
        details = {"task_id": task_id, "next_step": steps.reopen_step(state, task_id)}
        raise ValidationError("attempts_exhausted", message, details)


def _outcome(
    engine: Engine,
    state: RunState,
    result: TaskResult,
    fingerprint: str,
) -> _Outcome:
    task_id, status = result.task_id, result.status
    record = state.tasks[task_id]
    last = record.attempts[-1].attempt if record.attempts else 0
    number = max(last + 1, record.starts)
    signature = (
        error_signature(state, task_id, result.summary) if status is TaskStatus.FAILED else ""
    )
    attempt = AttemptRecord(task_id, number, status, record.model, signature)
    escalation, next_model = _escalation(engine, state, attempt)
    running = record.status is TaskStatus.RUNNING
    used_up = record.starts >= engine.attempt_limit(state, task_id)
    changed = None if record.baseline is None else fingerprint != record.baseline.fingerprint
    stale = record.result.blockers if record.result else ()
    exhausted = running and used_up and status in UNFINISHED
    return _Outcome(result, attempt, escalation, next_model, stale, changed, exhausted, fingerprint)


def record_task(
    engine: Engine,
    task_id: str,
    status: TaskStatus,
    summary: str,
    changed_files: Sequence[str],
    blockers: Sequence[str],
    evidence: Sequence[Evidence],
) -> dict[str, Any]:
    """Record the reported outcome; ``verified`` is refused without evidence on this tree."""
    state = engine.load()
    progress.task_record(state, task_id)
    _refuse_bad_record(state, task_id, status)
    manual = evidence_rules.checked_evidence(engine, state, evidence, task_id)
    fingerprint = engine.fingerprint(state)
    if status is TaskStatus.VERIFIED:
        evidence_rules.require_evidence(state, engine.contract(state, task_id), manual)
        evidence_rules.require_same_tree(state, task_id, fingerprint)
    result = TaskResult(
        task_id,
        status,
        engine.clean(summary),
        manual,
        tuple(engine.clean(path) for path in changed_files),
        tuple(engine.clean(blocker) for blocker in blockers),
    )
    outcome = _outcome(engine, state, result, fingerprint)
    attempt, escalation = outcome.attempt, outcome.escalation
    data = {
        "task_id": task_id,
        "status": status.value,
        "attempt": attempt.attempt,
        "summary": result.summary,
    }
    after = engine.commit(_apply(engine, outcome), "task.recorded", data, base=state)
    return {
        "run_id": after.run_id,
        "task_id": task_id,
        "status": after.tasks[task_id].status.value,
        "reported_status": status.value,
        "attempt": attempt.attempt,
        "attempts_exhausted": outcome.exhausted,
        "tree_changed": outcome.tree_changed,
        "error_signature": attempt.error_signature,
        "escalation": escalation.to_dict() if escalation else None,
        "recommended_action": escalation.action.value if escalation else None,
        "next_model": outcome.next_model or None,
        **engine.step_fields(after),
    }


def review_task(
    engine: Engine, task_id: str, reviewer: str, accepted: bool, summary: str
) -> dict[str, Any]:
    """Record an independent review; a rejection reopens the task with the summary as context."""
    state = engine.load()
    record = progress.task_record(state, task_id)
    if reviewer not in engine.services.agents.registry:
        message = i18n.t("orch.error.unknown_reviewer", reviewer=reviewer)
        raise ValidationError("unknown_reviewer", message, {"reviewer": reviewer})
    if reviewer == record.agent_id:
        message = i18n.t("orch.error.self_review", reviewer=reviewer, task=task_id)
        raise PermissionDenied("self_review", message, {"reviewer": reviewer, "task_id": task_id})
    if record.status is not TaskStatus.VERIFIED:
        message = i18n.t("orch.error.review_unverified", task=task_id, status=record.status.value)
        raise ValidationError("task_not_verified", message, {"task_id": task_id})
    stamp, text = engine.stamp(), engine.clean(summary)
    review = ReviewRecord(
        task_id, stamp, reviewer, accepted, text, progress.recorded_tree(state, task_id)
    )
    verdict = "accept" if accepted else "reject"
    note = i18n.t("orch.decision.review", task=task_id, reviewer=reviewer, verdict=verdict)

    def change(current: RunState) -> RunState:
        moved = replace(current, reviews=(*current.reviews, review))
        moved = with_decision(moved, engine.decision(Phase.REVIEW, note, (text,), reviewer))
        if not accepted:
            moved = reopen(moved, task_id, stamp, text or note)
        return with_phase(moved, _phase_after(moved, task_id))

    data = {"task_id": task_id, "reviewer": reviewer, "verdict": verdict, "summary": text}
    after = engine.commit(change, "task.reviewed", data, base=state)
    return {
        "run_id": after.run_id,
        "task_id": task_id,
        "reviewer": reviewer,
        "reviewer_identity": SELF_DECLARED,
        "verdict": verdict,
        "task_status": after.tasks[task_id].status.value,
        "complete": progress.task_complete(after, task_id),
        **engine.step_fields(after),
    }
