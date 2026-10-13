"""PLAN and DECIDE: store a plan and give every waiting task an agent and a model."""

from __future__ import annotations

from dataclasses import replace

from wev_skills import i18n
from wev_skills.core import plan_amend, planning, progress
from wev_skills.core.contracts import Mode, Plan, RiskLevel
from wev_skills.core.engine import Engine, set_assignment
from wev_skills.core.errors import ValidationError
from wev_skills.state.model import (
    DecisionRecord,
    Phase,
    RunState,
    with_decision,
    with_phase,
    with_plan,
)

MODEL_SOURCE = "model-router"


def _with_plan(state: RunState, plan: Plan) -> RunState:
    """Store ``plan``; records of waiting tasks it no longer lists are dropped."""
    kept = {task.id for task in plan.tasks}
    pruned = replace(state, tasks={k: v for k, v in state.tasks.items() if k in kept})
    return with_plan(pruned, plan)


def _decisions(engine: Engine, state: RunState, item: planning.Assignment) -> list[DecisionRecord]:
    task = progress.plan_task(state, item.task_id)
    risk = progress.task_risk(state, task)
    agent = i18n.t("orch.decision.agent", task=task.id, agent=item.agent_id)
    model = i18n.t(
        "orch.decision.model", task=task.id, model=item.model.model, tier=item.model.tier
    )
    records = [
        engine.decision(Phase.DECIDE, agent, (), item.agent_source),
        engine.decision(Phase.DECIDE, model, item.model.reasons, MODEL_SOURCE),
    ]
    run_risk = state.classification.risk if state.classification else RiskLevel.LOW
    if risk is not run_risk:
        text = i18n.t("orch.decision.risk", task=task.id, risk=risk.value)
        records.append(engine.decision(Phase.DECIDE, text))
    return records


def adopt_plan(engine: Engine, plan: Plan, event: str, amend_reason: str | None = None) -> RunState:
    """Validate against the run, assign agents and models, and record each choice.

    A change to the guarded fields of a task that has ever been started needs
    ``amend_reason`` and is recorded as an amendment (see ``plan_amend``)."""
    state = engine.load()
    if state.strategy is None:
        raise ValidationError("run_not_started", i18n.t("orch.error.not_started"))
    dropped = planning.dropped_with_history(state, plan)
    if dropped:
        message = i18n.t("orch.error.plan_drops", tasks=", ".join(dropped))
        raise ValidationError("plan_drops_tasks", message, {"tasks": dropped})
    amended = plan_amend.changes(state, plan)
    plan_amend.refuse_unamended(state, amended, amend_reason)
    draft = _with_plan(state, plan)
    services = engine.services
    assignments = [
        planning.assign(
            draft,
            task,
            services.agents,
            services.provider,
            services.router,
            services.config.agents.default_agent,
        )
        for task in plan.tasks
        if draft.tasks[task.id].status in progress.WAITING
    ]

    def change(current: RunState) -> RunState:
        moved = _with_plan(current, plan)
        if amended:
            moved = plan_amend.apply(engine, moved, amended, amend_reason or "")
        for item in assignments:
            moved = set_assignment(moved, item.task_id, item.agent_id, item.model.model)
            for record in _decisions(engine, moved, item):
                moved = with_decision(moved, record)
        return with_phase(moved, Phase.PLAN if moved.mode is Mode.PLAN else Phase.EXECUTE)

    data = {"tasks": [task.id for task in plan.tasks]}
    after = engine.commit(change, event, data, base=state)
    if amended:
        reason = engine.clean(amend_reason or "").strip()
        engine.services.audit.append(
            plan_amend.EVENT, {"run_id": state.run_id, **plan_amend.audit_data(amended, reason)}
        )
    return after
