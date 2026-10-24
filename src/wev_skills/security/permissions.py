"""Permission policy: decides whether a command or a tool may be used right now.

The policy is deny-oriented. It builds on the heuristics in ``security.commands``,
so it shares their limits: it reduces accidents, it is not a sandbox.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from typing import Protocol

from wev_skills import i18n
from wev_skills.config import PermissionsConfig
from wev_skills.core.contracts import Mode, PermissionDecision, PermissionOutcome, RiskLevel
from wev_skills.core.errors import ApprovalRequired, NotFound, PermissionDenied
from wev_skills.security import commands, patterns, recursive, uproot
from wev_skills.security.paths import glob_may_match_protected, is_protected
from wev_skills.security.readonly import (
    READ_ONLY_COMMANDS,
    READ_ONLY_FORBIDDEN_OPTIONS,
    TRUSTED_BIN_DIRS,
    is_read_only,
)
from wev_skills.security.redact import redact, redact_argv
from wev_skills.tools.registry import ToolRegistry

TOOL_ACTION_PREFIX = "tool"
_RISK_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}

__all__ = [
    "READ_ONLY_COMMANDS",
    "READ_ONLY_FORBIDDEN_OPTIONS",
    "TRUSTED_BIN_DIRS",
    "ApprovalGate",
    "PermissionPolicy",
    "is_read_only",
]


class ApprovalGate(Protocol):
    """What the policy needs from an approval store (see ``governance.approvals``)."""

    def is_granted(self, action: Sequence[str], cwd: str = "") -> bool: ...

    def consume(self, action: Sequence[str], cwd: str = "") -> bool: ...

    def is_denied(self, action: Sequence[str], cwd: str = "") -> bool: ...


def _decision(outcome: PermissionOutcome, key: str, **params: object) -> PermissionDecision:
    return PermissionDecision(outcome, i18n.t(f"security.decision.{key}", **params))


def _denied(code: str, **params: object) -> PermissionDenied:
    details = {key: str(value) for key, value in params.items()}
    return PermissionDenied(code, i18n.t(f"security.error.{code}", **params), details)


def _inside(root: str, path: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _has_separator(program: str) -> bool:
    return os.sep in program or "/" in program


def _path_candidates(token: str) -> tuple[str, ...]:
    """Spellings of one argument that may name a file: ``x``, ``--opt=x``, ``@x``."""
    values = {token, token.split("=", 1)[-1]}
    return tuple(sorted({value.lstrip("@") for value in values} - {""}))


class PermissionPolicy:
    """Implements the ``CommandGate`` port.

    ``check_command`` is the gate called right before a command runs, so by default it
    uses up a single-use approval when that approval is what allows the command. Pass
    ``consume=False`` to ask "would this be allowed?" without spending the grant.
    """

    def __init__(
        self,
        permissions_config: PermissionsConfig,
        tool_registry: ToolRegistry | None = None,
        approvals: ApprovalGate | None = None,
    ) -> None:
        self._config = permissions_config
        self._tools = tool_registry if tool_registry is not None else ToolRegistry.default()
        self._approvals = approvals
        for pattern in (*permissions_config.allowed_commands, *permissions_config.denied_commands):
            patterns.pattern_tokens(pattern)

    @property
    def exec_path(self) -> tuple[str, ...]:
        """The absolute directories a bare program name is looked up in."""
        return tuple(entry for entry in self._config.exec_path if os.path.isabs(entry))

    def resolve_program(self, argv: Sequence[str], cwd: str | None) -> str:
        """The program ``argv`` runs: looked up on the safe path, never on ``$PATH``.

        A program that lives inside the run root (``cwd``) is refused, because the agent
        can write there. Only an explicit relative path (``./tool``) names one, and that is
        classified as an unanalyzable script, so it needs approval.
        """
        program, root = argv[0], os.path.realpath(cwd or os.getcwd())
        if _has_separator(program) and not os.path.isabs(program):
            return program
        found = program if os.path.isabs(program) else None
        if found is None:
            found = shutil.which(program, path=os.pathsep.join(self.exec_path) or os.devnull)
        if found is None:
            raise _denied("program_not_on_safe_path", program=redact(program))
        if _inside(root, os.path.realpath(found)):
            raise _denied("program_in_run_root", program=redact(program))
        return found

    def _has_grant(self, action: Sequence[str], cwd: str, consume: bool) -> bool:
        if self._approvals is None:
            return False
        if consume:
            return self._approvals.consume(action, cwd)
        return self._approvals.is_granted(action, cwd)

    def _protected_argument(
        self, expanded: Sequence[Sequence[str]], cwd: str | None, shell_globs: frozenset[str]
    ) -> str | None:
        root = cwd or os.getcwd()
        tokens = dict.fromkeys(token for argv in expanded for token in argv)
        protected = self._config.protected_paths
        for token in tokens:
            for candidate in _path_candidates(token):
                if is_protected(candidate, root, protected):
                    return candidate
                hidden = not (candidate == token and token in shell_globs)
                if glob_may_match_protected(candidate, root, protected, hidden=hidden):
                    return candidate
        return None

    def _swept(
        self, expanded: Sequence[Sequence[str]], cwd: str | None
    ) -> PermissionDecision | None:
        """A recursive reader given a directory that holds a protected path: ask, because
        it reads the protected file without naming it (see ``security.recursive``)."""
        root = cwd or os.getcwd()
        for argv in expanded:
            hit = recursive.protected_inside(argv, root, self._config.protected_paths)
            if hit is not None:
                shown = os.path.relpath(hit[1], os.path.realpath(root))
                return _decision(
                    PermissionOutcome.NEEDS_APPROVAL,
                    "protected_inside",
                    program=commands.program_name(argv),
                    directory=redact(os.path.relpath(hit[0], root)),
                    path=redact(shown),
                )
        return None

    def _uprooted(
        self, expanded: Sequence[Sequence[str]], cwd: str | None
    ) -> PermissionDecision | None:
        """A move or removal of a directory that holds a protected path: ask, because it
        takes the protected path away without naming it (see ``security.uproot``)."""
        root = cwd or os.getcwd()
        for argv in expanded:
            hit = uproot.uprooted(argv, root, self._config.protected_paths)
            if hit is not None:
                return _decision(
                    PermissionOutcome.NEEDS_APPROVAL,
                    "protected_ancestor",
                    program=commands.program_name(argv),
                    directory=redact(hit[0]),
                    path=redact(hit[1]),
                )
        return None

    def _local_script(self, argv: Sequence[str]) -> commands.CommandRisk:
        """A program named by a relative path is a file the agent can write: never analyzed."""
        program = argv[0]
        relative = _has_separator(program) and not os.path.isabs(program)
        return commands.risk("u", "local_script") if relative else commands.CommandRisk()

    def _settle(
        self, checked: Sequence[str], cwd: str | None, pending: PermissionDecision, consume: bool
    ) -> PermissionDecision:
        """What a command that needs approval gets: a refusal, a spent grant, or the request."""
        place = os.path.realpath(cwd) if cwd else ""
        if tuple(redact_argv(checked)) != tuple(checked):
            return _decision(PermissionOutcome.DENY, "secret_in_command")
        if self._approvals is not None and self._approvals.is_denied(checked, place):
            return _decision(PermissionOutcome.DENY, "approval_denied")
        if self._has_grant(checked, place, consume):
            return _decision(PermissionOutcome.ALLOW, "approved")
        return pending

    def _approval_reason(
        self, argv: Sequence[str], found: commands.CommandRisk, read_only: bool, risk: RiskLevel
    ) -> PermissionDecision | None:
        needs = PermissionOutcome.NEEDS_APPROVAL
        if found.needs_approval:
            return _decision(needs, "risky", reasons="; ".join(found.reasons))
        allowed = self._config.allowed_commands
        if allowed and patterns.first_match([argv], allowed) is None:
            return _decision(needs, "not_allowlisted")
        if risk is RiskLevel.HIGH and not read_only:
            return _decision(needs, "high_risk")
        return None

    def check_command(
        self,
        argv: Sequence[str],
        cwd: str | None,
        mode: Mode,
        risk: RiskLevel,
        *,
        consume: bool = True,
        shell_globs: frozenset[str] = frozenset(),
    ) -> PermissionDecision:
        """``shell_globs``: words of ``argv`` the shell expanded itself (an unquoted glob
        that matched files), so their ``*`` could not name a dotted protected path."""
        deny = PermissionOutcome.DENY
        try:
            checked = commands.parse(argv, allow_shell=self._config.allow_shell)
        except PermissionDenied as exc:
            return PermissionDecision(deny, exc.message)
        if commands.is_assignment(checked[0]):
            return _decision(deny, "env_prefix")
        expansion = commands.expand(checked)
        if isinstance(argv, str) and commands.has_shell_syntax(argv):
            # Only reachable with allow_shell: the string is a script, not one invocation.
            # Look at every position as a possible command and never treat it as analyzed.
            inner = commands.expand(("env", *checked)).commands
            expansion = commands.Expansion(inner, (*expansion.opaque, "inline_shell"))
        found = commands.classify_expansion(expansion).merge(self._local_script(checked))
        pattern = patterns.first_match(expansion.commands, self._config.denied_commands)
        if pattern is not None:
            return _decision(deny, "denied_by_list", pattern=pattern)
        read_only = is_read_only(checked) and not found.is_risky
        if mode is Mode.PLAN and not read_only:
            return _decision(deny, "plan_mode")
        protected = self._protected_argument(expansion.commands, cwd, shell_globs)
        if protected is not None:
            return _decision(deny, "protected_path", path=redact(protected))
        pending = (
            self._uprooted(expansion.commands, cwd)
            or self._swept(expansion.commands, cwd)
            or self._approval_reason(checked, found, read_only, risk)
        )
        if pending is None:
            return _decision(PermissionOutcome.ALLOW, "allowed")
        return self._settle(checked, cwd, pending, consume)

    def check_path(self, path: str, cwd: str | None) -> PermissionDecision:
        """Whether a file named outside an argv (a redirection target) may be touched."""
        if is_protected(path, cwd or os.getcwd(), self._config.protected_paths):
            return _decision(PermissionOutcome.DENY, "protected_path", path=redact(path))
        return _decision(PermissionOutcome.ALLOW, "allowed")

    def enforce_command(
        self,
        argv: Sequence[str],
        cwd: str | None,
        mode: Mode,
        risk: RiskLevel,
        *,
        consume: bool = True,
    ) -> PermissionDecision:
        """Like ``check_command`` but raises ``PermissionDenied`` or ``ApprovalRequired``."""
        decision = self.check_command(argv, cwd, mode, risk, consume=consume)
        shown = [redact(argv)] if isinstance(argv, str) else list(redact_argv(argv))
        details = {"argv": shown, "mode": mode.value}
        if decision.outcome is PermissionOutcome.DENY:
            raise PermissionDenied("command_denied", decision.reason, details)
        if decision.outcome is PermissionOutcome.NEEDS_APPROVAL:
            raise ApprovalRequired("approval_required", decision.reason, details)
        return decision

    def check_tool(
        self,
        tool: str,
        mode: Mode,
        risk: RiskLevel,
        agent_tools_allow: Sequence[str] = (),
        agent_tools_deny: Sequence[str] = (),
        *,
        consume: bool = True,
    ) -> PermissionDecision:
        """Gate a tool for an agent. A tool in both agent lists is denied."""
        deny = PermissionOutcome.DENY
        try:
            spec = self._tools.get(tool)
        except NotFound:
            return _decision(deny, "tool_unknown", tool=tool)
        if tool in agent_tools_deny:
            return _decision(deny, "tool_denied_by_agent", tool=tool)
        if agent_tools_allow and tool not in agent_tools_allow:
            return _decision(deny, "tool_not_allowed_for_agent", tool=tool)
        if mode is Mode.PLAN and spec.mutating:
            return _decision(deny, "tool_plan_mode", tool=tool)
        threshold = spec.min_risk_for_approval
        gated = threshold is not None and _RISK_ORDER[risk] >= _RISK_ORDER[threshold]
        if not gated and not (spec.mutating and risk is RiskLevel.HIGH):
            return _decision(PermissionOutcome.ALLOW, "tool_allowed", tool=tool)
        if self._has_grant((TOOL_ACTION_PREFIX, tool), "", consume):
            return _decision(PermissionOutcome.ALLOW, "approved")
        return _decision(PermissionOutcome.NEEDS_APPROVAL, "tool_needs_approval", tool=tool)
