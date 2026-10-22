"""Handlers of ``wev skills update|rollback|freeze|show|activate|deactivate``."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

from wev_skills.cli import CommandResult
from wev_skills.core.errors import RemoteError, StateConflict, WevError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.third_party import activate, check, fetch, health, state, switch
from wev_skills.third_party.sources import SOURCES, Source, source

EXIT_UPDATE_FAILED = RemoteError.exit_code


def _state_path() -> Path:
    return state.data_home() / "state.json"


def _row(src: Source, result: switch.UpdateResult) -> dict[str, Any]:
    return {
        "source": src.name,
        "ok": result.ok,
        "code": result.code,
        "version": result.version,
        "health": health.render(result.health) if result.health else None,
    }


def _relink(src: Source) -> dict[str, Any]:
    """Re-run the activation the person made, so it follows the new ``current``: links of
    dropped skills go, new skills are linked. Nothing to follow without a manifest."""
    home = state.data_home()
    if src.name != activate.TARGET or not (home / "manifest.json").is_file():
        return {}
    try:
        links = activate.activate(home, activate.default_roots()).files
    except WevError as exc:
        return {"activation": {"ok": False, "code": exc.code, "message": exc.message}}
    return {"activation": {"ok": True, "links": list(links)}}


def _update_one(src: Source, yes: bool) -> dict[str, Any]:
    path = _state_path()
    new, result = switch.update(
        src,
        state.data_home(),
        state.load(path),
        check.bounded(check.fetch, check.INTERACTIVE_BUDGET),
        SubprocessRunner(),
        check.BASE_URLS,
        yes=yes,
    )
    if result.code != "updated":
        return _row(src, result)
    state.save(path, new)
    return {**_row(src, result), **_relink(src)}


def _skipped(src: Source, code: str, *, ok: bool = True) -> dict[str, Any]:
    return {"source": src.name, "ok": ok, "code": code, "version": None}


def run_update(args: argparse.Namespace) -> CommandResult | dict[str, Any]:
    if args.source:
        return _finish([_update_one(source(args.source), args.yes)])
    current = state.load(_state_path())
    rows = []
    for src in SOURCES:
        item = current.sources.get(src.name, state.SourceState())
        skipped = "frozen" if item.frozen else "not_installed" if item.active is None else None
        if skipped:
            rows.append(_skipped(src, skipped))
            continue
        try:
            rows.append(_update_one(src, args.yes))
        except WevError as exc:
            rows.append(_skipped(src, exc.code, ok=exc.code == "declined"))
    return _finish(rows)


def _finish(rows: list[dict[str, Any]]) -> CommandResult | dict[str, Any]:
    payload = {"results": rows}
    failed = any(not r["ok"] or not r.get("activation", {"ok": True})["ok"] for r in rows)
    return CommandResult(payload, EXIT_UPDATE_FAILED) if failed else payload


def _item(path: Path, src: Source) -> state.SourceState:
    return state.load(path).sources.get(src.name, state.SourceState())


def run_rollback(args: argparse.Namespace) -> CommandResult | dict[str, Any]:
    src, path = source(args.source), _state_path()
    new = switch.rollback(src, state.data_home(), state.load(path))
    state.save(path, new)
    item = new.sources[src.name]
    payload: dict[str, Any] = {"source": src.name, "active": item.active, "previous": item.previous}
    payload |= _relink(src)
    if payload.get("activation", {"ok": True})["ok"]:
        return payload
    return CommandResult(payload, StateConflict.exit_code)


def run_freeze(args: argparse.Namespace) -> dict[str, Any]:
    src, path = source(args.source), _state_path()
    state.save(path, switch.freeze(src, state.load(path), not args.off))
    return {"source": src.name, "frozen": not args.off}


def run_show(args: argparse.Namespace) -> dict[str, Any]:
    src = source(args.source)
    item = _item(_state_path(), src)
    payload: dict[str, Any] = {"source": src.name, "state": asdict(item)}
    if src.name == "rea":
        payload["mcp_argv"] = list(fetch.mcp_argv(item.active)) if item.active else None
    return payload


def run_activate(_args: argparse.Namespace) -> dict[str, Any]:
    manifest = activate.activate(state.data_home(), activate.default_roots())
    return {"links": list(manifest.files)}


def run_deactivate(_args: argparse.Namespace) -> dict[str, Any]:
    return {"removed": list(activate.deactivate(state.data_home(), activate.default_roots()))}
