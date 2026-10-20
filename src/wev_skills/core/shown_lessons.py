"""Which lessons a task start showed, recorded so learning can count how those tasks ended.

The record is a ``lessons.shown`` event in the run's ``events.jsonl``, not a field of
``state.json``: release 2.0.0 validates ``state.json`` strictly and would refuse to resume a
run that carries a field it does not know, while it reads events as plain JSON. Release
3.0.0 wrote ``lessons_shown`` on the task; that field is still read and counted.

A start reads the agent's source file again under the lock that ``specialists accept`` and
``specialists retire`` take, and refuses when the file is gone or its lessons differ from
the spec as loaded (before ``extends`` is resolved). The lock is held until the start is
recorded and committed, so a decision lands either before this start (and the start is
refused, to be run again) or after it (and applies from the next start).

The event is appended before the state is committed, so a committed start never lacks its
record. Each record names the agent and the attempt number; a start whose commit fails is
retried with the same number, so only the last record of an attempt the state counts in
``starts`` is the committed one (``committed``), and records for another agent are ignored.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from wev_skills import i18n
from wev_skills.agents.registry import load_file
from wev_skills.core.errors import StateConflict
from wev_skills.core.fsutil import locked
from wev_skills.core.wiring import Services
from wev_skills.state.store import StateStore

EVENT = "lessons.shown"
LOCK_NAME = "specialists"


Attempts = dict[int, tuple[str, tuple[str, ...]]]
"""Per attempt number: (agent id, lesson ids) of the last record of that attempt."""


def record(store: StateStore, data: Mapping[str, Any]) -> None:
    """Append what one start showed: ``data`` has ``task_id``, ``agent_id``, ``attempt`` and
    ``lessons_shown``. Nothing is written when the start showed no lesson."""
    ids = list(data["lessons_shown"])
    if ids:
        fields = {key: data[key] for key in ("task_id", "agent_id", "attempt")}
        store.append_event(EVENT, {**fields, "lessons": ids})


def _parsed(event: Any) -> tuple[str, int, str, tuple[str, ...]] | None:
    if not isinstance(event, Mapping) or event.get("type") != EVENT:
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    task_id, agent_id = data.get("task_id"), data.get("agent_id")
    attempt, lessons = data.get("attempt"), data.get("lessons")
    if not (isinstance(task_id, str) and isinstance(agent_id, str) and isinstance(lessons, list)):
        return None
    if not isinstance(attempt, int) or isinstance(attempt, bool):
        return None
    return task_id, attempt, agent_id, tuple(item for item in lessons if isinstance(item, str))


def by_task(events: Iterable[Any]) -> dict[str, Attempts]:
    """Per task id, per attempt: the last record of that attempt (a later one replaces a
    record whose commit failed). Lines that are not well-formed records are skipped."""
    found: dict[str, Attempts] = {}
    for event in events:
        parsed = _parsed(event)
        if parsed is not None:
            task_id, attempt, agent_id, lessons = parsed
            found.setdefault(task_id, {})[attempt] = (agent_id, lessons)
    return found


def committed(attempts: Attempts, starts: int, agent_id: str) -> tuple[str, ...]:
    """Lesson ids of the attempts the state counts (1 to ``starts``) that ``agent_id`` made."""
    ids: dict[str, None] = {}
    for attempt in sorted(attempts):
        shown_to, lessons = attempts[attempt]
        if attempt <= starts and shown_to == agent_id:
            ids.update(dict.fromkeys(lessons))
    return tuple(ids)


@contextmanager
def current_lessons(services: Services, agent_id: str) -> Iterator[None]:
    """Hold the specialists lock and refuse when the agent's source file is gone or no longer
    has the lessons the catalog loaded. An agent registered without a file passes."""
    registry = services.agents.registry
    source = registry.source(agent_id)
    timeout = services.config.limits.lock_timeout_seconds
    with locked(services.state_dir / LOCK_NAME, timeout):
        if source is not None and (
            not source.is_file()
            or load_file(source).experience != registry.get(agent_id).experience
        ):
            message = i18n.t("orch.error.lessons_changed", agent=agent_id)
            raise StateConflict("lessons_changed", message, {"agent_id": agent_id})
        yield
