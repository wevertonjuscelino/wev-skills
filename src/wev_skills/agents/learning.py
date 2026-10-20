"""Deterministic observations from engine records, never from an agent's prose."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace

from wev_skills import i18n
from wev_skills.agents.experience import (
    ACTIVE,
    PROPOSED,
    PROPOSER,
    RETIRED,
    STALE,
    Lesson,
    LessonEvidence,
    RecordRef,
    check_key,
)
from wev_skills.core.contracts import TaskStatus
from wev_skills.state.model import RunState


def _id(key: tuple[str, ...]) -> str:
    return "lesson-" + hashlib.sha256("\0".join(key).encode()).hexdigest()[:24]


def _observations(state: RunState, agent_id: str) -> list[tuple[tuple[str, ...], bool, str, str]]:
    """Latest result per check/task in this run; baseline and trivial checks cannot teach."""
    found: dict[tuple[str, ...], tuple[tuple[str, ...], bool, str, str]] = {}
    tasks = {key for key, record in state.tasks.items() if record.agent_id == agent_id}
    for record in state.verifications:
        if record.task_id not in tasks:
            continue
        for check in record.checks:
            if check.trivial or check.state not in ("passed", "failed"):
                continue
            if check.state == "passed" and (
                not record.all_met or state.tasks[record.task_id].status is not TaskStatus.VERIFIED
            ):
                continue
            key = check_key(check.argv)
            found[key] = (key, check.state == "passed", record.task_id, record.at)
    for trip in state.guard_trips:
        if trip.task_id in tasks:
            key = ("guard", trip.rule)
            found[key] = (key, True, trip.task_id, trip.at)
    return list(found.values())


_UNVERIFIED = frozenset({TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.PARTIAL})


def _usage(states: Sequence[RunState], agent_id: str) -> dict[str, tuple[int, int]]:
    """Per lesson id: (ended verified, ended unverified) over the agent's tasks that ended."""
    found: dict[str, tuple[int, int]] = {}
    for state in states:
        for record in state.tasks.values():
            ended = record.status is TaskStatus.VERIFIED or record.status in _UNVERIFIED
            if record.agent_id != agent_id or not ended:
                continue
            good = int(record.status is TaskStatus.VERIFIED)
            for lesson_id in record.lessons_shown:
                verified, unverified = found.get(lesson_id, (0, 0))
                found[lesson_id] = (verified + good, unverified + 1 - good)
    return found


def derive(states: Sequence[RunState], agent_id: str, stale_after: int = 20) -> tuple[Lesson, ...]:
    """Rebuild counters from distinct persisted runs; replaying learning never increments them."""
    ordered = sorted({state.run_id: state for state in states}.values(), key=lambda s: s.created_at)
    lessons: dict[tuple[str, ...], Lesson] = {}
    last_seen: dict[tuple[str, ...], int] = {}
    for index, state in enumerate(ordered):
        for key, positive, task, stamp in _observations(state, agent_id):
            old = lessons.get(key)
            guard = key[0] == "guard"
            text = i18n.t(
                "agents.learning.guard" if guard else "agents.learning.check", rule=key[1]
            )
            evidence = LessonEvidence(
                state.run_id,
                task,
                (RecordRef("verification" if key[0] == "check" else "guard_trip", stamp),),
            )
            lesson = old or Lesson(
                _id(key),
                "pitfall" if guard else "practice",
                text,
                evidence,
                stamp,
                "engine",
                derivation="engine-records",
                key=key,
            )
            lessons[key] = replace(
                lesson,
                confirmations=lesson.confirmations + int(positive),
                contradictions=lesson.contradictions + int(not positive),
                last_seen_run=state.run_id,
                evidence=evidence,
            )
            last_seen[key] = index
    usage = _usage(ordered, agent_id)
    return tuple(
        replace(
            item,
            status=STALE if len(ordered) - 1 - last_seen[key] >= stale_after else ACTIVE,
            shown_verified=usage.get(item.id, (0, 0))[0],
            shown_unverified=usage.get(item.id, (0, 0))[1],
        )
        for key, item in lessons.items()
    )


def _carry(lesson: Lesson, before: Lesson | None) -> Lesson:
    """A person's decision outlives relearning; anything no person accepted stays proposed."""
    if before is not None and before.status == RETIRED:
        return replace(lesson, status=RETIRED, accepted_by=before.accepted_by)
    if before is not None and before.accepted_by != PROPOSER and before.status != PROPOSED:
        return replace(lesson, accepted_by=before.accepted_by)
    return replace(lesson, status=PROPOSED, accepted_by=PROPOSER)


def reconcile(
    old: Sequence[Lesson], derived: Sequence[Lesson], maximum: int = 30
) -> tuple[Lesson, ...]:
    """Preserve the operator's decisions and retain at most the configured, hard-capped 30
    lessons. A new lesson, or one only the engine accepted (before acceptance existed), is
    proposed: it is not shown until a person accepts it."""
    before = {lesson.id: lesson for lesson in old}
    found = [_carry(lesson, before.get(lesson.id)) for lesson in derived]
    found.sort(
        key=lambda item: (item.status != ACTIVE, -item.confirmations, item.contradictions, item.id)
    )
    return tuple(found[: min(30, maximum)])
