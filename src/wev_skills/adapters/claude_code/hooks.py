"""Claude Code plugin hooks: re-inject the plan brief and pre-check Bash commands.

Three hooks, wired in ``hooks/hooks.json`` and run through ``wev hook <name>``:

- ``session-context`` (SessionStart after compaction or resume) and ``prompt-reminder``
  (UserPromptSubmit) print the brief of the active run, so the plan stays in front of the
  model. Whether that helps a given model is a hypothesis (docs/research/hypotheses.md, H8).
- ``pre-tool-use`` (PreToolUse for ``Bash``) judges the command under the active run's
  pinned configuration, mode and risk (``bash_guard``). Without a run it judges it under the
  built-in defaults (``Config()``) in execute mode at medium risk, rooted at the repository
  around ``cwd``; the repository's ``wev.config.json`` is not read, since a file in the tree
  must not loosen the guard. It answers ``deny`` or ``ask`` and otherwise prints nothing.
  It never answers ``allow`` and never reads the approval store: the person's answer in
  Claude Code's permission prompt is the approval for that call.

Scope: the run is looked up with ``core.active.find_active_run`` from the hook's ``cwd``
and from every path the command names, so a command started in ``/tmp`` or in a nested
repository that touches a run's tree, or a parent directory of it, is judged by that run.
A path built from a variable cannot be matched; with any run registered for the user such
a command is an ``ask``. Looking is read-only.

Failure policy: anything that goes wrong while judging a command (an unreadable or forged
state, an internal error, with or without a run) becomes ``ask`` with a reason naming the
problem, never silence. Input that cannot be read is an ``ask`` with a run and silent
without one: the command is unknown and there is nothing to judge it by. Approvals and loop
detection stay run-scoped; the hook uses neither.

Limits: only the Bash tool is checked. Edits made with Claude's own file tools are not seen
by the engine, and that includes edits to the state directory. This hook is a guardrail
against mistakes; an agent that sets out to defeat it has other tools to do so.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code import bash_guard
from wev_skills.adapters.claude_code.bash_guard import ASK, DENY, NO_OPINION, HookVerdict
from wev_skills.config import Config, find_repo_root, protect_state_dir
from wev_skills.core import wiring
from wev_skills.core.active import ActiveRun, find_active_run, registered_run
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.core.errors import ValidationError, WevError
from wev_skills.core.orchestrator import Orchestrator
from wev_skills.security.shell import SimpleCommand
from wev_skills.state.store import StateStore, run_dir

__all__ = [
    "ASK",
    "DENY",
    "MAX_INPUT_BYTES",
    "NO_OPINION",
    "HookVerdict",
    "failure_note",
    "parse_payload",
    "pre_tool_use",
    "prompt_reminder",
    "session_context",
    "unreadable_input",
]

HOOK_EVENT = "PreToolUse"
BASH_TOOL = "Bash"
MAX_CWD_CHARS = 4096
MAX_INPUT_BYTES = 1_048_576
SESSION_BRIEF_MAX_CHARS = 2000
NO_RUN_MODE = Mode.EXECUTE
NO_RUN_RISK = RiskLevel.MEDIUM
_CWD_FIELD = re.compile(r'"cwd"\s*:\s*("(?:[^"\\]|\\.){0,4096}")')


def parse_payload(text: str) -> dict[str, Any]:
    """The hook input as a JSON object; anything else is a ``ValidationError``."""
    if len(text.encode("utf-8", errors="replace")) > MAX_INPUT_BYTES:
        raise ValidationError("hook_bad_input", i18n.t("hooks.error.input"))
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValidationError("hook_bad_input", i18n.t("hooks.error.input")) from exc
    if not isinstance(data, dict):
        raise ValidationError("hook_bad_input", i18n.t("hooks.error.input"))
    return data


def _directory(cwd: object) -> Path | None:
    """``cwd`` as an existing absolute directory, or ``None`` for anything else."""
    if not isinstance(cwd, str) or not cwd or "\x00" in cwd or len(cwd) > MAX_CWD_CHARS:
        return None
    path = Path(os.path.normpath(cwd))
    try:
        return path if path.is_absolute() and path.is_dir() else None
    except OSError:
        return None


def _working_directory(cwd: object) -> Path:
    """The hook's directory: the payload's when usable, else the one the hook runs in."""
    return _directory(cwd) or Path.cwd()


def _orchestrator(active: ActiveRun) -> Orchestrator:
    services = wiring.build_services(active.config, active.root)
    store = StateStore(run_dir(active.state_dir, active.run_id), services.clock)
    return Orchestrator(store, services)


def _readable_run(payload: Mapping[str, Any]) -> ActiveRun | None:
    active = find_active_run(_working_directory(payload.get("cwd")))
    return active if active is not None and active.state_error is None else None


def session_context(payload: Mapping[str, Any]) -> str:
    """SessionStart: the brief of the active run under a line saying what it is."""
    active = _readable_run(payload)
    if active is None:
        return ""
    with i18n.use_config_language(active.language):
        intro = i18n.t("hooks.session.intro", run=active.run_id)
        return f"{intro}\n{_orchestrator(active).brief(SESSION_BRIEF_MAX_CHARS)}"


def prompt_reminder(payload: Mapping[str, Any]) -> str:
    """UserPromptSubmit: the brief, capped, when the run's ``harness.plan_reminder`` is on."""
    active = _readable_run(payload)
    if active is None or not active.config.harness.plan_reminder:
        return ""
    with i18n.use_config_language(active.language):
        return _orchestrator(active).brief(active.config.harness.plan_reminder_max_chars)


def _bash_command(payload: Mapping[str, Any]) -> str:
    """The command of a Bash tool call, or ``""`` for any other tool or shape."""
    tool_input = payload.get("tool_input")
    if payload.get("tool_name") != BASH_TOOL or not isinstance(tool_input, Mapping):
        return ""
    command = tool_input.get("command")
    return command if isinstance(command, str) and command.strip() else ""


def _output(decision: str, reason: str) -> str:
    output = {
        "hookEventName": HOOK_EVENT,
        "permissionDecision": decision,
        "permissionDecisionReason": reason[: bash_guard.MAX_REASON_CHARS],
    }
    return json.dumps({"hookSpecificOutput": output}, ensure_ascii=False)


def _answer(active: ActiveRun, verdict: HookVerdict) -> str:
    if verdict.decision == NO_OPINION:
        return ""
    with i18n.use_config_language(active.language):
        reason = i18n.t(
            "hooks.reason.context", run=active.run_id, mode=active.mode.value, reason=verdict.reason
        )
    return _output(verdict.decision, reason)


def _judge(active: ActiveRun, command: str, cwd: Path) -> HookVerdict:
    """The verdict under the run's own configuration; any failure here is an ``ask``."""
    if active.state_error is not None:
        reason = i18n.t("hooks.reason.state_error", error=active.state_error)
        return HookVerdict(ASK, reason)
    with i18n.use_config_language(active.language):
        return _guarded(active.config, active.root, active.mode, active.risk, command, cwd)


def _guarded(
    config: Config, root: Path, mode: Mode, risk: RiskLevel, command: str, cwd: Path
) -> HookVerdict:
    """The verdict under ``config`` with its state directory protected; a failure is an ``ask``."""
    try:
        policy = wiring.build_grantless_policy(protect_state_dir(config, root), root)
        context = bash_guard.GuardContext(mode, risk, policy, str(cwd), str(root))
        return bash_guard.decide_command(command, context)
    except Exception as exc:  # noqa: BLE001 - fail safe, never silent
        return _failed(exc)


def _failed(exc: Exception) -> HookVerdict:
    code = exc.code if isinstance(exc, WevError) else type(exc).__name__
    return HookVerdict(ASK, i18n.t("hooks.reason.internal_error", error=code))


def _without_run(command: str, cwd: Path) -> str:
    """No run governs the command: judge it under the built-in defaults, never a repository
    file, in execute mode at medium risk. The language follows the default rules."""
    try:
        root = find_repo_root(cwd)
    except Exception as exc:  # noqa: BLE001 - fail safe, never silent
        verdict = _failed(exc)
    else:
        verdict = _guarded(Config(), root, NO_RUN_MODE, NO_RUN_RISK, command, cwd)
    if verdict.decision == NO_OPINION:
        return ""
    reason = i18n.t("hooks.reason.no_run_context", mode=NO_RUN_MODE.value, reason=verdict.reason)
    return _output(verdict.decision, reason)


def _unknown_target(parts: Sequence[SimpleCommand] | None) -> str:
    """No run was found for the command, but a word comes from a variable: with any run
    registered for the user the target may be that run's tree, so a person decides."""
    if parts is None or not bash_guard.target_unknown(parts):
        return ""
    other = registered_run()
    if other is None:
        return ""
    with i18n.use_config_language(other.language):
        reason = i18n.t("hooks.reason.unknown_target", root=str(other.root))
    return _answer(other, HookVerdict(ASK, reason))


def pre_tool_use(payload: Mapping[str, Any]) -> str:
    """PreToolUse for Bash: a ``deny`` or ``ask`` decision as JSON, or ``""`` (no opinion)."""
    command = _bash_command(payload)
    if not command:
        return ""
    cwd = _working_directory(payload.get("cwd"))
    parts = bash_guard.split_bounded(command)
    paths = bash_guard.command_paths(parts, str(cwd)) if parts is not None else ()
    targets = bash_guard.target_paths(parts, str(cwd)) if parts is not None else ()
    active = find_active_run(cwd, paths, targets)
    if active is None:
        return _unknown_target(parts) or _without_run(command, cwd)
    return _answer(active, _judge(active, command, cwd))


def _claimed_directory(text: str) -> Path:
    """The ``cwd`` field of input that is not valid JSON, when it can still be read."""
    match = _CWD_FIELD.search(text)
    try:
        claimed = json.loads(match.group(1)) if match else None
    except ValueError:
        claimed = None
    return _working_directory(claimed)


def unreadable_input(text: str) -> str:
    """PreToolUse input that cannot be read (oversized, truncated, not JSON).

    The command is unknown, so nothing can be judged: with a run for the directory the
    answer is ``ask``; without one the hook stays silent.
    """
    active = find_active_run(_claimed_directory(text))
    if active is None:
        return ""
    with i18n.use_config_language(active.language):
        return _answer(active, HookVerdict(ASK, i18n.t("hooks.reason.unreadable_input")))


def failure_note(name: str, error: BaseException) -> str:
    """The single stderr line of a hook that could not act; no message text, it may hold data."""
    code = error.code if isinstance(error, WevError) else type(error).__name__
    return i18n.t("hooks.note.failed", name=name, error=code)
