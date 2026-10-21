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
- ``ask``: none of these hooks can ask (owner ruling: allow plus a warning). Codex: the
  warning on stderr, exit 0. Gemini: ``{"decision": "allow", "systemMessage": ...}``.
  OpenCode: ``{"decision": "allow", "reason": <warning>}``.
- no opinion: empty stdout, exit 0.

OpenCode answer contract for the plugin (Task 5): stdin is
``{"tool": "bash", "args": {"command": ...}, "cwd": ...}``; stdout is empty (allow) or one
JSON object ``{"decision": "allow" | "deny", "reason": str}``; the plugin throws on
``deny`` and may show ``reason`` of an ``allow`` as a warning.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code import hooks

HARNESSES = ("claude", "codex", "gemini", "opencode")
_SHELL_TOOL = {"codex": "Bash", "gemini": "run_shell_command", "opencode": "bash"}
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
    return {"tool_name": hooks.BASH_TOOL, "tool_input": {"command": command},
            "cwd": payload.get("cwd")}  # fmt: skip


def _decision(answer: str) -> tuple[str, str]:
    """The decision and reason inside a Claude PreToolUse answer; unreadable means ask."""
    try:
        specific = json.loads(answer)["hookSpecificOutput"]
        reason = specific.get("permissionDecisionReason", "")
        return str(specific["permissionDecision"]), str(reason)
    except ValueError, KeyError, TypeError:
        return hooks.ASK, ""


def _json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False)


def from_claude_answer(harness: str, answer: str) -> HookOutput:
    """The harness's own output for a Claude PreToolUse answer."""
    if not answer:
        return HookOutput("", "", 0)
    decision, reason = _decision(answer)
    if decision == hooks.DENY:
        return HookOutput(_deny(harness, reason), "", 0)
    warning = i18n.t("hooks.reason.ask_as_warning", reason=reason)
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
