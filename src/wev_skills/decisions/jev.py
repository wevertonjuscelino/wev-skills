"""Optional JEV adapter: ``jev ask`` classifies tasks; everything else stays local.

``jev ask --questions <file> --state-file <file>`` prints a JSON object of answers,
exit 0 means success and 1 any error. The answer shape was observed once, on
2026-10-13 (tests/fixtures/jev_ask_response_2026-10-13.json); the client code does
not define it, so parsing is strict and any deviation falls back to the local policy:

* ``score``: ``{"type": "score", "score": <0-based int>, "confidence": 0..1, ...}``
* ``choice``: ``{"type": "choice", "choice": <option key>, "confidence": 0..1, ...}``
* ``noul``: ``{"type": "noul", "noul": <0..1 probability of yes>}`` (no confidence)
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from wev_skills import i18n
from wev_skills.core.contracts import (
    AttemptRecord,
    Classification,
    Complexity,
    EscalationDecision,
    Mode,
    PlanTask,
    RiskLevel,
    Strategy,
    TaskContract,
    TaskResult,
    TaskSignals,
    ToolSelection,
    Verdict,
)
from wev_skills.core.ports import AgentLike, Runner
from wev_skills.decisions import jev_tools
from wev_skills.decisions.jev_wire import (
    MIN_CONFIDENCE,
    JevUnavailable,
    check_exit,
    confidence,
    fields,
    is_fraction,
    load_answers,
    trusted,
    unparseable,
)
from wev_skills.decisions.local import COMPLEXITY_ORDER, LocalPolicyProvider, higher_risk
from wev_skills.decisions.local import PROVIDER_ID as LOCAL_ID
from wev_skills.decisions.tool_selection import ToolAgent
from wev_skills.tools.registry import ToolSpec

__all__ = ["MIN_CONFIDENCE", "JevProvider", "JevUnavailable", "parse_answers"]

PROVIDER_ID = "jev"
DEFAULT_TIMEOUT_SECONDS = 30.0
Q_COMPLEXITY, Q_RISK, Q_PARALLEL = "complexity", "risk", "parallelizable"
COMPLEXITY_LEVELS = (
    (Complexity.TRIVIAL, "trivial: one small, well understood change"),
    (Complexity.SIMPLE, "simple: a few files, little uncertainty"),
    (Complexity.MODERATE, "moderate: several files or some open questions"),
    (Complexity.COMPLEX, "complex: many files, many unknowns or cross-cutting"),
)
RISK_CRITERIA = {
    "low": "reversible, local, easy to verify",
    "medium": "touches remote systems, many files or is hard to undo",
    "high": "production, destructive or externally visible side effects",
}
YES_THRESHOLD = 0.5
NOUL_UNCERTAIN_LOW = 0.35
NOUL_UNCERTAIN_HIGH = 0.65


def build_questions() -> dict[str, Any]:
    return {
        Q_COMPLEXITY: {
            "type": "score",
            "instructions": "Rate the complexity of this software task.",
            "criteria": [text for _, text in COMPLEXITY_LEVELS],
        },
        Q_RISK: {
            "type": "choice",
            "instructions": "Pick the risk level of this software task.",
            "criteria": dict(RISK_CRITERIA),
        },
        Q_PARALLEL: {
            "type": "noul",
            "instructions": "Can this task be split into independent parallel subtasks?",
        },
    }


def build_state(signals: TaskSignals) -> str:
    return (
        f"Task: {signals.objective}\n"
        f"files_touched_estimate={signals.files_touched_estimate} "
        f"unknowns={signals.unknowns} independent_subtasks={signals.independent_subtasks}\n"
        f"touches_remote={signals.touches_remote} touches_production={signals.touches_production} "
        f"destructive={signals.destructive} external_side_effects={signals.external_side_effects} "
        f"has_tests={signals.has_tests} reversible={signals.reversible}"
    )


@dataclass(frozen=True)
class Answer:
    """One parsed JEV answer. ``confidence`` is None when the service reported none."""

    value: Any
    confidence: float | None
    trusted: bool


@dataclass(frozen=True)
class ParsedAnswers:
    complexity: Answer
    risk: Answer
    parallelizable: Answer


def _parse_complexity(raw: Any) -> Answer:
    index, found = fields(raw, Q_COMPLEXITY, "score", "score")
    if not isinstance(index, int) or isinstance(index, bool):
        raise unparseable(Q_COMPLEXITY)
    if not 0 <= index < len(COMPLEXITY_LEVELS):
        raise unparseable(Q_COMPLEXITY)
    sure = confidence(found, Q_COMPLEXITY)
    return Answer(COMPLEXITY_LEVELS[index][0], sure, trusted(sure))


def _parse_risk(raw: Any) -> Answer:
    key, found = fields(raw, Q_RISK, "choice", "choice")
    if not isinstance(key, str) or key not in RISK_CRITERIA:
        raise unparseable(Q_RISK)
    sure = confidence(found, Q_RISK)
    return Answer(RiskLevel(key), sure, trusted(sure))


def _parse_flag(raw: Any) -> Answer:
    probability, _ = fields(raw, Q_PARALLEL, "noul", "noul")
    if not is_fraction(probability):
        raise unparseable(Q_PARALLEL)
    uncertain = NOUL_UNCERTAIN_LOW < probability < NOUL_UNCERTAIN_HIGH
    return Answer(probability >= YES_THRESHOLD, None, not uncertain)


def parse_answers(stdout: str) -> ParsedAnswers:
    """Interpret ``jev ask`` output; raise ``JevUnavailable`` when it cannot be trusted."""
    data = load_answers(stdout, (Q_COMPLEXITY, Q_RISK, Q_PARALLEL))
    return ParsedAnswers(
        _parse_complexity(data[Q_COMPLEXITY]),
        _parse_risk(data[Q_RISK]),
        _parse_flag(data[Q_PARALLEL]),
    )


class JevProvider:
    """Classifies through ``jev ask``; the other five decisions delegate to ``local``."""

    provider_id = PROVIDER_ID

    def __init__(
        self,
        runner: Runner,
        local: LocalPolicyProvider,
        command: str | Sequence[str] = "jev",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        *,
        redactor: Callable[[str], str],
        program_resolver: Callable[[str], str] | None = None,
        asker: Callable[[Mapping[str, Any], str], str] | None = None,
    ) -> None:
        self._runner = runner
        self._local = local
        self._command = (command,) if isinstance(command, str) else tuple(command)
        self._timeout = timeout_seconds
        self._redactor = redactor
        self._resolve = program_resolver
        self._asker = asker

    def ask(self, questions: Mapping[str, Any], state: str) -> str:
        """One ``jev ask`` call; returns its stdout. ``state`` is redacted before it is
        written, so nothing leaves the machine that the redactor would have removed.
        With an ``asker`` (the built-in HTTPS client) no program runs."""
        if self._asker is not None:
            return self._asker(questions, self._redactor(state))
        command = self._program_command()
        with tempfile.TemporaryDirectory(prefix="wev-jev-") as private:
            questions_file = os.path.join(private, "questions.json")
            state_file = os.path.join(private, "state.txt")
            with open(questions_file, "w", encoding="utf-8") as handle:
                json.dump(dict(questions), handle)
            with open(state_file, "w", encoding="utf-8") as handle:
                handle.write(self._redactor(state))
            argv = (
                *command,
                "ask",
                "--questions",
                questions_file,
                "--state-file",
                state_file,
            )
            try:
                result = self._runner.run(argv, None, self._timeout, None)
            except OSError as exc:
                raise JevUnavailable(
                    "binary_missing", i18n.t("decisions.jev.why.binary_missing")
                ) from exc
        check_exit(result)
        return result.stdout

    def _program_command(self) -> tuple[str, ...]:
        """The configured command with its program resolved, when a resolver is set."""
        if self._resolve is None:
            return self._command
        return (self._resolve(self._command[0]), *self._command[1:])

    def _ask(self, signals: TaskSignals) -> ParsedAnswers:
        return parse_answers(self.ask(build_questions(), build_state(signals)))

    def select_tools(
        self, task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec], tier: str
    ) -> ToolSelection:
        """One ``jev ask`` per task; any failure falls back to the local selection."""
        return jev_tools.select(self.ask, self._local, task, agent, available, tier)

    def classify_task(self, signals: TaskSignals) -> Classification:
        base = self._local.classify_task(signals)
        try:
            answers = self._ask(signals)
        except JevUnavailable as exc:
            reason = i18n.t("decisions.jev.unavailable", why=exc.message or exc.code)
            return _with_reason(base, reason)
        return _merge(base, answers)

    def select_strategy(
        self, classification: Classification, mode: Mode, executor_tier: str = "standard"
    ) -> Strategy:
        return self._local.select_strategy(classification, mode, executor_tier)

    def route_agent(
        self, task: PlanTask, agents: Sequence[AgentLike], default_agent: str = ""
    ) -> str:
        return self._local.route_agent(task, agents, default_agent)

    def evaluate_result(self, contract: TaskContract, result: TaskResult) -> Verdict:
        return self._local.evaluate_result(contract, result)

    def resolve_conflict(self, verdicts: Sequence[Verdict], quorum: int | None = None) -> Verdict:
        return self._local.resolve_conflict(verdicts, quorum)

    def should_escalate(
        self, history: Sequence[AttemptRecord], max_attempts: int | None = None
    ) -> EscalationDecision:
        return self._local.should_escalate(history, max_attempts)


def _with_reason(base: Classification, reason: str) -> Classification:
    return Classification(
        complexity=base.complexity,
        risk=base.risk,
        uncertainty=base.uncertainty,
        parallelizable=base.parallelizable,
        reasons=(reason, *base.reasons),
        source=LOCAL_ID,
    )


def _distrust_reason(question: str, local_value: str) -> str:
    return i18n.t("decisions.jev.distrusted", question=question, value=local_value)


def _pick(answer: Answer, local: Any, question: str, reasons: list[str]) -> Any:
    if answer.trusted:
        return answer.value
    reasons.append(_distrust_reason(question, str(getattr(local, "value", local)).lower()))
    return local


def _uncertainty(base: float, answers: ParsedAnswers) -> float:
    confidences = [
        a.confidence
        for a in (answers.complexity, answers.risk)
        if a.trusted and a.confidence is not None
    ]
    return max(base, 1.0 - min(confidences)) if confidences else base


def _merge(base: Classification, answers: ParsedAnswers) -> Classification:
    notes: list[str] = []
    jev_complexity = _pick(answers.complexity, base.complexity, Q_COMPLEXITY, notes)
    complexity = max(jev_complexity, base.complexity, key=COMPLEXITY_ORDER.index)
    jev_risk = _pick(answers.risk, base.risk, Q_RISK, notes)
    parallel = _pick(answers.parallelizable, base.parallelizable, Q_PARALLEL, notes)
    risk = higher_risk(jev_risk, base.risk)
    reasons = [
        i18n.t("decisions.jev.complexity", value=jev_complexity.value),
        i18n.t("decisions.jev.risk", value=jev_risk.value),
        i18n.t("decisions.jev.parallel", value=str(parallel).lower()),
        *notes,
    ]
    if risk is not jev_risk:
        reasons.append(i18n.t("decisions.jev.floor", local=base.risk.value, jev=jev_risk.value))
    if complexity is not jev_complexity:
        reasons.append(
            i18n.t(
                "decisions.jev.complexity_floor",
                local=base.complexity.value,
                jev=jev_complexity.value,
            )
        )
    reasons.extend(reason for reason in base.reasons if reason not in reasons)
    return Classification(
        complexity=complexity,
        risk=risk,
        uncertainty=_uncertainty(base.uncertainty, answers),
        parallelizable=parallel,
        reasons=tuple(reasons),
        source=PROVIDER_ID,
    )
