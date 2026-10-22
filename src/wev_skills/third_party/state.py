"""``state.json`` of the third-party sources. It is data: what it holds is checked, never obeyed."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.third_party.sources import SOURCES

VERSION_RE = re.compile(r"(?!\.+$)[A-Za-z0-9._-]{1,64}")  # not "." or "..": a path segment
_VERSION_FIELDS = ("active", "previous", "latest_seen", "declined")
_TEXT_FIELDS = ("last_check",)


@dataclass(frozen=True)
class SourceState:
    active: str | None = None
    previous: str | None = None
    frozen: bool = False
    last_check: str | None = None
    latest_seen: str | None = None
    declined: str | None = None  # the version the person said no to


@dataclass(frozen=True)
class State:
    sources: Mapping[str, SourceState]
    checked_at: str | None = None


def data_home() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "wev-skills" / "third-party"


def _invalid(path: Path, why: str) -> ValidationError:
    return ValidationError(
        "state_invalid", i18n.t("skills.error.state_invalid", path=str(path), why=why)
    )


def _source_state(path: Path, name: str, raw: object) -> SourceState:
    names = {f.name for f in fields(SourceState)}
    if not isinstance(raw, dict) or not set(raw) <= names:
        raise _invalid(path, f"sources.{name}")
    for key in _VERSION_FIELDS:
        value = raw.get(key)
        if value is not None and not (isinstance(value, str) and VERSION_RE.fullmatch(value)):
            raise _invalid(path, f"sources.{name}.{key}")
    for key in _TEXT_FIELDS:
        if not isinstance(raw.get(key), str | None):
            raise _invalid(path, f"sources.{name}.{key}")
    if not isinstance(raw.get("frozen", False), bool):
        raise _invalid(path, f"sources.{name}.frozen")
    return SourceState(**raw)


def _parse(path: Path, data: object) -> State:
    if not isinstance(data, dict) or not set(data) <= {"sources", "checked_at"}:
        raise _invalid(path, "root")
    raw_sources, checked = data.get("sources", {}), data.get("checked_at")
    known = {s.name for s in SOURCES}
    if not isinstance(raw_sources, dict) or not set(raw_sources) <= known:
        raise _invalid(path, "sources")
    if not isinstance(checked, str | None):
        raise _invalid(path, "checked_at")
    return State({n: _source_state(path, n, r) for n, r in raw_sources.items()}, checked)


def load(path: Path) -> State:
    if not path.is_file():
        return State({}, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(path, type(exc).__name__) from exc
    return _parse(path, data)


def save(path: Path, state: State) -> None:
    data = {
        "sources": {
            n: {f.name: getattr(s, f.name) for f in fields(s)} for n, s in state.sources.items()
        },
        "checked_at": state.checked_at,
    }
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")
