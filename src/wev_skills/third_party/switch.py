"""Make an installed version active, roll back to the previous one, freeze a source.

The state changes only after the new version passed its health check; ``current`` is a
symlink replaced in one step, so a reader sees the old version or the new one, never neither.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.ports import Runner
from wev_skills.third_party import check, fetch, health
from wev_skills.third_party.sources import Source
from wev_skills.third_party.state import SourceState, State

CURRENT = "current"


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    code: str  # "updated", "up_to_date", a check code or a health code
    version: str | None = None
    health: health.HealthReport | None = None


def point_current(base: Path, version: str) -> None:
    """Repoint ``base/current`` at ``version`` (a sibling directory) atomically."""
    tmp = base / f"{CURRENT}.tmp"
    tmp.unlink(missing_ok=True)
    os.symlink(version, tmp)
    os.replace(tmp, base / CURRENT)


def _with(state: State, name: str, item: SourceState) -> State:
    return replace(state, sources={**state.sources, name: item})


def update(
    source: Source,
    home: Path,
    state: State,
    opener: check.Opener,
    runner: Runner,
    base_urls: Mapping[str, str],
    *,
    yes: bool = False,
    npx: str = "npx",
) -> tuple[State, UpdateResult]:
    item = state.sources.get(source.name, SourceState())
    if item.frozen:
        raise ValidationError("frozen", i18n.t("skills.error.frozen", name=source.name))
    try:
        release = check.latest(source, opener, base_urls)
    except check.CheckFailed as exc:
        return state, UpdateResult(False, exc.code)
    if release.version == item.declined and not yes:
        raise ValidationError(
            "declined", i18n.t("skills.error.declined", name=source.name, version=release.version)
        )
    base = home / source.name
    if release.version == item.active and (base / CURRENT).is_symlink():
        return state, UpdateResult(True, "up_to_date", release.version)
    try:
        fetch.install_version(source, release, home, opener, runner)
    except check.CheckFailed as exc:
        return state, UpdateResult(False, exc.code, release.version)
    report = health.health(source, release.version, home, runner, npx=npx)
    if not report.ok:
        return state, UpdateResult(False, report.code, release.version, report)
    point_current(base, release.version)
    new = replace(item, active=release.version, previous=item.active, declined=None)
    return _with(state, source.name, new), UpdateResult(True, "updated", release.version, report)


def rollback(source: Source, home: Path, state: State) -> State:
    item = state.sources.get(source.name, SourceState())
    if item.previous is None:
        raise StateConflict("no_previous", i18n.t("skills.error.no_previous", name=source.name))
    base = home / source.name
    if not (base / item.previous).is_dir():
        raise StateConflict(
            "previous_missing",
            i18n.t("skills.error.previous_missing", name=source.name, version=item.previous),
        )
    point_current(base, item.previous)
    return _with(state, source.name, replace(item, active=item.previous, previous=item.active))


def freeze(source: Source, state: State, on: bool) -> State:
    item = state.sources.get(source.name, SourceState())
    return _with(state, source.name, replace(item, frozen=on))
