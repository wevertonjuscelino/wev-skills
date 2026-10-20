"""Which lessons a task start showed, recorded so learning can count how those tasks ended.

The record is a ``lessons.shown`` event in the run's ``events.jsonl``, not a field of
``state.json``: release 2.0.0 validates ``state.json`` strictly and would refuse to resume a
run that carries a field it does not know, while it reads events as plain JSON. Release
3.0.0 wrote ``lessons_shown`` on the task; that field is still read and counted.

A start reads the specialist's file again under the lock that ``specialists accept`` and
``specialists retire`` take, and refuses when the lessons changed since the catalog was
loaded. The lock is held until the start is committed and recorded, so a decision lands
either before this start (and the start is refused, to be run again) or after it (and applies
from the next start).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from wev_skills import i18n
from wev_skills.agents.registry import load_file
from wev_skills.agents.spec import AgentSpec
from wev_skills.core.errors import StateConflict
from wev_skills.core.fsutil import locked
from wev_skills.core.wiring import Services
from wev_skills.state.store import StateStore

EVENT = "lessons.shown"
LOCK_NAME = "specialists"


def record(store: StateStore, task_id: str, lesson_ids: Iterable[str]) -> None:
    """Append the ids one start of ``task_id`` showed (nothing when it showed none)."""
    ids = list(lesson_ids)
    if ids:
        store.append_event(EVENT, {"task_id": task_id, "lessons": ids})


def by_task(events: Iterable[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    """Per task id: every lesson id any start of that task showed, first shown first."""
    found: dict[str, dict[str, None]] = {}
    for event in events:
        data = event.get("data")
        if event.get("type") != EVENT or not isinstance(data, Mapping):
            continue
        task_id, lessons = data.get("task_id"), data.get("lessons")
        if not isinstance(task_id, str) or not isinstance(lessons, list):
            continue
        seen = found.setdefault(task_id, {})
        seen.update((item, None) for item in lessons if isinstance(item, str))
    return {task_id: tuple(ids) for task_id, ids in found.items()}


@contextmanager
def current_lessons(services: Services, spec: AgentSpec) -> Iterator[None]:
    """Hold the specialists lock and refuse when the project specialist's file no longer
    has the lessons ``spec`` was loaded with. An agent without a file there passes."""
    path = services.root / services.config.agents.project_dir / f"{spec.id}.json"
    timeout = services.config.limits.lock_timeout_seconds
    with locked(services.state_dir / LOCK_NAME, timeout):
        if path.is_file() and load_file(path).experience != spec.experience:
            message = i18n.t("orch.error.lessons_changed", agent=spec.id)
            raise StateConflict("lessons_changed", message, {"agent_id": spec.id})
        yield
