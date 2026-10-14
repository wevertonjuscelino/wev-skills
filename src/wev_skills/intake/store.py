"""Private, atomic intake records; transitions run under the record lock."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.core.fsutil import atomic_write_text, ensure_ignored_dir, locked
from wev_skills.core.ports import SystemClock
from wev_skills.intake import model
from wev_skills.intake.model import Brief, IntakeRecord
from wev_skills.state.model import iso_utc, validate_run_id
from wev_skills.state.store import new_run_id


def _safe_directory(path: Path) -> None:
    for part in (path, path.parent):
        if part.is_symlink():
            raise ValidationError("intake_unsafe_path", i18n.t("intake.error.unsafe_path"), {})
    if path.exists():
        info = path.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValidationError("intake_unsafe_path", i18n.t("intake.error.unsafe_path"), {})


class IntakeStore:
    def __init__(self, state_dir: Path, timeout: float = 30.0) -> None:
        self.directory = Path(state_dir) / "intakes"
        self.timeout = timeout

    def _path(self, intake_id: str) -> Path:
        _safe_directory(self.directory)
        path = self.directory / f"{validate_run_id(intake_id)}.json"
        lock_path = path.with_name(f".{path.name}.lock")
        if path.is_symlink() or lock_path.is_symlink():
            raise ValidationError("intake_unsafe_path", i18n.t("intake.error.unsafe_path"), {})
        if path.exists():
            info = path.stat()
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise ValidationError("intake_unsafe_path", i18n.t("intake.error.unsafe_path"), {})
        return path

    def start(self, request: str) -> tuple[str, IntakeRecord]:
        clock = SystemClock()
        record = model.start(request, iso_utc(clock.now()))
        intake_id = new_run_id(clock)
        path = self._path(intake_id)
        ensure_ignored_dir(self.directory)
        with locked(path, self.timeout):
            if path.exists():
                raise ValidationError("intake_collision", i18n.t("intake.error.collision"), {})
            self._write(path, record)
        return intake_id, record

    def load(self, intake_id: str) -> IntakeRecord:
        path = self._path(intake_id)
        try:
            record = IntakeRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise NotFound("intake_not_found", i18n.t("intake.error.not_found"), {}) from exc
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValidationError("intake_corrupt", i18n.t("intake.error.corrupt"), {}) from exc
        self._validate(record)
        return record

    def update(
        self, intake_id: str, transition: Callable[[IntakeRecord], IntakeRecord]
    ) -> IntakeRecord:
        path = self._path(intake_id)
        # Do not create an empty state directory for an unknown identifier.
        if not path.exists():
            return self.load(intake_id)
        with locked(path, self.timeout):
            record = transition(self.load(intake_id))
            self._validate(record)
            self._write(path, record)
            return record

    @staticmethod
    def _write(path: Path, record: IntakeRecord) -> None:
        atomic_write_text(path, json.dumps(record.to_dict(), ensure_ascii=False, indent=2) + "\n")

    @staticmethod
    def _validate(record: IntakeRecord) -> None:
        if not 0 <= record.rounds_used <= 10:
            raise ValidationError("intake_corrupt", i18n.t("intake.error.corrupt"), {})
        reconstructed = model.start(record.request, record.created_at)
        seen: set[str] = set()
        for item in record.fields:
            if item.field in seen:
                raise ValidationError("intake_corrupt", i18n.t("intake.error.corrupt"), {})
            seen.add(item.field)
            reconstructed = model.set_field(reconstructed, item.field, item.values, item.source)
        if record.complete:
            model.finish(reconstructed)


def load_brief(state_dir: Path, intake_id: str) -> Brief:
    record = IntakeStore(state_dir).load(intake_id)
    if not record.complete:
        raise ValidationError("intake_incomplete", i18n.t("intake.error.intake_incomplete"), {})
    return model.finish(record)[1]
