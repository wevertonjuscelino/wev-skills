"""Handlers of ``wev skills update|rollback|freeze|show|activate|deactivate``."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path
from typing import Any

from wev_skills.cli import CommandResult
from wev_skills.core.errors import RemoteError, WevError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.third_party import activate, check, fetch, health, state, switch
from wev_skills.third_party.sources import SOURCES, Source, source

EXIT_UPDATE_FAILED = RemoteError.exit_code


def _state_path() -> Path:
    return state.data_home() / "state.json"


def _net(url: str, timeout: float) -> bytes:
    """Tarballs go through the bounded download, everything else through the JSON fetch."""
    return (fetch.download if "/tarball/" in url else check.fetch)(url, timeout)


def _row(src: Source, result: switch.UpdateResult) -> dict[str, Any]:
    return {
        "source": src.name,
        "ok": result.ok,
        "code": result.code,
        "version": result.version,
        "health": health.render(result.health) if result.health else None,
    }


def _update_one(src: Source, yes: bool) -> dict[str, Any]:
    path = _state_path()
    new, result = switch.update(
        src, state.data_home(), state.load(path), _net, SubprocessRunner(), check.BASE_URLS, yes=yes
    )
    if result.code == "updated":
        state.save(path, new)
    return _row(src, result)


def run_update(args: argparse.Namespace) -> CommandResult | dict[str, Any]:
    if args.source:
        return _finish([_update_one(source(args.source), args.yes)])
    current = state.load(_state_path())
    rows = []
    for src in SOURCES:
        if current.sources.get(src.name, state.SourceState()).frozen:
            rows.append({"source": src.name, "ok": True, "code": "frozen", "version": None})
            continue
        try:
            rows.append(_update_one(src, args.yes))
        except WevError as exc:
            rows.append({"source": src.name, "ok": False, "code": exc.code, "version": None})
    return _finish(rows)


def _finish(rows: list[dict[str, Any]]) -> CommandResult | dict[str, Any]:
    payload = {"results": rows}
    return payload if all(r["ok"] for r in rows) else CommandResult(payload, EXIT_UPDATE_FAILED)


def _item(path: Path, src: Source) -> state.SourceState:
    return state.load(path).sources.get(src.name, state.SourceState())


def run_rollback(args: argparse.Namespace) -> dict[str, Any]:
    src, path = source(args.source), _state_path()
    new = switch.rollback(src, state.data_home(), state.load(path))
    state.save(path, new)
    item = new.sources[src.name]
    return {"source": src.name, "active": item.active, "previous": item.previous}


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
