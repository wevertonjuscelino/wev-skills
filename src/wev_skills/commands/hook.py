"""``wev hook session-context|prompt-reminder|pre-tool-use``: the Claude Code plugin hooks.

Each command reads the hook JSON on stdin (at most 1 MiB) and prints what Claude Code
expects, or nothing. The logic, its scope rule and its failure policy are in
``adapters.claude_code.hooks``. The configuration is always the active run's pinned one: a
``--config`` given on the hook's own command line is ignored.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code import hooks
from wev_skills.cli import CommandResult
from wev_skills.commands import Handler, Subparsers
from wev_skills.core.errors import ValidationError

Hook = Callable[[Mapping[str, Any]], str]

PRE_TOOL_USE = "pre-tool-use"
HOOKS: dict[str, Hook] = {
    "session-context": hooks.session_context,
    "prompt-reminder": hooks.prompt_reminder,
    PRE_TOOL_USE: hooks.pre_tool_use,
}


def _read_input() -> str:
    """The hook JSON, capped; a terminal on stdin means nobody is sending one."""
    stream = sys.stdin
    if stream is None or stream.isatty():
        return ""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream.read(hooks.MAX_INPUT_BYTES + 1)
    data: bytes = buffer.read(hooks.MAX_INPUT_BYTES + 1)
    return data.decode("utf-8", errors="replace")


def _unreadable(name: str, text: str) -> str:
    """What a hook prints for input it cannot parse: the Bash pre-check still fails safe."""
    return hooks.unreadable_input(text) if name == PRE_TOOL_USE else ""


def run_hook(name: str) -> str:
    """What the hook prints. An error leaves one stderr line; see the module for when the
    Bash pre-check answers ``ask`` instead of nothing."""
    text = ""
    try:
        text = _read_input()
        try:
            payload = hooks.parse_payload(text)
        except ValidationError as exc:
            print(hooks.failure_note(name, exc), file=sys.stderr)
            return _unreadable(name, text)
        return HOOKS[name](payload)
    except Exception as exc:  # noqa: BLE001 - a broken engine must never crash the session
        print(hooks.failure_note(name, exc), file=sys.stderr)
        return ""


def _handler(name: str) -> Handler:
    def handle(args: argparse.Namespace) -> CommandResult:
        return CommandResult(run_hook(name), raw=True)

    return handle


def register(subparsers: Subparsers) -> None:
    hook = subparsers.add_parser(
        "hook", help=i18n.t("hooks.help"), description=i18n.t("hooks.help")
    )
    actions = hook.add_subparsers(dest="hook_command", metavar="<command>", required=True)
    for name in HOOKS:
        parser = actions.add_parser(name, help=i18n.t(f"hooks.{name}.help"))
        parser.set_defaults(handler=_handler(name))
