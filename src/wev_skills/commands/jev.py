"""``wev jev status|ask|batch``: the built-in JEV client from the command line."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.cli import EXIT_OK, CommandResult
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import resolve_scope
from wev_skills.config import BUILTIN, read_json_object
from wev_skills.core.errors import ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.decisions.jev_http import (
    HttpAsker,
    build_http_asker,
    resolve_endpoint,
    validate_questions,
)
from wev_skills.decisions.jev_key import ApiKey, env_file_path, macos_keychain, resolve_api_key
from wev_skills.decisions.jev_wire import JevUnavailable
from wev_skills.security.redact import redact

BATCH_WORKERS = 4
EXIT_PROVIDER_FAILED = 8


@dataclass(frozen=True)
class _Item:
    id: str
    state: str


def _reason(exc: JevUnavailable) -> str:
    return exc.message or exc.code


def _key_or_error() -> tuple[ApiKey | None, str | None]:
    """The key, or the reason it could not be read; never the key's value in a message."""
    try:
        return resolve_api_key(os.environ, env_file_path(), macos_keychain), None
    except JevUnavailable as exc:
        return None, _reason(exc)


def _builtin_status() -> dict[str, Any]:
    """Endpoint and key facts of the built-in client; no network call is made."""
    try:
        endpoint = resolve_endpoint(os.environ)
    except JevUnavailable as exc:
        return {"key_source": None, "key_error": _reason(exc), "endpoint": "", "usable": False}
    key, error = _key_or_error()
    if key is None and error is None:
        error = i18n.t("decisions.jev.why.key_missing")
    return {
        "key_source": key.source if key is not None else None,
        "key_error": error if key is None else None,
        "endpoint": endpoint.url,
        "usable": endpoint.local or key is not None,
    }


def _run_status(args: argparse.Namespace) -> dict[str, Any]:
    decision = resolve_scope(args.config).config.decision
    program = decision.jev.command != BUILTIN
    facts = (
        {"key_source": None, "key_error": None, "endpoint": "", "usable": True}
        if program
        else _builtin_status()
    )
    jev = decision.provider == "jev"
    return {
        "provider": decision.provider,
        "client": "program" if program else "builtin",
        "key_source": facts["key_source"],
        "key_error": facts["key_error"],
        "endpoint": facts["endpoint"],
        "orchestration": "wev" if jev and facts["usable"] else "harness",
    }


def _read_questions(path: str) -> dict[str, Any]:
    questions = read_json_object(path)
    validate_questions(questions)
    return questions


def _read_state(args: argparse.Namespace) -> str:
    if args.state is not None:
        return str(args.state)
    try:
        with open(args.state_file, encoding="utf-8") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        message = i18n.t("jev.error.state_unreadable", path=args.state_file)
        raise ValidationError("state_unreadable", message, {"path": args.state_file}) from exc


def _asker(args: argparse.Namespace) -> HttpAsker:
    return build_http_asker(resolve_scope(args.config).config.decision.jev.timeout_seconds)


def _run_ask(args: argparse.Namespace) -> dict[str, Any]:
    questions = _read_questions(args.questions)
    state = redact(_read_state(args))
    return {"answers": json.loads(_asker(args)(questions, state))}


def _bad_line(path: str, number: int, why_key: str, **params: object) -> ValidationError:
    why = i18n.t(why_key, **params)
    message = i18n.t("jev.error.item_line", path=path, line=number, why=why)
    return ValidationError("invalid_items", message, {"path": path, "line": number})


def _parse_item(path: str, number: int, line: str, seen: set[str]) -> _Item:
    try:
        data = json.loads(line)
    except ValueError:
        raise _bad_line(path, number, "jev.error.item_not_json") from None
    ident = data.get("id") if isinstance(data, dict) else None
    state = data.get("state") if isinstance(data, dict) else None
    if not isinstance(ident, str) or not isinstance(state, str):
        raise _bad_line(path, number, "jev.error.item_shape")
    if ident in seen:
        raise _bad_line(path, number, "jev.error.item_duplicate_id", id=ident)
    seen.add(ident)
    return _Item(ident, state)


def _read_items(path: str) -> list[_Item]:
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        message = i18n.t("jev.error.items_unreadable", path=path)
        raise ValidationError("items_unreadable", message, {"path": path}) from exc
    seen: set[str] = set()
    items = [
        _parse_item(path, number, line, seen)
        for number, line in enumerate(lines, start=1)
        if line.strip()
    ]
    if not items:
        raise ValidationError("no_items", i18n.t("jev.error.no_items", path=path), {"path": path})
    return items


def _answer_item(asker: HttpAsker, questions: dict[str, Any], item: _Item) -> dict[str, Any]:
    try:
        return {"id": item.id, "answers": json.loads(asker(questions, redact(item.state)))}
    except JevUnavailable as exc:
        return {"id": item.id, "error": i18n.t("jev.error.item_failed", why=_reason(exc))}


def _run_batch(args: argparse.Namespace) -> CommandResult:
    questions = _read_questions(args.questions)
    items = _read_items(args.items)
    asker = _asker(args)
    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        rows = list(pool.map(lambda item: _answer_item(asker, questions, item), items))
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    try:
        atomic_write_text(Path(args.out), text)
    except OSError as exc:
        message = i18n.t("jev.error.out_unwritable", path=args.out)
        raise ValidationError("out_unwritable", message, {"path": args.out}) from exc
    failed = sum(1 for row in rows if "error" in row)
    payload = {"ok": len(rows) - failed, "failed": failed, "out": args.out}
    return CommandResult(payload, EXIT_PROVIDER_FAILED if failed else EXIT_OK)


def register(subparsers: Subparsers) -> None:
    group = subparsers.add_parser("jev", help=i18n.t("jev.group.help"))
    commands = group.add_subparsers(dest="jev_command", required=True)

    status = commands.add_parser("status", help=i18n.t("jev.status.help"))
    status.set_defaults(handler=_run_status)

    ask = commands.add_parser("ask", help=i18n.t("jev.ask.help"))
    ask.add_argument("--questions", required=True, help=i18n.t("jev.arg.questions"))
    source = ask.add_mutually_exclusive_group(required=True)
    source.add_argument("--state", default=None, help=i18n.t("jev.arg.state"))
    source.add_argument("--state-file", default=None, help=i18n.t("jev.arg.state_file"))
    ask.set_defaults(handler=_run_ask)

    batch = commands.add_parser("batch", help=i18n.t("jev.batch.help"))
    batch.add_argument("--questions", required=True, help=i18n.t("jev.arg.questions"))
    batch.add_argument("--items", required=True, help=i18n.t("jev.arg.items"))
    batch.add_argument("--out", required=True, help=i18n.t("jev.arg.out"))
    batch.set_defaults(handler=_run_batch)
