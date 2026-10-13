"""What the active run allows a remote command: its mode, its risk and its task's agent.

The caller of ``wev remote`` is the agent being governed, so nothing it types may widen
what the run recorded. Mode and risk come from the run and the command line may only
repeat them or be more restrictive; the task must belong to the run's plan and the agent
assigned to it must have ``permissions.may_use_remote``.
"""

from __future__ import annotations

from wev_skills import i18n
from wev_skills.core.active import ActiveRun
from wev_skills.core.agent_rules import task_permissions
from wev_skills.core.contracts import Mode, RiskLevel, risk_rank
from wev_skills.core.errors import PermissionDenied, WevError
from wev_skills.core.wiring import AgentCatalog
from wev_skills.state.store import StateStore, run_dir

DEFAULT_RISK = RiskLevel.MEDIUM


def _denied(code: str, active: ActiveRun, **details: str) -> PermissionDenied:
    """A refusal whose message and details both name the run and the values compared."""
    values = {"run": active.run_id, **details}
    return PermissionDenied(f"remote_{code}", i18n.t(f"remote.error.{code}", **values), values)


def refuse_unreadable(active: ActiveRun) -> None:
    """A run whose state cannot be read counts as plan mode at high risk: refuse."""
    if active.state_error is not None:
        raise _denied("run_state_unreadable", active, state_error=active.state_error)


def resolve_levels(
    active: ActiveRun | None, mode: Mode | None, risk: RiskLevel | None
) -> tuple[Mode | None, RiskLevel]:
    """The mode and risk a remote command is judged with.

    Without an active run they are the command line's (``None`` when no mode was given;
    risk defaults to medium). With one they are the run's: asking for plan mode or for a
    higher risk is accepted, anything more permissive raises ``PermissionDenied``.
    """
    if active is None:
        return mode, risk if risk is not None else DEFAULT_RISK
    refuse_unreadable(active)
    if active.mode is Mode.PLAN and mode not in (None, Mode.PLAN):
        raise _denied("mode_widened", active, run_mode=active.mode.value, mode=mode.value)
    if risk is not None and risk_rank(risk) < risk_rank(active.risk):
        raise _denied("risk_widened", active, run_risk=active.risk.value, risk=risk.value)
    return (Mode.PLAN if mode is Mode.PLAN else active.mode), (risk or active.risk)


def require_remote_task(active: ActiveRun, agents: AgentCatalog, task_id: str) -> None:
    """Refuse unless ``task_id`` is in the run's plan and its agent may use remote hosts."""
    refuse_unreadable(active)
    try:
        state = StateStore(run_dir(active.state_dir, active.run_id)).load()
        record = state.tasks.get(task_id)
        if record is not None and not record.agent_id:
            raise _denied("task_unassigned", active, task=task_id)
        allowed = task_permissions(state, task_id, agents)
    except PermissionDenied:
        raise
    except WevError as exc:
        raise _denied("task_not_in_run", active, task=task_id, reason=exc.message) from exc
    if not allowed.may_use_remote:
        raise _denied("agent_not_allowed", active, task=task_id, agent_id=allowed.agent_id)
