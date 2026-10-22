"""``wev skills list``: the third-party skill sources and what is installed from each."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Subparsers
from wev_skills.core.errors import ValidationError
from wev_skills.third_party import check as check_mod
from wev_skills.third_party import state as state_mod
from wev_skills.third_party.sources import SOURCES, source


def _run_list(_args: argparse.Namespace) -> dict[str, Any]:
    current = state_mod.load(state_mod.data_home() / "state.json")
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


def _state_path() -> Any:
    return state_mod.data_home() / "state.json"


def _session_json(updates: tuple[check_mod.Update, ...]) -> str:
    context = check_mod.daily_context(updates)
    event = {"hookEventName": "SessionStart", "additionalContext": context}
    return json.dumps({"hookSpecificOutput": event}, ensure_ascii=False)


def _run_daily() -> CommandResult:
    """The session-start check: it prints the hook JSON or nothing, and never fails loudly."""
    silent = CommandResult("", raw=True)
    try:
        path, now = _state_path(), datetime.now(UTC)
        current = state_mod.load(path)
        if not check_mod.is_due(current, now):
            return silent
        opener = check_mod.budgeted(check_mod.fetch, check_mod.DAILY_BUDGET)
        outcome = check_mod.scan(current, now, opener, check_mod.BASE_URLS, force=False)
        if outcome.state != current:
            state_mod.save(path, outcome.state)
        return (
            CommandResult(_session_json(outcome.updates), raw=True) if outcome.updates else silent
        )
    except Exception:  # noqa: BLE001 - a session must start whatever happens here
        return silent


def _run_check(args: argparse.Namespace) -> CommandResult | dict[str, Any]:
    if args.daily:
        return _run_daily()
    path = _state_path()
    outcome = check_mod.scan(
        state_mod.load(path), datetime.now(UTC), check_mod.fetch, check_mod.BASE_URLS, force=True
    )
    state_mod.save(path, outcome.state)
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


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("skills", help=i18n.t("skills.group.help"))
    commands = group.add_subparsers(dest="skills_command", required=True)
    listing = commands.add_parser("list", help=i18n.t("skills.list.help"))
    listing.set_defaults(handler=_run_list)
    checking = commands.add_parser("check", help=i18n.t("skills.check.help"))
    checking.add_argument("--daily", action="store_true", help=i18n.t("skills.check.daily"))
    checking.add_argument("--json", action="store_true", help=i18n.t("skills.check.json"))
    checking.set_defaults(handler=_run_check)
    declining = commands.add_parser("decline", help=i18n.t("skills.decline.help"))
    declining.add_argument("source", help=i18n.t("skills.decline.source"))
    declining.set_defaults(handler=_run_decline)
