"""Per-task tool selection in a run: compute it, store it with the task, restore a tool.

Selection runs only when ``harness.tool_selection`` is ``local`` or ``provider``. It is
computed once per task, when the task's contract is first built, and kept with the task so
that every later contract of the task grants the same tools. A tool that was dropped and
turns out to be needed can be restored while the task runs, but only from the agent's own
candidate set, and each restore is recorded as a selection miss.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.agents.tool_profile import tier_of
from wev_skills.core import progress, task_contract, wiring
from wev_skills.core.contracts import TaskStatus, ToolSelection
from wev_skills.core.engine import Engine
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.decisions import DecisionProvider
from wev_skills.decisions import tool_selection as rules
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.state.model import Phase, RunState, TaskRecord, with_decision
from wev_skills.state.records import ToolMiss

SOURCE = "tool-selection"
OFF, LOCAL, PROVIDER = "off", "local", "provider"
NONE_MARK = "-"


def _provider(engine: Engine) -> DecisionProvider:
    """``provider`` mode uses the configured decision provider; ``local`` never leaves it."""
    config = engine.services.config
    if config.harness.tool_selection == PROVIDER:
        return engine.services.provider
    return LocalPolicyProvider(config.limits, config.harness)


def _select(engine: Engine, state: RunState, task_id: str) -> ToolSelection:
    task = progress.plan_task(state, task_id)
    record = state.tasks[task_id]
    spec = engine.services.agents.resolved(record.agent_id)
    asked = replace(task, checks=task_contract.contract_checks(state, task, spec))
    tier = tier_of(record.model, engine.services.config.models)
    available = wiring.build_tool_registry().list()
    chosen = _provider(engine).select_tools(asked, spec, available, tier)
    return replace(chosen, reasons=tuple(engine.clean(reason) for reason in chosen.reasons))


def compute(engine: Engine, state: RunState, task_ids: Sequence[str]) -> dict[str, ToolSelection]:
    """A selection for each of ``task_ids`` that has none yet; empty when selection is off."""
    if engine.services.config.harness.tool_selection == OFF:
        return {}
    missing = [t for t in task_ids if state.tasks[t].tool_selection is None]
    return {task_id: _select(engine, state, task_id) for task_id in missing}


def _names(tools: Sequence[str]) -> str:
    return ", ".join(tools) or NONE_MARK


def _put(state: RunState, task_id: str, record: TaskRecord) -> RunState:
    return replace(state, tasks={**state.tasks, task_id: record})


def store(engine: Engine, state: RunState, chosen: Mapping[str, ToolSelection]) -> RunState:
    """``state`` with each new selection kept on its task and recorded as a decision."""
    moved = state
    for task_id, selection in chosen.items():
        if moved.tasks[task_id].tool_selection is not None:
            continue
        moved = _put(moved, task_id, replace(moved.tasks[task_id], tool_selection=selection))
        text = i18n.t(
            "decisions.tools.decision",
            task=task_id,
            selected=_names(selection.selected),
            dropped=_names(selection.dropped),
            source=selection.source,
        )
        record = engine.decision(Phase.EXECUTE, text, selection.reasons, SOURCE)
        moved = with_decision(moved, record)
    return moved


def _refuse(code: str, key: str, task_id: str, **params: object) -> ValidationError:
    message = i18n.t(f"decisions.tools.error.{key}", task=task_id, **params)
    return ValidationError(code, message, {"task_id": task_id})


def _restorable(engine: Engine, state: RunState, task_id: str, tool: str) -> ToolSelection:
    """The task's selection, when ``tool`` may be restored into it; raises otherwise."""
    record = progress.task_record(state, task_id)
    current = record.tool_selection
    if current is None:
        raise _refuse("no_tool_selection", "no_selection", task_id)
    if record.status is not TaskStatus.RUNNING:
        raise _refuse("task_not_running", "not_running", task_id, status=record.status.value)
    spec = engine.services.agents.resolved(record.agent_id)
    wanted = rules.base_name(tool)
    allowed = set(rules.bases(rules.candidate_tools(spec))) & set(rules.bases(current.offered))
    if wanted not in allowed:
        message = i18n.t("decisions.tools.error.not_offered", tool=tool, agent=spec.id)
        details = {"task_id": task_id, "tool": tool, "agent_id": spec.id}
        raise PermissionDenied("tool_not_offered", message, details)
    if wanted in rules.bases(current.selected):
        raise _refuse("tool_already_selected", "already", task_id, tool=tool)
    return current


def _with_tool(current: ToolSelection, tool: str, note: str) -> ToolSelection:
    """``current`` with every offered entry of ``tool`` selected again."""
    wanted = {*rules.bases(current.selected), rules.base_name(tool)}
    selected = tuple(t for t in current.offered if rules.base_name(t) in wanted)
    available = wiring.build_tool_registry().list()
    return replace(
        current,
        selected=selected,
        dropped=tuple(t for t in current.offered if t not in selected),
        reasons=(*current.reasons, note),
        estimated_tokens_selected=rules.estimate_tokens(selected, available),
    )


def restore(engine: Engine, task_id: str, tool: str, reason: str) -> dict[str, Any]:
    """Give a running task back a tool that selection dropped, and count it as a miss.

    Only a tool inside the agent's candidate set (its allow list minus its deny list) can
    come back: this narrows nothing further and widens nothing beyond the agent's spec.
    """
    why = engine.clean(reason).strip()
    if not why:
        raise ValidationError("reason_required", i18n.t("decisions.tools.error.reason"))
    state = engine.load()
    restored = _restorable(engine, state, task_id, tool)
    name = rules.base_name(tool)
    note = i18n.t("decisions.tools.restored", tool=name, task=task_id, reason=why)
    stamp = engine.stamp()

    def change(current: RunState) -> RunState:
        record = current.tasks[task_id]
        miss = ToolMiss(stamp, name, why, record.starts)
        updated = replace(
            record,
            tool_selection=_with_tool(restored, name, engine.clean(note)),
            tool_misses=(*record.tool_misses, miss),
        )
        decision = engine.decision(current.phase, note, (why,), SOURCE)
        return with_decision(_put(current, task_id, updated), decision)

    data = {"task_id": task_id, "tool": name, "reason": why}
    after = engine.commit(change, "task.tool_restored", data, base=state)
    record = after.tasks[task_id]
    return {
        "run_id": after.run_id,
        "task_id": task_id,
        "restored": name,
        "tool_selection": record.tool_selection.to_dict() if record.tool_selection else None,
        "misses": len(record.tool_misses),
        "contract": engine.contract(after, task_id).to_dict(),
        **engine.step_fields(after),
    }
