"""What an agent spec allows, as the engine enforces it.

Enforced here and by the callers of this module: ``permissions.modes``, ``max_risk`` and
``may_mutate``, ``max_attempts``, ``timeout_seconds``, ``budget.max_units`` and
``required_checks``. ``may_use_remote`` is exposed for the remote commands to enforce.
``stop_conditions``, ``success_criteria``, ``escalation`` and ``output_format`` are text the
agent receives in its contract; nothing in the engine checks them.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.core import progress
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import Mode, RiskLevel, risk_rank
from wev_skills.core.wiring import AgentCatalog
from wev_skills.guards.execution import GuardLimits
from wev_skills.state.model import RunState

ALL_MODES = (Mode.PLAN, Mode.EXECUTE)


@dataclass(frozen=True)
class AgentPermissions(Serializable):
    """The permissions of the agent assigned to a task, with unset values made explicit."""

    agent_id: str
    modes: tuple[Mode, ...]
    max_risk: RiskLevel
    may_mutate: bool
    may_use_remote: bool


def permissions_of(spec: AgentSpec) -> AgentPermissions:
    """A spec's permissions; what it does not declare is the most restrictive value,
    except ``modes``, where nothing declared means no mode restriction."""
    declared = spec.permissions
    modes = declared.modes if declared and declared.modes is not None else ALL_MODES
    return AgentPermissions(
        agent_id=spec.id,
        modes=tuple(modes),
        max_risk=(declared.max_risk if declared else None) or RiskLevel.LOW,
        may_mutate=bool(declared and declared.may_mutate),
        may_use_remote=bool(declared and declared.may_use_remote),
    )


def working_mode(mode: Mode) -> Mode:
    """The mode an agent needs permission for: only a plan-mode run is ``plan``."""
    return Mode.PLAN if mode is Mode.PLAN else Mode.EXECUTE


def refusal(spec: AgentSpec, mode: Mode, risk: RiskLevel) -> str | None:
    """Why ``spec`` may not take a task in ``mode`` at ``risk``; ``None`` when it may."""
    allowed = permissions_of(spec)
    needed = working_mode(mode)
    if needed not in allowed.modes:
        modes = ", ".join(item.value for item in allowed.modes) or "-"
        return i18n.t("orch.agent.mode", agent=spec.id, mode=needed.value, modes=modes)
    if risk_rank(risk) > risk_rank(allowed.max_risk):
        return i18n.t(
            "orch.agent.risk", agent=spec.id, risk=risk.value, max_risk=allowed.max_risk.value
        )
    return None


def task_permissions(state: RunState, task_id: str, agents: AgentCatalog) -> AgentPermissions:
    """The permissions of the agent assigned to ``task_id`` in this run."""
    record = progress.task_record(state, task_id)
    return permissions_of(agents.resolved(record.agent_id))


def attempt_limit(state: RunState, spec: AgentSpec | None) -> int:
    """How many times a task may start: the run's limit, lowered by the agent's when set."""
    limit = state.strategy.max_attempts if state.strategy else 1
    own = spec.max_attempts if spec is not None else None
    return max(1, min(limit, own) if own else limit)


def task_limits(limits: GuardLimits, spec: AgentSpec | None) -> GuardLimits:
    """Guard limits for one task: the agent lowers attempts and timeout (the lower wins),
    and its ``budget.max_units``, when set, is the task's budget (none otherwise)."""
    if spec is None:
        return replace(limits, budget_units=None)
    attempts, timeout = limits.max_attempts, limits.task_timeout_seconds
    if spec.max_attempts:
        attempts = min(attempts, spec.max_attempts) if attempts else spec.max_attempts
    if spec.timeout_seconds:
        timeout = min(timeout, spec.timeout_seconds) if timeout else spec.timeout_seconds
    budget = spec.budget.max_units if spec.budget else None
    return replace(limits, max_attempts=attempts, task_timeout_seconds=timeout, budget_units=budget)
