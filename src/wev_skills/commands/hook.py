"""``wev hook session-context|prompt-reminder|pre-tool-use``: the Claude Code plugin hooks.

Each command reads the hook JSON on stdin (at most 1 MiB) and prints what Claude Code
expects, or nothing. The logic, its scope rule and its failure policy are in
``adapters.claude_code.hooks``. The configuration is always the active run's pinned one: a
``--config`` given on the hook's own command line is ignored.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Callable, Mapping
from typing import Any

from wev_skills import i18n
from wev_skills.adapters import harness_hooks
from wev_skills.adapters.claude_code import hooks
from wev_skills.adapters.claude_code.bash_guard import ASK, HookVerdict
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


def _note(name: str, error: Exception) -> None:
    """The stderr line of a failed hook; if even that fails, nothing is printed."""
    with contextlib.suppress(Exception):  # reporting must not replace the answer
        print(hooks.failure_note(name, error), file=sys.stderr)


def _failed(name: str, error: Exception) -> str:
    """What a hook prints after an unexpected error: the Bash pre-check asks, the brief
    hooks only add context and stay silent."""
    _note(name, error)
    return hooks.internal_error(error) if name == PRE_TOOL_USE else ""


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
        return _failed(name, exc)


def run_harness_pre_tool_use(harness: str) -> HookVerdict:
    """The guard's verdict for another harness's payload; whatever goes wrong is a fail-safe
    ask, which the codec turns into that harness's deny."""
    text = ""
    try:
        text = _read_input()
        try:
            claude = harness_hooks.to_claude_payload(harness, hooks.parse_payload(text))
        except ValidationError as exc:
            _note(PRE_TOOL_USE, exc)
            if exc.code == "hook_bad_workdir":
                return HookVerdict(ASK, str(exc), fail_safe=True)
            return hooks.unreadable_verdict(text)
        return HookVerdict() if claude is None else hooks.pre_tool_use_verdict(claude)
    except Exception as exc:  # noqa: BLE001 - a broken engine must never crash the session
        _note(PRE_TOOL_USE, exc)
        return hooks.internal_verdict(exc)


def _handler(name: str) -> Handler:
    def handle(args: argparse.Namespace) -> CommandResult:
        harness: str = getattr(args, "harness", "claude")
        if harness == "claude":
            return CommandResult(run_hook(name), raw=True)
        if name != PRE_TOOL_USE:
            text = run_hook(name)
            return CommandResult(harness_hooks.session_context_output(harness, text), raw=True)
        output = harness_hooks.from_verdict(harness, run_harness_pre_tool_use(harness))
        if output.stderr:
            print(output.stderr, file=sys.stderr)
        return CommandResult(output.stdout, output.exit_code, raw=True)

    return handle


def register(subparsers: Subparsers) -> None:
    hook = subparsers.add_parser(
        "hook", help=i18n.t("hooks.help"), description=i18n.t("hooks.help")
    )
    actions = hook.add_subparsers(dest="hook_command", metavar="<command>", required=True)
    for name in HOOKS:
        parser = actions.add_parser(name, help=i18n.t(f"hooks.{name}.help"))
        if name == "prompt-reminder":  # a Claude Code hook only; other harnesses have none
            parser.set_defaults(handler=_handler(name))
            continue
        parser.add_argument("--harness", choices=harness_hooks.HARNESSES, default="claude",
                            help=i18n.t("hooks.harness.help"))  # fmt: skip
        parser.set_defaults(handler=_handler(name))
