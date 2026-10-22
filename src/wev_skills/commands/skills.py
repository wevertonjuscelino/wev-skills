"""``wev skills list``: the third-party skill sources and what is installed from each."""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Subparsers
from wev_skills.commands import _skills_manage as manage
from wev_skills.core.errors import RemoteError, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.third_party import check as check_mod
from wev_skills.third_party import fetch as fetch_mod
from wev_skills.third_party import state as state_mod
from wev_skills.third_party.sources import SOURCES, Source, source


def _run_list(_args: argparse.Namespace) -> dict[str, Any]:
    current = state_mod.load(_state_path())
    rows = []
    for src in SOURCES:
        item = current.sources.get(src.name, state_mod.SourceState())
        shown = item.latest_seen or item.active
        rows.append(
            {
                "name": src.name,
                "kind": src.kind,
                "active": item.active,
                "previous": item.previous,
                "frozen": item.frozen,
                "latest_seen": item.latest_seen,
                "changelog": src.changelog.format(version=shown) if shown else None,
            }
        )
    return {"sources": rows}


def _state_path() -> Path:
    return state_mod.data_home() / "state.json"


def _session_json(updates: tuple[check_mod.Update, ...]) -> str:
    context = check_mod.daily_context(updates)
    event = {"hookEventName": "SessionStart", "additionalContext": context}
    return json.dumps({"hookSpecificOutput": event}, ensure_ascii=False)


def _scan_within_budget(current: state_mod.State, now: datetime) -> check_mod.Outcome | None:
    """The scan, or ``None`` after the wall-clock budget: a slow answer is left behind."""
    box: list[check_mod.Outcome] = []

    def work() -> None:
        scan = check_mod.scan(current, now, check_mod.fetch, check_mod.BASE_URLS, force=False)
        box.append(scan)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(check_mod.DAILY_BUDGET)
    return None if worker.is_alive() or not box else box[0]


def _run_daily() -> CommandResult:
    """The session-start check: it prints the hook JSON or nothing, and never fails loudly."""
    silent = CommandResult("", raw=True)
    try:
        path, now = _state_path(), datetime.now(UTC)
        current = state_mod.load(path)
        if not check_mod.is_due(current, now):
            return silent
        outcome = _scan_within_budget(current, now)
        if outcome is None:
            return silent
        if outcome.state != current:
            _save_checked(path, current, outcome)
        return (
            CommandResult(_session_json(outcome.updates), raw=True) if outcome.updates else silent
        )
    except Exception:  # noqa: BLE001 - a session must start whatever happens here
        return silent


def _save_checked(path: Path, before: state_mod.State, outcome: check_mod.Outcome) -> None:
    """Merge what the check saw into the state as it is now: another command may have saved it
    meanwhile (a freeze, an update), and the scan's own copy is older than that."""
    fresh = state_mod.load(path)
    sources = dict(fresh.sources)
    for name in outcome.checked:
        seen = outcome.state.sources[name]
        item = sources.get(name, state_mod.SourceState())
        sources[name] = replace(item, last_check=seen.last_check, latest_seen=seen.latest_seen)
    moved = outcome.state.checked_at != before.checked_at
    marker = outcome.state.checked_at if moved else fresh.checked_at
    state_mod.save(path, replace(fresh, sources=sources, checked_at=marker))


def _registry() -> check_mod.Opener:
    return check_mod.bounded(check_mod.fetch, check_mod.INTERACTIVE_BUDGET)


def _run_check(args: argparse.Namespace) -> CommandResult | dict[str, Any]:
    if args.daily:
        return _run_daily()
    path = _state_path()
    current = state_mod.load(path)
    outcome = check_mod.scan(
        current, datetime.now(UTC), _registry(), check_mod.BASE_URLS, force=True
    )
    _save_checked(path, current, outcome)
    return {
        "updates": [asdict(u) for u in outcome.updates],
        "checked": list(outcome.checked),
        "failed": [dict(f) for f in outcome.failed],
    }


def _run_decline(args: argparse.Namespace) -> dict[str, Any]:
    name = source(args.source).name
    path = _state_path()
    current = state_mod.load(path)
    item = current.sources.get(name, state_mod.SourceState())
    if item.latest_seen is None:
        raise ValidationError(
            "nothing_to_decline", i18n.t("skills.error.nothing_to_decline", name=name)
        )
    sources = {**current.sources, name: replace(item, declined=item.latest_seen)}
    state_mod.save(path, replace(current, sources=sources))
    return {"source": name, "declined": item.latest_seen}


def _release_for(src: Source, version: str | None) -> check_mod.Release:
    if version is None:
        return check_mod.latest(src, _registry())
    if not check_mod.valid_version(src.kind, version):
        raise ValidationError("bad_version", i18n.t("skills.error.bad_version", version=version))
    link = src.changelog.format(version=version)
    if src.kind == "npm":  # the registry must know the version before a ref is written
        base = check_mod.BASE_URLS["npm"]
        check_mod.get_json(_registry(), f"{base}/{src.package}/{version}")
        return check_mod.Release(version, link, None)
    return check_mod.Release(version, link, check_mod.tarball_url(src, version))


def _run_install(args: argparse.Namespace) -> dict[str, Any]:
    src = source(args.source)
    try:
        release = _release_for(src, args.version)
        path = fetch_mod.install_version(
            src, release, state_mod.data_home(), fetch_mod.download, SubprocessRunner()
        )
    except check_mod.CheckFailed as exc:
        raise RemoteError(
            exc.code, i18n.t("skills.error.install_failed", name=src.name, code=exc.code)
        ) from exc
    return {
        "source": src.name,
        "version": release.version,
        "path": str(path),
        "active": False,
        "next_steps": i18n.t("skills.install.next_steps", name=src.name),
    }


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("skills", help=i18n.t("skills.group.help"))
    commands = group.add_subparsers(dest="skills_command", required=True)
    listing = commands.add_parser("list", help=i18n.t("skills.list.help"))
    listing.set_defaults(handler=_run_list)
    checking = commands.add_parser("check", help=i18n.t("skills.check.help"))
    checking.add_argument("--daily", action="store_true", help=i18n.t("skills.check.daily"))
    checking.set_defaults(handler=_run_check)
    declining = commands.add_parser("decline", help=i18n.t("skills.decline.help"))
    declining.add_argument("source", help=i18n.t("skills.decline.source"))
    declining.set_defaults(handler=_run_decline)
    installing = commands.add_parser("install", help=i18n.t("skills.install.help"))
    installing.add_argument("source", help=i18n.t("skills.decline.source"))
    installing.add_argument("--version", help=i18n.t("skills.install.version"))
    installing.set_defaults(handler=_run_install)
    updating = commands.add_parser("update", help=i18n.t("skills.update.help"))
    updating.add_argument("source", nargs="?", help=i18n.t("skills.update.source"))
    updating.add_argument("--yes", action="store_true", help=i18n.t("skills.update.yes"))
    updating.set_defaults(handler=manage.run_update)
    rolling = commands.add_parser("rollback", help=i18n.t("skills.rollback.help"))
    rolling.add_argument("source", help=i18n.t("skills.decline.source"))
    rolling.set_defaults(handler=manage.run_rollback)
    freezing = commands.add_parser("freeze", help=i18n.t("skills.freeze.help"))
    freezing.add_argument("source", help=i18n.t("skills.decline.source"))
    freezing.add_argument("--off", action="store_true", help=i18n.t("skills.freeze.off"))
    freezing.set_defaults(handler=manage.run_freeze)
    showing = commands.add_parser("show", help=i18n.t("skills.show.help"))
    showing.add_argument("source", help=i18n.t("skills.decline.source"))
    showing.set_defaults(handler=manage.run_show)
    commands.add_parser("activate", help=i18n.t("skills.activate.help")).set_defaults(
        handler=manage.run_activate
    )
    commands.add_parser("deactivate", help=i18n.t("skills.deactivate.help")).set_defaults(
        handler=manage.run_deactivate
    )
