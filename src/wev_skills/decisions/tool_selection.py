"""Per-task tool selection: the candidates, the floor and the one gate every result passes.

A provider proposes which of an agent's tools one task needs (hypothesis H10). Whatever it
proposes goes through ``enforce``, which holds the rules no proposal can change:

* the candidates are the agent's allow list minus its deny list, and the result is a subset
  of them: a proposal can only narrow, and nothing denied is ever added;
* a floor is always kept: the read tools the agent already had, the edit tool when the task
  changes files and the agent may change them, and the shell when the task has checks;
* an empty or malformed proposal falls back to the local policy;
* a scoped pattern such as ``Bash(git:*)`` is treated by its base tool name;
* permissions are not part of a selection, so selecting tools cannot change them.

Dropping a tool the task needed fails the task, while keeping one it did not need only
costs context. Every rule here therefore errs towards keeping.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from wev_skills import i18n
from wev_skills.agents.spec import Permissions, Tools
from wev_skills.agents.tool_profile import LEAN, SHELL_TOOL, STRUCTURED, apply_profile
from wev_skills.core.contracts import PlanTask, ToolSelection
from wev_skills.tools.registry import DEFAULT_DEFINITION_TOKENS, ToolSpec

READ_TOOLS = ("Read", "Grep", "Glob")
EDIT_TOOLS = ("Edit", "Write")
"""In order of preference: the floor keeps the first one the agent has."""
PROFILES = (STRUCTURED, LEAN)
FLOOR_READ, FLOOR_EDIT, FLOOR_SHELL, FLOOR_ALL = "read", "edit", "shell", "all"


class ToolAgent(Protocol):
    """What selection reads of an agent: its id, its tool lists and its permissions."""

    @property
    def id(self) -> str: ...

    @property
    def tools(self) -> Tools | None: ...

    @property
    def permissions(self) -> Permissions | None: ...


@dataclass(frozen=True)
class Proposal:
    """What a provider suggests, before the rules are applied. Names may be base names."""

    selected: tuple[str, ...]
    profile: str
    reasons: tuple[str, ...] = ()
    source: str = ""


@dataclass(frozen=True)
class FloorTool:
    name: str
    kind: str


Fallback = Callable[[], Proposal]


def base_name(tool: str) -> str:
    """``Bash(git status:*)`` is a form of ``Bash``."""
    return tool.split("(", 1)[0].strip()


def bases(tools: Sequence[str]) -> tuple[str, ...]:
    """The distinct base names of ``tools``, in order."""
    return tuple(dict.fromkeys(base_name(tool) for tool in tools))


def candidate_tools(agent: ToolAgent) -> tuple[str, ...]:
    """The agent's allow list minus its deny list: the most any selection may grant.

    A deny entry removes the allow entry equal to it; an unscoped one (``Bash``) also
    removes every scoped form of that tool.
    """
    tools = agent.tools
    if tools is None:
        return ()
    denied = set(tools.deny)
    kept = (t for t in tools.allow if t not in denied and base_name(t) not in denied)
    return tuple(dict.fromkeys(kept))


def may_mutate(agent: ToolAgent) -> bool:
    return bool(agent.permissions is not None and agent.permissions.may_mutate)


def may_use_remote(agent: ToolAgent) -> bool:
    return bool(agent.permissions is not None and agent.permissions.may_use_remote)


def floor_entries(
    task: PlanTask, agent: ToolAgent, candidates: Sequence[str]
) -> tuple[FloorTool, ...]:
    """The tools no selection may drop, as base names with the rule that keeps each.

    An agent with none of the read tools has nothing safe to fall back on, so its whole
    list is the floor: the floor is never empty while there are candidates.
    """
    have = bases(candidates)
    floor = [FloorTool(name, FLOOR_READ) for name in READ_TOOLS if name in have]
    if not floor:
        return tuple(FloorTool(name, FLOOR_ALL) for name in have)
    edit = next((name for name in EDIT_TOOLS if name in have), None)
    if edit is not None and not task.read_only and may_mutate(agent):
        floor.append(FloorTool(edit, FLOOR_EDIT))
    if task.checks and SHELL_TOOL in have:
        floor.append(FloorTool(SHELL_TOOL, FLOOR_SHELL))
    return tuple(floor)


def floor_tools(task: PlanTask, agent: ToolAgent, candidates: Sequence[str]) -> tuple[str, ...]:
    return tuple(entry.name for entry in floor_entries(task, agent, candidates))


def floor_reasons(task: PlanTask, agent: ToolAgent, candidates: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        i18n.t(f"decisions.tools.floor.{entry.kind}", tool=entry.name)
        for entry in floor_entries(task, agent, candidates)
    )


def surface(agent: ToolAgent, candidates: Sequence[str], profile: str) -> tuple[str, ...]:
    """``candidates`` as ``profile`` offers them: ``lean`` shortens an editing agent's list."""
    narrowed = apply_profile(Tools(allow=tuple(candidates)), agent.permissions, profile)
    return narrowed.allow if narrowed is not None else ()


def estimate_tokens(tools: Sequence[str], available: Sequence[ToolSpec]) -> int:
    """Sum of the rough definition sizes of ``tools``, each base tool counted once.

    An estimate for comparing two tool sets, not a measurement (see ``ToolSpec``).
    """
    sizes = {spec.name: spec.approx_definition_tokens for spec in available}
    return sum(sizes.get(name, DEFAULT_DEFINITION_TOKENS) for name in bases(tools))


def _problem(proposal: Proposal, candidates: Sequence[str]) -> str | None:
    """Why ``proposal`` cannot be used at all; ``None`` when it can."""
    if not all(isinstance(name, str) for name in proposal.selected):
        return "names"
    if proposal.profile not in PROFILES:
        return "profile"
    known = set(bases(candidates))
    if candidates and not any(base_name(name) in known for name in proposal.selected):
        return "empty"
    return None


def _recovered(
    proposal: Proposal, candidates: Sequence[str], why: str, fallback: Fallback | None
) -> Proposal:
    """The proposal used instead of an unusable one: the local policy's, else everything."""
    cause = i18n.t(f"decisions.tools.invalid.{why}")
    if fallback is None:
        reason = i18n.t("decisions.tools.kept_all", why=cause)
        return Proposal(tuple(candidates), STRUCTURED, (reason,), proposal.source)
    local = fallback()
    reason = i18n.t("decisions.tools.fallback", source=proposal.source or "-", why=cause)
    return replace(local, reasons=(reason, *local.reasons))


def _notes(
    proposal: Proposal, candidates: Sequence[str], offered: Sequence[str], floor: Sequence[str]
) -> list[str]:
    """Reasons for what the rules, not the proposal, decided."""
    known, asked = set(bases(candidates)), set(bases(proposal.selected))
    notes: list[str] = []
    refused = [name for name in bases(proposal.selected) if name not in known]
    if refused:
        notes.append(i18n.t("decisions.tools.refused", tools=", ".join(refused)))
    lean = [tool for tool in candidates if tool not in offered]
    if lean:
        notes.append(i18n.t("decisions.tools.lean", tools=", ".join(lean)))
    notes.extend(
        i18n.t("decisions.tools.floor.enforced", tool=name) for name in floor if name not in asked
    )
    return notes


def enforce(
    task: PlanTask,
    agent: ToolAgent,
    available: Sequence[ToolSpec],
    proposal: Proposal,
    fallback: Fallback | None = None,
) -> ToolSelection:
    """The selection for ``task``: ``proposal`` held to the rules in the module docstring.

    ``fallback`` supplies the local policy's proposal when ``proposal`` is unusable; without
    it an unusable proposal keeps every candidate. Neither argument is changed.
    """
    candidates = candidate_tools(agent)
    why = _problem(proposal, candidates)
    if why is not None:
        return enforce(task, agent, available, _recovered(proposal, candidates, why, fallback))
    offered = surface(agent, candidates, proposal.profile)
    floor = floor_tools(task, agent, offered)
    wanted = set(bases(proposal.selected)) | set(floor)
    selected = tuple(tool for tool in offered if base_name(tool) in wanted)
    return ToolSelection(
        offered=candidates,
        selected=selected,
        dropped=tuple(tool for tool in candidates if tool not in selected),
        profile=proposal.profile,
        reasons=(*proposal.reasons, *_notes(proposal, candidates, offered, floor)),
        source=proposal.source,
        estimated_tokens_offered=estimate_tokens(candidates, available),
        estimated_tokens_selected=estimate_tokens(selected, available),
    )
