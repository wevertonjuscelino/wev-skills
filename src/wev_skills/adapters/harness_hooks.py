"""Translate the Claude Code hook protocol for Codex, Gemini CLI and OpenCode.

``wev hook pre-tool-use --harness X`` turns the harness payload into the Claude-shaped one
(``to_claude_payload``), runs the existing guard, and turns its answer back
(``from_claude_answer``). The guard's verdicts are not changed here.

Sources (docs/research/harness-*.md): Codex shell tool ``Bash`` (openai/codex
rust-v0.160.0), Gemini ``run_shell_command``, OpenCode ``bash``.

Mapping of the guard's answer:

- ``deny``: Codex, stdout ``hookSpecificOutput`` with ``permissionDecision: deny``, exit 0;
  Gemini, stdout ``{"decision": "deny", "reason": ...}``, exit 0; OpenCode, stdout
  ``{"decision": "deny", "reason": ...}``, exit 0.
- ``ask`` from policy: these hooks have no ask decision (owner ruling: allow plus a
  warning). Codex: the
  warning on stderr, exit 0. Gemini: ``{"decision": "allow", "systemMessage": ...}``.
  OpenCode: ``{"decision": "allow", "reason": <warning>}``.
- ``ask`` marked ``person_only`` (a human-operator command, ``harness install|uninstall``):
  deny, same formats as ``deny``, reason ``hooks.reason.person_only_denied``.
- ``ask`` marked ``fail_safe`` (the guard could not judge: unreadable input, internal error,
  untrusted registry, unknown target, an answer the codec cannot parse): deny, same formats
  as ``deny`` with the reason ``hooks.reason.fail_safe_denied``.
- no opinion: empty stdout, exit 0.

Working directory: a shell call may name its own directory (Gemini ``dir_path`` in
``tool_input``, OpenCode ``workdir`` in ``args``, Codex ``workdir``); it is resolved against
the payload ``cwd`` and passed to the guard as ``cwd``. A value that is not a string, or does
not resolve to an existing directory, raises ``ValidationError`` (the hook then denies).

OpenCode answer contract for the plugin (Task 5): stdin is
``{"tool": "bash", "args": {"command": ...}, "cwd": ...}``; stdout is empty (allow) or one
JSON object ``{"decision": "allow" | "deny", "reason": str}``; the plugin throws on
``deny`` and may show ``reason`` of an ``allow`` as a warning.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code import hooks
from wev_skills.adapters.claude_code.bash_guard import HookVerdict
from wev_skills.core.errors import ValidationError

HARNESSES = ("claude", "codex", "gemini", "opencode")
_SHELL_TOOL = {"codex": "Bash", "gemini": "run_shell_command", "opencode": "bash"}
_WORKDIR_KEY = {"codex": "workdir", "gemini": "dir_path", "opencode": "workdir"}
ALLOW = "allow"


@dataclass(frozen=True)
class HookOutput:
    stdout: str
    stderr: str
    exit_code: int


def _shell_input(harness: str, payload: Mapping[str, Any]) -> tuple[object, object]:
    if harness == "opencode":
        return payload.get("tool"), payload.get("args")
    return payload.get("tool_name"), payload.get("tool_input")


def to_claude_payload(harness: str, payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """The Claude-shaped payload of a shell call, or ``None`` (no opinion) for anything else."""
    tool, arguments = _shell_input(harness, payload)
    if tool != _SHELL_TOOL.get(harness) or not isinstance(arguments, Mapping):
        return None
    command = arguments.get("command")
    if not isinstance(command, str):
        return None
    cwd = _workdir(arguments, payload.get("cwd"), _WORKDIR_KEY[harness])
    return {"tool_name": hooks.BASH_TOOL, "tool_input": {"command": command}, "cwd": cwd}


def _workdir(arguments: Mapping[str, Any], cwd: object, key: str) -> object:
    """The directory the call runs in: its own, resolved against the session ``cwd``."""
    if key not in arguments:
        return cwd
    named = arguments[key]
    base = cwd if isinstance(cwd, str) else ""
    if not isinstance(named, str) or not named or "\x00" in named:
        raise ValidationError("hook_bad_workdir", i18n.t("hooks.error.workdir"))
    if not os.path.isabs(named) and not os.path.isabs(base):
        raise ValidationError("hook_bad_workdir", i18n.t("hooks.error.workdir"))
    resolved = os.path.normpath(os.path.join(base, named))
    if not Path(resolved).is_dir():
        raise ValidationError("hook_bad_workdir", i18n.t("hooks.error.workdir"))
    return resolved


def _parse(answer: str) -> HookVerdict:
    """The verdict inside a Claude PreToolUse answer; unreadable is a fail-safe ask."""
    if not answer:
        return HookVerdict()
    try:
        specific = json.loads(answer)["hookSpecificOutput"]
        decision = str(specific["permissionDecision"])
        reason = str(specific["permissionDecisionReason"])  # a policy answer always has one
    except ValueError, KeyError, TypeError, AttributeError:
        return HookVerdict(hooks.ASK, "", fail_safe=True)
    return HookVerdict(decision, reason, fail_safe=False)


def _json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def from_claude_answer(harness: str, answer: str) -> HookOutput:
    """The harness's own output for a Claude PreToolUse answer."""
    return from_verdict(harness, _parse(answer))


def from_verdict(harness: str, verdict: HookVerdict) -> HookOutput:
    """The harness's own output for a guard verdict."""
    if verdict.decision == hooks.NO_OPINION:
        return HookOutput("", "", 0)
    if verdict.decision == hooks.DENY:
        return HookOutput(_deny(harness, verdict.reason), "", 0)
    if verdict.person_only:
        reason = i18n.t("hooks.reason.person_only_denied", reason=verdict.reason)
        return HookOutput(_deny(harness, reason), "", 0)
    if verdict.fail_safe:
        reason = i18n.t("hooks.reason.fail_safe_denied", reason=verdict.reason)
        return HookOutput(_deny(harness, reason), "", 0)
    warning = i18n.t("hooks.reason.ask_as_warning", reason=verdict.reason)
    if harness == "codex":
        return HookOutput("", warning, 0)
    key = "systemMessage" if harness == "gemini" else "reason"
    return HookOutput(_json({"decision": ALLOW, key: warning}), "", 0)


def _deny(harness: str, reason: str) -> str:
    if harness == "codex":
        specific = {"hookEventName": hooks.HOOK_EVENT, "permissionDecision": hooks.DENY,
                    "permissionDecisionReason": reason}  # fmt: skip
        return _json({"hookSpecificOutput": specific})
    return _json({"decision": hooks.DENY, "reason": reason})


def session_context_output(harness: str, text: str) -> str:
    """The brief in the harness's SessionStart context format; OpenCode takes plain text."""
    if not text or harness in ("claude", "opencode"):
        return text
    return _json({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                         "additionalContext": text}})  # fmt: skip
