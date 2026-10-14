"""Deterministic observations from engine records, never from an agent's prose."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import replace

from wev_skills import i18n
from wev_skills.agents.experience import ACTIVE, RETIRED, STALE, Lesson, LessonEvidence, RecordRef
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
            key = ("check", hashlib.sha256("\0".join(check.argv).encode()).hexdigest())
            found[key] = (key, check.state == "passed", record.task_id, record.at)
    for trip in state.guard_trips:
        if trip.task_id in tasks:
            key = ("guard", trip.rule)
            found[key] = (key, True, trip.task_id, trip.at)
    return list(found.values())


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
    return tuple(
        replace(item, status=STALE if len(ordered) - 1 - last_seen[key] >= stale_after else ACTIVE)
        for key, item in lessons.items()
    )


def reconcile(
    old: Sequence[Lesson], derived: Sequence[Lesson], maximum: int = 30
) -> tuple[Lesson, ...]:
    """Preserve retirement decisions and retain at most the configured, hard-capped 30 lessons."""
    retired = {lesson.id for lesson in old if lesson.status == RETIRED}
    found = [
        replace(lesson, status=RETIRED) if lesson.id in retired else lesson for lesson in derived
    ]
    found.sort(
        key=lambda item: (item.status != ACTIVE, -item.confirmations, item.contradictions, item.id)
    )
    return tuple(found[: min(30, maximum)])
