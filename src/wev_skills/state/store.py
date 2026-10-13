"""Durable run state: ``state.json`` (schema-validated, revisioned) and ``events.jsonl``.

Every write holds an exclusive lock, re-reads the file, and replaces it atomically, so
concurrent writers never lose an update and readers never see a partial file. Nothing here
redacts: callers pass redacted text (see ``state.model``).
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from wev_skills import schema
from wev_skills.core.contracts import Mode
from wev_skills.core.errors import NotFound, StateConflict, ValidationError
from wev_skills.core.fsutil import (
    LOCK_TIMEOUT_SECONDS,
    append_line,
    atomic_write_text,
    locked,
)
from wev_skills.core.ports import Clock, SystemClock
from wev_skills.state.model import (
    RUN_ID_RE,
    SCHEMA_VERSION,
    Phase,
    RunState,
    iso_utc,
    plain_json,
    validate_run_id,
)

STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"
RUNS_DIR = "runs"
_SUFFIX_BYTES = 3
_IMMUTABLE_FIELDS = (
    "run_id",
    "created_at",
    "schema_version",
    "mode",
    "config",
    "config_digest",
    "config_source",
)


def new_run_id(clock: Clock) -> str:
    """UTC timestamp plus a short random suffix, e.g. ``20261013T142501Z-9f3a1c``."""
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(clock.now()))
    return f"{stamp}-{secrets.token_hex(_SUFFIX_BYTES)}"


def runs_dir(state_dir: str | Path) -> Path:
    return Path(state_dir) / RUNS_DIR


def run_dir(state_dir: str | Path, run_id: str) -> Path:
    """Directory of one run; rejects ids that are not a safe single directory name."""
    return runs_dir(state_dir) / validate_run_id(run_id)


def list_runs(state_dir: str | Path) -> list[str]:
    """Sorted ids of every run directory under ``<state_dir>/runs`` that holds a state file."""
    base = runs_dir(state_dir)
    if not base.is_dir():
        return []
    return sorted(
        entry.name
        for entry in base.iterdir()
        if RUN_ID_RE.match(entry.name) and not entry.is_symlink() and (entry / STATE_FILE).is_file()
    )


def runs_by_recency(state_dir: str | Path) -> list[str]:
    """Run ids, most recently written state file first (ties by id)."""
    stamped: list[tuple[int, str]] = []
    for name in list_runs(state_dir):
        try:
            stamp = (runs_dir(state_dir) / name / STATE_FILE).stat().st_mtime_ns
        except FileNotFoundError:
            continue
        stamped.append((stamp, name))
    return [name for _, name in sorted(stamped, reverse=True)]


def latest_run(state_dir: str | Path) -> str | None:
    """Id of the most recently written run (by state file modification time), or ``None``."""
    ordered = runs_by_recency(state_dir)
    return ordered[0] if ordered else None


def _recorded_phase(path: Path) -> str:
    """The ``phase`` of a state file, read without building the whole state."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _corrupt(path, f"{type(exc).__name__}: {exc}") from exc
    phase = data.get("phase") if isinstance(data, dict) else None
    if not isinstance(phase, str):
        raise _corrupt(path, "no phase recorded")
    return phase


def active_run(state_dir: str | Path) -> str | None:
    """Id of the active run: the most recently written one whose phase is not ``done``.

    Read-only: nothing is created or changed. A state file that cannot be read is an error,
    never a run silently skipped, because skipping it could hide the run that is active.
    """
    for name in runs_by_recency(state_dir):
        if _recorded_phase(runs_dir(state_dir) / name / STATE_FILE) != Phase.DONE.value:
            return name
    return None


def _corrupt(path: Path, reason: str) -> ValidationError:
    return ValidationError(
        "state_corrupt",
        f"state file {path} is corrupt and was left untouched: {reason}",
        {"path": str(path)},
    )


class StateStore:
    """Reads and writes the state of one run directory."""

    def __init__(
        self,
        run_dir: str | Path,
        clock: Clock | None = None,
        lock_timeout: float = LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self.run_dir = Path(run_dir)
        self._lock_timeout = lock_timeout
        self.state_path = self.run_dir / STATE_FILE
        self.events_path = self.run_dir / EVENTS_FILE
        self._clock: Clock = clock if clock is not None else SystemClock()

    def exists(self) -> bool:
        return self.state_path.is_file()

    def create(
        self,
        objective: str,
        mode: Mode | str,
        run_id: str | None = None,
        config: Mapping[str, Any] | None = None,
        config_digest: str = "",
        config_source: str = "",
    ) -> RunState:
        """Write revision 1. Raises ``StateConflict`` when this run already has a state.

        ``config`` is the configuration snapshot the run is pinned to; like the mode, it
        can never be changed afterwards.
        """
        if not isinstance(objective, str) or not objective.strip():
            raise ValidationError("invalid_objective", "objective must be a non-empty string")
        try:
            run_mode = Mode(mode)
        except ValueError as exc:
            raise ValidationError("invalid_enum", f"unknown mode: {mode!r}") from exc
        now = iso_utc(self._clock.now())
        state = RunState(
            self._run_id(run_id),
            objective,
            run_mode,
            now,
            now,
            config=dict(config or {}),
            config_digest=config_digest,
            config_source=config_source,
        )
        with locked(self.state_path, self._lock_timeout):
            if self.state_path.exists():
                raise StateConflict(
                    "state_exists",
                    f"a state already exists at {self.state_path}",
                    {"path": str(self.state_path)},
                )
            self._write(state)
        self.append_event("run_created", {"run_id": state.run_id, "mode": run_mode.value})
        return state

    def load(self) -> RunState:
        """Read and validate the state. Never modifies the file, even when it is corrupt."""
        path = self.state_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NotFound("state_not_found", f"no state at {path}", {"path": str(path)}) from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _corrupt(path, f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(data, dict):
            raise _corrupt(path, "top level must be an object")
        version = data.get("schema_version")
        if version != SCHEMA_VERSION or isinstance(version, bool):
            raise ValidationError(
                "state_version_unsupported",
                f"state file {path} has schema_version {version!r}; this engine reads "
                f"version {SCHEMA_VERSION}. The file was left untouched.",
                {"path": str(path), "found": version, "supported": SCHEMA_VERSION},
            )
        errors = schema.validate(data, schema.load("state"))
        if errors:
            raise ValidationError(
                "state_corrupt",
                f"state file {path} failed schema validation and was left untouched: {errors[0]}",
                {"path": str(path), "errors": errors},
            )
        return RunState.from_dict(data)

    def update(
        self, mutator: Callable[[RunState], RunState], expected_revision: int | None = None
    ) -> RunState:
        """Apply ``mutator`` to the latest state on disk under the lock and persist the result.

        If the mutator raises, or its result is invalid, the previous state stays on disk.
        """
        with locked(self.state_path, self._lock_timeout):
            current = self.load()
            if expected_revision is not None and expected_revision != current.revision:
                raise StateConflict(
                    "revision_mismatch",
                    f"expected revision {expected_revision}, found {current.revision}",
                    {"expected": expected_revision, "found": current.revision},
                )
            changed = mutator(current)
            if not isinstance(changed, RunState):
                raise ValidationError("invalid_mutator", "the mutator must return a RunState")
            for name in _IMMUTABLE_FIELDS:
                if getattr(changed, name) != getattr(current, name):
                    raise ValidationError("immutable_field", f"{name} cannot be changed")
            updated = replace(
                changed, revision=current.revision + 1, updated_at=iso_utc(self._clock.now())
            )
            self._write(updated)
        return updated

    def append_event(self, event_type: str, data: Mapping[str, Any] | None = None) -> None:
        """Append one JSON line to ``events.jsonl``. ``data`` must be redacted plain JSON."""
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValidationError("invalid_event", "event type must be a non-empty string")
        if data is not None and not isinstance(data, Mapping):
            raise ValidationError("invalid_event", "event data must be an object")
        event = {
            "at": iso_utc(self._clock.now()),
            "type": event_type,
            "data": plain_json(data or {}, "/data"),
        }
        append_line(self.events_path, json.dumps(event, ensure_ascii=False, sort_keys=True))

    def events(self) -> list[dict[str, Any]]:
        """Every recorded event, oldest first (empty when none was written)."""
        try:
            lines = self.events_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        try:
            return [json.loads(line) for line in lines if line.strip()]
        except json.JSONDecodeError as exc:
            raise _corrupt(self.events_path, str(exc)) from exc

    def _run_id(self, requested: str | None) -> str:
        if requested is not None:
            return validate_run_id(requested)
        name = self.run_dir.name
        return name if RUN_ID_RE.match(name) else new_run_id(self._clock)

    def _write(self, state: RunState) -> None:
        data = state.to_dict()
        schema.validate_or_raise(data, schema.load("state"), "run state")
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        except ValueError as exc:
            raise ValidationError("invalid_value", f"state is not valid JSON: {exc}") from exc
        atomic_write_text(self.state_path, text + "\n")
