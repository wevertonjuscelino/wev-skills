"""Append-only audit log: one redacted JSON object per line."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core import fsutil
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import Clock, SystemClock
from wev_skills.security.redact import redact, redact_mapping

UNREADABLE_EVENT = "audit.unreadable_line"
AUDIT_FILE_NAME = "audit.jsonl"
"""The audit log's file name inside a state directory (``core.wiring`` uses the same one)."""


class AuditLog:
    def __init__(self, path: str | Path, clock: Clock | None = None) -> None:
        self._path = Path(path)
        self._clock: Clock = clock if clock is not None else SystemClock()

    def append(self, event_type: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """Write one event and return the record as stored (secrets already masked)."""
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValidationError("invalid_event", i18n.t("security.audit.event_type_required"))
        if not isinstance(data, Mapping):
            raise ValidationError("invalid_event", i18n.t("security.audit.data_not_mapping"))
        record = {
            "ts": self._clock.now(),
            "type": redact(event_type.strip()),
            "data": redact_mapping(data),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        fsutil.append_line(self._path, line)
        stored: dict[str, Any] = json.loads(line)
        return stored

    def read(self, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        """Events oldest first; ``limit`` keeps only the most recent ones.

        A line that is not a JSON object is reported as an ``audit.unreadable_line``
        event instead of being dropped, so damage to the log stays visible.
        """
        if limit is not None and limit < 0:
            raise ValidationError("invalid_limit", i18n.t("security.audit.bad_limit"))
        try:
            lines = self._path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ()
        events = [_decode(number, line) for number, line in enumerate(lines, 1) if line.strip()]
        if limit is None:
            return tuple(events)
        return tuple(events[len(events) - limit :]) if limit else ()


def _decode(number: int, line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value
    return {"ts": None, "type": UNREADABLE_EVENT, "data": {"line": number}}
