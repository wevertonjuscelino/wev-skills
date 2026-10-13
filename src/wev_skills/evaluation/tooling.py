"""Tool selection inside the scripted evaluation: what a subtask is handed, and misses.

The scripted agent calls no tool. A step may name the tool it stands for (``needs_tool``);
with selection on, a step whose tool was dropped records a miss and the tool is restored
from the reference agent's own list, which is the recovery path of ``wev task tools``
replayed mechanically. The restore costs no simulated time or tokens. The token figures
are sums of the registry's rough constants: estimates, not measurements.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from wev_skills.agents.spec import Permissions, Tools
from wev_skills.config import HarnessSettings
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import PlanTask, ToolSelection
from wev_skills.decisions import tool_selection as rules
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.evaluation.configs import (
    REFERENCE_PERMISSIONS,
    REFERENCE_TOOLS,
    SELECTION_OFF,
    HarnessConfig,
)
from wev_skills.evaluation.tasks import EvalTask, Subtask
from wev_skills.tools.registry import ToolRegistry

REASON_TOOL_UNAVAILABLE = "tool_unavailable"
"""A step needs a tool outside the reference agent's list: nothing can restore it."""


@dataclass(frozen=True)
class ReferenceAgent:
    """The agent every scripted subtask is assigned to: it edits files and has a shell."""

    id: str = "reference"
    tools: Tools | None = REFERENCE_TOOLS
    permissions: Permissions | None = REFERENCE_PERMISSIONS


@dataclass(frozen=True)
class SubtaskTools(Serializable):
    """What one subtask was handed, and every tool it had to get back (a miss)."""

    subtask_id: str
    offered: tuple[str, ...]
    selected: tuple[str, ...]
    dropped: tuple[str, ...]
    restored: tuple[str, ...] = ()
    misses: int = 0
    estimated_tokens_offered: int = 0
    estimated_tokens_selected: int = 0


def _plan_task(task: EvalTask, subtask: Subtask) -> PlanTask:
    checks = tuple(s.signature for s in task.steps_for(subtask.id) if s.kind == "verify")
    return PlanTask(
        id=subtask.id,
        title=subtask.id,
        objective=subtask.objective or task.signals.objective,
        files=subtask.files,
        checks=checks,
        read_only=subtask.read_only,
    )


def _summary(subtask_id: str, chosen: ToolSelection) -> SubtaskTools:
    return SubtaskTools(
        subtask_id=subtask_id,
        offered=chosen.offered,
        selected=chosen.selected,
        dropped=chosen.dropped,
        estimated_tokens_offered=chosen.estimated_tokens_offered,
        estimated_tokens_selected=chosen.estimated_tokens_selected,
    )


def select(task: EvalTask, subtask: Subtask, config: HarnessConfig, tier: str) -> SubtaskTools:
    """The subtask's tools: the local selection, or the whole profile surface when off."""
    agent, available = ReferenceAgent(), ToolRegistry.default().list()
    provider = LocalPolicyProvider(
        config.limits(), HarnessSettings(tool_profile=config.tool_profile)
    )
    plan_task = _plan_task(task, subtask)
    proposal = provider.propose_tools(plan_task, agent, available, tier)
    if config.tool_selection == SELECTION_OFF:
        everything = rules.candidate_tools(agent)
        proposal = replace(proposal, selected=everything, reasons=(), source=SELECTION_OFF)
    return _summary(subtask.id, rules.enforce(plan_task, agent, available, proposal))


def use(tools: SubtaskTools, needed: str, checking: bool) -> tuple[SubtaskTools, bool]:
    """``(tools after the step, whether the step can run)`` for a step that needs ``needed``.

    A dropped tool inside the offered list is restored and counted as a miss. A tool
    outside it cannot be restored, so the step cannot run.
    """
    name = rules.base_name(needed)
    if not checking or not needed or name in rules.bases(tools.selected):
        return tools, True
    if name not in rules.bases(tools.offered):
        return tools, False
    wanted = {*rules.bases(tools.selected), name}
    selected = tuple(tool for tool in tools.offered if rules.base_name(tool) in wanted)
    restored = replace(
        tools,
        selected=selected,
        dropped=tuple(tool for tool in tools.offered if tool not in selected),
        restored=(*tools.restored, name),
        misses=tools.misses + 1,
        estimated_tokens_selected=rules.estimate_tokens(selected, ToolRegistry.default().list()),
    )
    return restored, True
