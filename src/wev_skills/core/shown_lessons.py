"""Which lessons a task start showed, recorded so learning can count how those tasks ended.

The record is a ``lessons.shown`` event in the run's ``events.jsonl``, not a field of
``state.json``: release 2.0.0 validates ``state.json`` strictly and would refuse to resume a
run that carries a field it does not know, while it reads events as plain JSON. Release
3.0.0 wrote ``lessons_shown`` on the task; that field is still read and counted.

A start reads the agent's source file again under the lock that ``specialists accept`` and
``specialists retire`` take, and refuses when the file is gone or its lessons differ from
the spec as loaded (before ``extends`` is resolved). The lock is held until the start is
committed and recorded, so a decision lands either before this start (and the start is
refused, to be run again) or after it (and applies from the next start).

The event is appended only after the state is committed, so every record is a start that
happened. A process that dies between the two leaves that start without a record: its
lessons are not counted, which errs toward missing usage rather than crediting a lesson
that was never shown. Each record names the agent it was shown to, and only records for
the agent that ended the task count (``for_task``).
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


Records = tuple[tuple[str, tuple[str, ...]], ...]
"""The records of one task, oldest first: (agent id, lesson ids) per committed start."""


def record(store: StateStore, data: Mapping[str, Any]) -> None:
    """Append what one committed start showed: ``data`` has ``task_id``, ``agent_id`` and
    ``lessons_shown``. Nothing is written when the start showed no lesson."""
    ids = list(data["lessons_shown"])
    if ids:
        fields = {key: data[key] for key in ("task_id", "agent_id")}
        store.append_event(EVENT, {**fields, "lessons": ids})


def _parsed(event: Any) -> tuple[str, str, tuple[str, ...]] | None:
    if not isinstance(event, Mapping) or event.get("type") != EVENT:
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    task_id, agent_id, lessons = data.get("task_id"), data.get("agent_id"), data.get("lessons")
    if not (isinstance(task_id, str) and isinstance(agent_id, str) and isinstance(lessons, list)):
        return None
    return task_id, agent_id, tuple(item for item in lessons if isinstance(item, str))


def by_task(events: Iterable[Any]) -> dict[str, Records]:
    """Per task id: its records, oldest first. Lines that are not well-formed are skipped."""
    found: dict[str, Records] = {}
    for event in events:
        parsed = _parsed(event)
        if parsed is not None:
            task_id, agent_id, lessons = parsed
            found[task_id] = (*found.get(task_id, ()), (agent_id, lessons))
    return found


def for_task(records: Records, agent_id: str, legacy: Iterable[str] = ()) -> tuple[str, ...]:
    """The lesson ids shown to ``agent_id``, the agent that ended the task. ``legacy`` (the
    ids release 3.0.0 kept on the task, without an agent) counts only while no record shows
    that the task had another agent."""
    reassigned = any(shown_to != agent_id for shown_to, _ in records)
    ids: dict[str, None] = {} if reassigned else dict.fromkeys(legacy)
    for shown_to, lessons in records:
        if shown_to == agent_id:
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
