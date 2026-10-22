"""Make an installed version active, roll back to the previous one, freeze a source.

The state changes only after the new version passed its health check; ``current`` is a
symlink replaced in one step, so a reader sees the old version or the new one, never neither.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.ports import Runner
from wev_skills.third_party import check, fetch, health
from wev_skills.third_party.sources import Source
from wev_skills.third_party.state import VERSION_RE, SourceState, State

CURRENT = "current"


@dataclass(frozen=True)
class UpdateResult:
    ok: bool
    code: str  # "updated", "up_to_date", a check code or a health code
    version: str | None = None
    health: health.HealthReport | None = None


def point_current(base: Path, version: str) -> None:
    """Repoint ``base/current`` at ``version`` (a sibling directory) atomically. The temp link
    is named per process, so two updates at once never remove each other's."""
    tmp = base / f"{CURRENT}.tmp-{os.getpid()}"
    tmp.unlink(missing_ok=True)
    try:
        os.symlink(version, tmp)
    except FileExistsError as exc:
        raise StateConflict("busy", i18n.t("skills.error.busy", path=str(base))) from exc
    os.replace(tmp, base / CURRENT)


def _prune(base: Path, keep: set[str | None]) -> None:
    """Remove installed versions not in ``keep``; work directories and links are not versions.
    shortcut: a version another process installs at this moment can be removed under it."""
    for entry in base.iterdir():
        if entry.name in keep or not VERSION_RE.fullmatch(entry.name):
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)


def _points_at(base: Path, version: str) -> bool:
    """``current`` is a link to ``version``: a crash after a repoint leaves it elsewhere."""
    link = base / CURRENT
    return link.is_symlink() and os.readlink(link) == version


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
    download: check.Opener | None = None,
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
    if release.version == item.active and _points_at(base, item.active):
        return state, UpdateResult(True, "up_to_date", release.version)
    try:
        fetch.install_version(source, release, home, download or fetch.download, runner)
    except check.CheckFailed as exc:
        return state, UpdateResult(False, exc.code, release.version)
    report = health.health(source, release.version, home, runner, npx=npx)
    if not report.ok:  # the failed version stays for inspection, only the newest one
        _prune(base, {item.active, item.previous, release.version})
        return state, UpdateResult(False, report.code, release.version, report)
    point_current(base, release.version)
    previous = item.previous if release.version == item.active else item.active
    _prune(base, {release.version, previous})
    new = replace(item, active=release.version, previous=previous, declined=None)
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
    back = replace(item, active=item.previous, previous=item.active, declined=item.active)
    return _with(state, source.name, back)  # declined: the next update must not undo it


def freeze(source: Source, state: State, on: bool) -> State:
    item = state.sources.get(source.name, SourceState())
    return _with(state, source.name, replace(item, frozen=on))
