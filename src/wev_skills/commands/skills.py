"""``wev skills list``: the third-party skill sources and what is installed from each."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.third_party import state as state_mod
from wev_skills.third_party.sources import SOURCES


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


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("skills", help=i18n.t("skills.group.help"))
    commands = group.add_subparsers(dest="skills_command", required=True)
    listing = commands.add_parser("list", help=i18n.t("skills.list.help"))
    listing.set_defaults(handler=_run_list)
