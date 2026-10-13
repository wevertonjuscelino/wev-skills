"""Tool selection through ``jev ask``: one call per task, typed questions only.

One ``noul`` question per candidate tool that is not in the floor, plus one ``choice``
question for the tool profile when ``harness.tool_profile`` is ``auto``. The state sent is
the task's title, objective and acceptance criteria and nothing else: no file contents, no
file names, no repository data. The caller's ``ask`` redacts it before it leaves.

The reading is conservative on purpose. Dropping a tool the task needed fails the task,
while keeping one it did not need only costs context, so a tool is dropped only when JEV is
confident it is not needed (``noul`` at or below ``DROP_THRESHOLD``). The floor is never
asked about. Any failure falls back to the local selection with the reason, exactly as
classification does. Nothing is cached between calls.

Evidence: tested against a fake ``jev`` only. No live call was made for tool selection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from wev_skills import i18n
from wev_skills.agents.tool_profile import LEAN, STRUCTURED
from wev_skills.config import AUTO
from wev_skills.core.contracts import PlanTask, ToolSelection
from wev_skills.decisions import tool_selection as rules
from wev_skills.decisions.jev_wire import (
    JevUnavailable,
    confidence,
    fields,
    is_fraction,
    load_answers,
    trusted,
    unparseable,
)
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.decisions.local_tools import task_text
from wev_skills.decisions.tool_selection import Proposal, ToolAgent
from wev_skills.tools.registry import ToolSpec

PROVIDER_ID = "jev"
DROP_THRESHOLD = 0.2
"""A tool is dropped only when the ``noul`` answer for "needed" is at or below this."""
MAX_TOOL_QUESTIONS = 12
"""Most tool questions sent in one call; a longer candidate list uses the local policy."""
TOOL_PREFIX = "tool_"
Q_PROFILE = "profile"
PROFILE_CRITERIA = {
    STRUCTURED: "separate, individually permission-checked tools for reading, searching, "
    "editing and running commands",
    LEAN: "only the shell plus one tool to read a file and one to edit it",
}

Ask = Callable[[Mapping[str, Any], str], str]
"""``(questions, state text) -> stdout`` of one ``jev ask`` call; redacts the state."""


def build_state(task: PlanTask) -> str:
    """The task text, and only that: title, objective and acceptance criteria."""
    return f"Task: {task_text(task)}"


TRAILING_PUNCTUATION = " \t\n.;:,!?"
"""Characters cut from a description so the question mark never follows a period."""


def build_questions(
    askable: Sequence[str], available: Sequence[ToolSpec], ask_profile: bool
) -> dict[str, Any]:
    described = {spec.name: spec.description for spec in available}
    questions: dict[str, Any] = {}
    for name in askable:
        detail = described.get(name, "").rstrip(TRAILING_PUNCTUATION)
        about = f": {detail}" if detail else ""
        text = f"Does this task need the {name} tool{about}?"
        questions[f"{TOOL_PREFIX}{name}"] = {"type": "noul", "instructions": text}
    if ask_profile:
        questions[Q_PROFILE] = {
            "type": "choice",
            "instructions": "Pick the tool interface that suits this task.",
            "criteria": dict(PROFILE_CRITERIA),
        }
    return questions


def _tool_reasons(askable: Sequence[str], data: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """``(tools kept, one reason per asked tool)``; a tool is kept unless clearly unneeded."""
    kept, reasons = [], []
    for name in askable:
        question = f"{TOOL_PREFIX}{name}"
        value, _ = fields(data[question], question, "noul", "noul")
        if not is_fraction(value):
            raise unparseable(question)
        keep = value > DROP_THRESHOLD
        key = "decisions.tools.jev.kept" if keep else "decisions.tools.jev.dropped"
        reasons.append(i18n.t(key, tool=name, value=value, threshold=DROP_THRESHOLD))
        if keep:
            kept.append(name)
    return kept, reasons


def _profile(data: Mapping[str, Any], local_profile: str) -> tuple[str, str]:
    """``(profile, reason)``: JEV's choice when confident, else the locally resolved one."""
    choice, found = fields(data[Q_PROFILE], Q_PROFILE, "choice", "choice")
    if not isinstance(choice, str) or choice not in PROFILE_CRITERIA:
        raise unparseable(Q_PROFILE)
    if trusted(confidence(found, Q_PROFILE)):
        return choice, i18n.t("decisions.tools.jev.profile", value=choice)
    return local_profile, i18n.t("decisions.tools.jev.profile_distrusted", value=local_profile)


def _interpret(
    stdout: str, questions: Mapping[str, Any], askable: Sequence[str], floor: Sequence[str],
    local_profile: str,
) -> Proposal:  # fmt: skip
    data = load_answers(stdout, tuple(questions))
    kept, reasons = _tool_reasons(askable, data)
    profile = local_profile
    if Q_PROFILE in questions:
        profile, why = _profile(data, local_profile)
        reasons.append(why)
    if floor:
        reasons.append(i18n.t("decisions.tools.jev.floor", tools=", ".join(floor)))
    return Proposal((*floor, *kept), profile, tuple(reasons), PROVIDER_ID)


def select(
    ask: Ask,
    local: LocalPolicyProvider,
    task: PlanTask,
    agent: ToolAgent,
    available: Sequence[ToolSpec],
    tier: str,
) -> ToolSelection:
    """The selection for ``task`` from one ``jev ask`` call, or the local one with a reason."""

    def fallback() -> Proposal:
        return local.propose_tools(task, agent, available, tier)

    def local_selection(reason: str) -> ToolSelection:
        base = fallback()
        noted = replace(base, reasons=(reason, *base.reasons))
        return rules.enforce(task, agent, available, noted)

    candidates = rules.candidate_tools(agent)
    floor = rules.floor_tools(task, agent, candidates)
    askable = [name for name in rules.bases(candidates) if name not in floor]
    ask_profile = local.harness.tool_profile == AUTO
    if len(askable) > MAX_TOOL_QUESTIONS:
        return local_selection(
            i18n.t("decisions.tools.jev.too_many", count=len(askable), limit=MAX_TOOL_QUESTIONS)
        )
    questions = build_questions(askable, available, ask_profile)
    if not questions:
        return local_selection(i18n.t("decisions.tools.jev.nothing"))
    try:
        stdout = ask(questions, build_state(task))
        proposal = _interpret(stdout, questions, askable, floor, fallback().profile)
    except JevUnavailable as exc:
        return local_selection(i18n.t("decisions.jev.unavailable", why=exc.message or exc.code))
    return rules.enforce(task, agent, available, proposal, fallback)
