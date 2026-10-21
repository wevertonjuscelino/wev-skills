"""``wev state show|list|drift``. Runs live under ``<config.state_dir>/runs/<run_id>/``."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._orchestration import Location, locate, resolve_run_id
from wev_skills.core import active
from wev_skills.core.engine import excluded_paths
from wev_skills.core.errors import WevError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.state.resume import check_drift
from wev_skills.state.store import StateStore, active_run, latest_run, list_runs, run_dir


def _store(args: argparse.Namespace, location: Location | None = None) -> StateStore:
    """The store of ``--run`` or of the active run, under the repository's state directory."""
    where = location or locate(args)
    return StateStore(run_dir(where.state_dir, resolve_run_id(args, where)))


def _show(args: argparse.Namespace) -> dict[str, Any]:
    location = locate(args)
    state = _store(args, location).load()
    registered = active.is_registered(location.state_dir, state.run_id)
    return {**state.to_dict(), "registered": registered}


def _summary(state_dir: Path, run_id: str) -> dict[str, Any]:
    try:
        state = StateStore(run_dir(state_dir, run_id)).load()
    except WevError as exc:
        return {"run_id": run_id, "error": exc.to_dict()}
    return {
        "run_id": run_id,
        "objective": state.objective,
        "mode": state.mode.value,
        "phase": state.phase.value,
        "revision": state.revision,
        "updated_at": state.updated_at,
    }


def _active(state_dir: Path) -> str | None:
    try:
        return active_run(state_dir)
    except WevError:
        return None


def _list(args: argparse.Namespace) -> dict[str, Any]:
    state_dir = locate(args).state_dir
    current = _active(state_dir)
    return {
        "state_dir": str(state_dir),
        "active": current,
        "active_registered": current is not None and active.is_registered(state_dir, current),
        "latest": latest_run(state_dir),
        "runs": [_summary(state_dir, run_id) for run_id in list_runs(state_dir)],
    }


def _drift(args: argparse.Namespace) -> dict[str, Any]:
    location = locate(args)
    state = _store(args, location).load()
    root = state.repo.root if state.repo else str(location.root)
    exclude = excluded_paths(root, location.state_dir)
    report = check_drift(state, SubprocessRunner(), exclude=exclude)
    return {"run_id": state.run_id, **report.to_dict()}


def register(subparsers: Subparsers) -> None:
    state = subparsers.add_parser("state", help=i18n.t("state.help"))
    actions = state.add_subparsers(dest="state_command", metavar="<command>", required=True)
    show = actions.add_parser("show", help=i18n.t("state.show.help"))
    show.add_argument("--run", default=None, help=i18n.t("state.arg.run"))
    show.set_defaults(handler=_show)
    listing = actions.add_parser("list", help=i18n.t("state.list.help"))
    listing.set_defaults(handler=_list)
    drift = actions.add_parser("drift", help=i18n.t("state.drift.help"))
    drift.add_argument("--run", default=None, help=i18n.t("state.arg.run"))
    drift.set_defaults(handler=_drift)
