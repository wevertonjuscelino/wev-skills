"""Which lessons a task start showed, recorded so learning can count how those tasks ended.

The record is a ``lessons.shown`` event in the run's ``events.jsonl``, not a field of
``state.json``: release 2.0.0 validates ``state.json`` strictly and would refuse to resume a
run that carries a field it does not know, while it reads events as plain JSON. Release
3.0.0 wrote ``lessons_shown`` on the task, inside the state commit; that field is still read.

A start reads the agent's source file again under the lock that ``specialists accept`` and
``specialists retire`` take, and refuses when the file is gone or its lessons differ from
the spec as loaded (before ``extends`` is resolved). The lock is held until the start is
committed and recorded, so a decision lands either before this start (and the start is
refused, to be run again) or after it (and applies from the next start).

Every committed start appends one record, even when it showed no lesson, naming the agent
and the attempt number. The record is appended only after the state commit, so every record
is a start that happened; when the append fails, or the process dies first, that start is
not counted, which errs toward missing usage rather than crediting a lesson never shown.
For the same reason the records release 4.0.0 wrote (before the commit, without an agent)
are not counted. Reopening a task resets its attempts to 1, so a record whose attempt does
not exceed the one before it begins a new cycle, and only the last cycle counts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.agents.registry import load_file
from wev_skills.core.errors import StateConflict
from wev_skills.core.fsutil import locked
from wev_skills.core.wiring import Services
from wev_skills.state.store import StateStore

EVENT = "lessons.shown"
LOCK_NAME = "specialists"


Record = tuple[int, str, tuple[str, ...]]
"""One committed start: (attempt number, agent id, lesson ids)."""


def record(store: StateStore, data: Mapping[str, Any]) -> None:
    """Append what one committed start showed: ``data`` has ``task_id``, ``agent_id``,
    ``attempt`` and ``lessons_shown`` (possibly empty)."""
    fields = {key: data[key] for key in ("task_id", "agent_id", "attempt")}
    store.append_event(EVENT, {**fields, "lessons": list(data["lessons_shown"])})


def read_events(path: Path) -> list[Any]:
    """The lines of an ``events.jsonl``; a line that is not JSON (a write cut short) is
    skipped, so one damaged line costs that record, not the run's learning."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    found = []
    for line in lines:
        try:
            found.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return found


def _parsed(event: Any) -> tuple[str, Record] | None:
    if not isinstance(event, Mapping) or event.get("type") != EVENT:
        return None
    data = event.get("data")
    if not isinstance(data, Mapping):
        return None
    task_id, agent_id, lessons = data.get("task_id"), data.get("agent_id"), data.get("lessons")
    attempt = data.get("attempt")
    if not (isinstance(task_id, str) and isinstance(agent_id, str) and isinstance(lessons, list)):
        return None
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        return None
    return task_id, (attempt, agent_id, tuple(item for item in lessons if isinstance(item, str)))


def by_task(events: Iterable[Any]) -> dict[str, tuple[Record, ...]]:
    """Per task id: its records, oldest first. Lines that are not well-formed are skipped."""
    found: dict[str, tuple[Record, ...]] = {}
    for event in events:
        parsed = _parsed(event)
        if parsed is not None:
            task_id, entry = parsed
            found[task_id] = (*found.get(task_id, ()), entry)
    return found


def _last_cycle(records: Iterable[Record]) -> list[Record]:
    cycle: list[Record] = []
    for entry in records:
        if cycle and entry[0] <= cycle[-1][0]:
            cycle = []
        cycle.append(entry)
    return cycle


def for_task(
    records: tuple[Record, ...], agent_id: str, starts: int, legacy: Iterable[str] = ()
) -> tuple[str, ...]:
    """The lesson ids the task's current cycle of starts (attempts 1 to ``starts``) showed to
    ``agent_id``, the agent that ended it. ``legacy`` (ids 3.0.0 kept on the task) counts only
    while no record shows another agent and no cycle began after the upgrade."""
    reassigned = any(shown_to != agent_id for _, shown_to, _ in records)
    restarted = any(attempt == 1 for attempt, _, _ in records)
    ids: dict[str, None] = {} if reassigned or restarted else dict.fromkeys(legacy)
    for attempt, shown_to, lessons in _last_cycle(records):
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
