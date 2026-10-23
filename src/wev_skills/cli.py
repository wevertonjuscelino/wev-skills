"""Command-line entry point. Command groups live in ``wev_skills.commands.<group>``."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wev_skills import commands, i18n
from wev_skills.commands import Subparsers
from wev_skills.core.active import ambient_language
from wev_skills.core.errors import WevError

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130  # the shell's code for a run stopped by Ctrl-C
STREAMS = ("stdout", "stderr")


@dataclass(frozen=True)
class CommandResult:
    """What a handler may return instead of a plain payload, to choose the exit code.

    ``payload`` is printed as JSON on ``stream`` (``stdout`` or ``stderr``). With
    ``raw=True`` the payload must be a string and is printed as it is (for Markdown); an
    empty raw payload prints nothing at all, which is how a hook says "no opinion".
    """

    payload: Any
    exit_code: int = EXIT_OK
    stream: str = "stdout"
    raw: bool = False


def _debug() -> bool:
    return os.environ.get("WEV_DEBUG") == "1"


def _warn(message: str) -> None:
    print(json.dumps({"warning": message}, ensure_ascii=False), file=sys.stderr)


def discover_command_modules() -> list[str]:
    """Names of every public module in ``wev_skills.commands``, sorted."""
    return sorted(
        info.name
        for info in pkgutil.iter_modules(commands.__path__)
        if not info.name.startswith("_")
    )


def _register_commands(subparsers: Subparsers) -> None:
    for name in discover_command_modules():
        qualified = f"{commands.__name__}.{name}"
        try:
            module = importlib.import_module(qualified)
            module.register(subparsers)
        except Exception as exc:  # noqa: BLE001 - one broken group must not break the CLI
            if _debug():
                raise
            _warn(f"command group '{name}' disabled: {type(exc).__name__}: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wev", description=i18n.t("cli.description"))
    parser.add_argument("--lang", default=None, help=i18n.t("cli.help.lang"))
    parser.add_argument("--config", default=None, help=i18n.t("cli.help.config"))
    subparsers = parser.add_subparsers(dest="command", metavar="<group>", required=True)
    _register_commands(subparsers)
    return parser


def _prescan_lang(argv: Sequence[str]) -> str | None:
    probe = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    probe.add_argument("--lang", default=None)
    try:
        known, _ = probe.parse_known_args(list(argv))
    except argparse.ArgumentError:
        return None
    lang: str | None = known.lang
    return lang


def _config_language(args: argparse.Namespace) -> str | None:
    """The ``language`` of the configuration this command resolves to, when it sets one."""
    try:
        return ambient_language(Path.cwd(), getattr(args, "config", None))
    except WevError, OSError:
        return None


def _emit_error(payload: dict[str, Any]) -> None:
    print(json.dumps({"error": payload}, ensure_ascii=False, indent=2), file=sys.stderr)


def _run(argv: Sequence[str]) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_usage(sys.stderr)
        return EXIT_USAGE
    with i18n.use_config_language(_config_language(args)):
        returned = handler(args)
    result = returned if isinstance(returned, CommandResult) else CommandResult(returned)
    try:
        text = _render(result)
    except TypeError, ValueError:
        message = i18n.t("cli.error.bad_result")
        _emit_error({"code": "bad_result", "message": message, "details": {}})
        return EXIT_UNEXPECTED
    if text or not result.raw:
        print(text, file=sys.stderr if result.stream == "stderr" else sys.stdout)
    return result.exit_code


def _render(result: CommandResult) -> str:
    """Text to print for ``result``; raises ``TypeError``/``ValueError`` when it is unusable."""
    if result.stream not in STREAMS or isinstance(result.exit_code, bool):
        raise ValueError("invalid command result")
    if not isinstance(result.exit_code, int):
        raise TypeError("exit code must be an integer")
    if result.raw:
        if not isinstance(result.payload, str):
            raise TypeError("raw payload must be text")
        return result.payload.rstrip("\n")
    return json.dumps(result.payload, ensure_ascii=False, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        with i18n.use_language(_prescan_lang(args)):
            return _run(args)
    except WevError as exc:
        _emit_error(exc.to_dict())
        return exc.exit_code
    except KeyboardInterrupt:
        print(i18n.t("cli.error.interrupted"), file=sys.stderr)
        return EXIT_INTERRUPTED
    except Exception as exc:  # noqa: BLE001 - last-resort boundary, reported without traceback
        if _debug():
            traceback.print_exc()
        _emit_error(
            {
                "code": "unexpected_error",
                "message": i18n.t("cli.error.unexpected"),
                "details": {"type": type(exc).__name__},
            }
        )
        return EXIT_UNEXPECTED
