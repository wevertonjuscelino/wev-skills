"""Deterministic, offline decision rules. The default provider and the JEV fallback."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.agents.tool_profile import resolve_profile
from wev_skills.config import TIER_NAMES, HarnessSettings, LimitsConfig
from wev_skills.core.contracts import (
    AttemptRecord,
    Classification,
    Complexity,
    EscalationDecision,
    EvidenceLabel,
    Flow,
    GuardAction,
    Mode,
    PlanTask,
    RiskLevel,
    Strategy,
    TaskContract,
    TaskResult,
    TaskSignals,
    TaskStatus,
    ToolSelection,
    Verdict,
    higher_risk,
)
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.core.ports import AgentLike
from wev_skills.decisions import lexicon, local_tools, tool_selection
from wev_skills.decisions.tool_selection import Proposal, ToolAgent
from wev_skills.tools.registry import ToolSpec

__all__ = ["LocalPolicyProvider", "higher_risk"]

PROVIDER_ID = "local-policy"

MEDIUM_RISK_FILE_LIMIT = 5
UNTESTED_FILE_LIMIT = 1
TRIVIAL_MAX_FILES = 1
SIMPLE_MAX_FILES = 3
SIMPLE_MAX_UNKNOWNS = 1
MODERATE_MAX_FILES = 10
MODERATE_MAX_UNKNOWNS = 3
UNCERTAINTY_PER_UNKNOWN = 0.2
UNCERTAINTY_WITHOUT_TESTS = 0.2
PARALLEL_MIN_SUBTASKS = 2
ESCALATION_SHARE = 2
"""Escalate once failures reach the attempt limit divided by this, rounded up."""
SECURITY_SPECIALTY = "security"
MIN_WORD_LENGTH = 2
PLURAL_MIN_LENGTH = 4
SPECIALTY_WORD_WEIGHT = 3
SPECIALTY_WHOLE_BONUS = 2
DESCRIPTION_WORD_WEIGHT = 1
STOP_WORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "do", "each", "for", "from", "has",
    "in", "into", "is", "it", "its", "not", "of", "on", "or", "so", "that", "the", "then",
    "this", "to", "up", "use", "when", "with",
})  # fmt: skip
"""Words that say nothing about what a task or an agent is for; they never score."""

DEFAULT_EXECUTOR_TIER = "standard"
COMPLEXITY_ORDER = (Complexity.TRIVIAL, Complexity.SIMPLE, Complexity.MODERATE, Complexity.COMPLEX)
PLAN_FROM_COMPLEXITY = {
    "economy": Complexity.SIMPLE,
    "standard": Complexity.MODERATE,
    "premium": Complexity.MODERATE,
}
"""With ``planning: auto``, the lowest complexity at which a low-risk task gets a plan, by
executor tier. Economy plans anything above trivial; premium skips the plan on small tasks.
The rule is a configurable default motivated by docs/research/hypotheses.md (H4, H8); its
effect has not been measured with a real model. Standard and premium currently share a
threshold: the standard rule predates tiers and already skipped the plan on small tasks.
With ``executor_tier: auto`` the rule therefore changes nothing for non-trivial tasks: the
router sends only trivial low-risk work to economy, and everything else lands on a tier with
the same threshold. The reasons and the help text say so."""

_WORD = re.compile(r"[a-z0-9]+")


def _validate(signals: TaskSignals) -> None:
    if signals.files_touched_estimate < 0 or signals.unknowns < 0:
        raise ValidationError("invalid_signals", i18n.t("decisions.error.negative_signal"))
    if signals.independent_subtasks < 1:
        raise ValidationError("invalid_signals", i18n.t("decisions.error.subtasks"))


def compute_risk(signals: TaskSignals) -> tuple[RiskLevel, tuple[str, ...]]:
    """Apply every risk rule; the level is the highest fired, reasons list each fired rule."""
    files = signals.files_touched_estimate
    rules = (
        (signals.touches_production, RiskLevel.HIGH, "decisions.risk.production"),
        (signals.destructive, RiskLevel.HIGH, "decisions.risk.destructive"),
        (signals.external_side_effects, RiskLevel.HIGH, "decisions.risk.external"),
        (
            signals.touches_remote and not signals.reversible,
            RiskLevel.HIGH,
            "decisions.risk.remote_irreversible",
        ),
        (signals.touches_remote, RiskLevel.MEDIUM, "decisions.risk.remote"),
        (signals.touches_credentials, RiskLevel.MEDIUM, "decisions.risk.credentials"),
        (signals.changes_data_schema, RiskLevel.MEDIUM, "decisions.risk.data_schema"),
        (not signals.reversible, RiskLevel.MEDIUM, "decisions.risk.irreversible"),
        (files > MEDIUM_RISK_FILE_LIMIT, RiskLevel.MEDIUM, "decisions.risk.many_files"),
        (
            not signals.has_tests and files > UNTESTED_FILE_LIMIT,
            RiskLevel.MEDIUM,
            "decisions.risk.untested",
        ),
    )
    fired = [(level, key) for hit, level, key in rules if hit]
    if not fired:
        return RiskLevel.LOW, (i18n.t("decisions.risk.low"),)
    level = RiskLevel.LOW
    for rule_level, _ in fired:
        level = higher_risk(level, rule_level)
    return level, tuple(i18n.t(key, files=files) for _, key in fired)


def compute_complexity(signals: TaskSignals) -> tuple[Complexity, str]:
    files, unknowns = signals.files_touched_estimate, signals.unknowns
    if files <= TRIVIAL_MAX_FILES and unknowns == 0 and signals.independent_subtasks == 1:
        level = Complexity.TRIVIAL
    elif files <= SIMPLE_MAX_FILES and unknowns <= SIMPLE_MAX_UNKNOWNS:
        level = Complexity.SIMPLE
    elif files <= MODERATE_MAX_FILES and unknowns <= MODERATE_MAX_UNKNOWNS:
        level = Complexity.MODERATE
    else:
        level = Complexity.COMPLEX
    reason = i18n.t(f"decisions.complexity.{level.value}", files=files, unknowns=unknowns)
    return level, reason


def compute_uncertainty(signals: TaskSignals) -> float:
    penalty = 0.0 if signals.has_tests else UNCERTAINTY_WITHOUT_TESTS
    return min(1.0, UNCERTAINTY_PER_UNKNOWN * signals.unknowns + penalty)


def _singular(word: str) -> str:
    """``tests`` and ``test`` are one word; nothing cleverer than a trailing ``s``."""
    plural = len(word) >= PLURAL_MIN_LENGTH and word.endswith("s") and not word.endswith("ss")
    return word[:-1] if plural else word


def task_words(text: str) -> frozenset[str]:
    """Whole lower-case words of ``text``, without stop words; plurals count as the singular."""
    found = (_singular(word) for word in _WORD.findall(text.lower()))
    return frozenset(w for w in found if len(w) >= MIN_WORD_LENGTH and w not in STOP_WORDS)


def agent_score(words: frozenset[str], agent: AgentLike) -> int:
    """How well ``agent`` fits a task made of ``words``; zero when nothing matches.

    A specialty word found in the task weighs more than a description word, and a specialty
    matched in full (``security``) beats a fragment of one (``review`` of ``code-review``).
    Matching is by whole word, never by substring.
    """
    score = 0
    counted: set[str] = set()
    for specialty in agent.specialties:
        parts = task_words(specialty)
        hits = parts & words
        score += SPECIALTY_WORD_WEIGHT * len(hits - counted)
        score += SPECIALTY_WHOLE_BONUS if parts and hits == parts else 0
        counted |= hits
    described = (task_words(agent.description) & words) - counted
    return score + DESCRIPTION_WORD_WEIGHT * len(described)


class LocalPolicyProvider:
    """Rule-based provider: no network, no randomness, every decision explained."""

    provider_id = PROVIDER_ID

    def __init__(self, limits: LimitsConfig, harness: HarnessSettings | None = None) -> None:
        self._limits = limits
        self._harness = harness if harness is not None else HarnessSettings()

    def classify_task(self, signals: TaskSignals) -> Classification:
        """Classify from the signals after the lexical floor raised what the objective implies."""
        _validate(signals)
        signals, floor_reasons = lexicon.floor_signals(signals)
        risk, risk_reasons = compute_risk(signals)
        complexity, complexity_reason = compute_complexity(signals)
        uncertainty = compute_uncertainty(signals)
        parallel = signals.independent_subtasks >= PARALLEL_MIN_SUBTASKS
        reasons = [*floor_reasons, *risk_reasons, complexity_reason]
        if uncertainty > 0:
            reasons.append(i18n.t("decisions.uncertainty", value=f"{uncertainty:.1f}"))
        if parallel:
            reasons.append(i18n.t("decisions.parallel", subtasks=signals.independent_subtasks))
        return Classification(
            complexity=complexity,
            risk=risk,
            uncertainty=uncertainty,
            parallelizable=parallel,
            reasons=tuple(reasons),
            source=PROVIDER_ID,
        )

    def _plan_rule(self, classification: Classification, mode: Mode, tier: str) -> tuple[bool, str]:
        """Whether a plan is made, and the reason naming the tier and the rule applied."""
        risk, policy = classification.risk, self._harness.planning
        if mode is Mode.PLAN or risk is RiskLevel.HIGH:
            return True, i18n.t("decisions.plan.forced", tier=tier, planning=policy)
        if policy != "auto":
            return policy == "always", i18n.t(f"decisions.plan.{policy}", tier=tier)
        level = COMPLEXITY_ORDER.index(classification.complexity)
        threshold = COMPLEXITY_ORDER.index(PLAN_FROM_COMPLEXITY[tier])
        wanted = risk is not RiskLevel.LOW or level >= threshold
        return wanted, i18n.t(f"decisions.plan.auto.{tier}", tier=tier)

    def select_strategy(
        self, classification: Classification, mode: Mode, executor_tier: str = DEFAULT_EXECUTOR_TIER
    ) -> Strategy:
        """Flow, plan, review and approval for a classified task.

        Only the plan step depends on ``executor_tier`` and on ``harness.planning``. Risk
        rules, approval, review and the limits are the same for every tier.
        """
        risk, complexity = classification.risk, classification.complexity
        tier = executor_tier if executor_tier in TIER_NAMES else DEFAULT_EXECUTOR_TIER
        plan, plan_reason = self._plan_rule(classification, mode, tier)
        review = risk is not RiskLevel.LOW or complexity is Complexity.COMPLEX
        small = risk is RiskLevel.LOW and complexity in (Complexity.TRIVIAL, Complexity.SIMPLE)
        if mode is Mode.PLAN:
            flow, key = Flow.PLANNED, "plan_mode"
        elif risk is RiskLevel.HIGH:
            flow, key = Flow.GATED, "gated"
        elif plan:
            flow, key = Flow.PLANNED, "planned"
        else:
            flow, key = Flow.DIRECT, "direct" if small else "no_plan"
        reasons = [i18n.t(f"decisions.strategy.{key}"), plan_reason]
        if review:
            reasons.append(i18n.t("decisions.strategy.review"))
        parallel = self._limits.max_parallel if classification.parallelizable else 1
        reasons.append(i18n.t("decisions.strategy.parallel", max_parallel=parallel))
        return Strategy(
            flow=flow,
            needs_plan=plan,
            needs_independent_review=review,
            needs_approval=flow is Flow.GATED,
            max_parallel=parallel,
            max_attempts=self._limits.max_attempts,
            reasons=tuple(reasons),
        )

    def route_agent(
        self, task: PlanTask, agents: Sequence[AgentLike], default_agent: str = ""
    ) -> str:
        """The hinted agent, else the best-scoring one (ties by id), else the default.

        Two rules narrow the candidates first, when someone qualifies: a task about remote
        systems goes to an agent allowed to use them, and a read-only security review goes
        to an agent whose specialty is security. When no agent scores above zero the task
        says nothing about who should take it, so it goes to ``default_agent`` when that is
        a candidate, otherwise to the first id.
        """
        if not agents:
            raise NotFound("no_agents", i18n.t("decisions.error.no_agents"))
        ids = sorted(agent.id for agent in agents)
        if task.agent_hint and task.agent_hint in ids:
            return task.agent_hint
        text = f"{task.title} {task.objective}"
        preferred = _preferred(task, text, agents)
        words = task_words(text)
        scored = sorted((-agent_score(words, agent), agent.id) for agent in preferred or agents)
        if scored[0][0] < 0 or preferred:
            return scored[0][1]
        return default_agent if default_agent in ids else ids[0]

    @property
    def harness(self) -> HarnessSettings:
        return self._harness

    def propose_tools(
        self, task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec], tier: str
    ) -> Proposal:
        """The local proposal, before the selection rules; ``auto`` resolves by ``tier``."""
        known = tier if tier in TIER_NAMES else DEFAULT_EXECUTOR_TIER
        profile = resolve_profile(self._harness.tool_profile, known)
        return local_tools.propose(task, agent, available, profile, PROVIDER_ID)

    def select_tools(
        self, task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec], tier: str
    ) -> ToolSelection:
        """The smallest tool set the task gives a reason for (see ``decisions.local_tools``)."""
        proposal = self.propose_tools(task, agent, available, tier)
        return tool_selection.enforce(task, agent, available, proposal)

    def evaluate_result(self, contract: TaskContract, result: TaskResult) -> Verdict:
        evidence = result.evidence
        failing = [e for e in evidence if e.kind == "command" and e.exit_code not in (None, 0)]
        supporting = [e for e in evidence if e.label is EvidenceLabel.TESTED and e not in failing]
        reasons: list[str] = []
        if result.status is not TaskStatus.VERIFIED:
            reasons.append(i18n.t("decisions.eval.status", status=result.status.value))
        if not evidence:
            reasons.append(i18n.t("decisions.eval.no_evidence"))
        elif not any(e.label is EvidenceLabel.TESTED for e in evidence):
            reasons.append(i18n.t("decisions.eval.no_tested"))
        if failing:
            reasons.append(i18n.t("decisions.eval.failing", count=len(failing)))
        accepted = not reasons
        if accepted:
            reasons.append(i18n.t("decisions.eval.accepted", count=len(supporting)))
        score = len(supporting) / len(evidence) if evidence else 0.0
        return Verdict(accepted=accepted, score=score, reasons=tuple(reasons), source=PROVIDER_ID)

    def resolve_conflict(self, verdicts: Sequence[Verdict], quorum: int | None = None) -> Verdict:
        if not verdicts:
            raise ValidationError("no_verdicts", i18n.t("decisions.error.no_verdicts"))
        if quorum is not None and not 1 <= quorum <= len(verdicts):
            message = i18n.t("decisions.error.bad_quorum", quorum=quorum, count=len(verdicts))
            raise ValidationError("bad_quorum", message)
        needed = len(verdicts) if quorum is None else quorum
        merged: list[str] = []
        for verdict in verdicts:
            merged.extend(r for r in verdict.reasons if r not in merged)
        return Verdict(
            accepted=sum(v.accepted for v in verdicts) >= needed,
            score=min(v.score for v in verdicts),
            reasons=tuple(merged),
            source=PROVIDER_ID,
        )

    def should_escalate(
        self, history: Sequence[AttemptRecord], max_attempts: int | None = None
    ) -> EscalationDecision:
        """Whether the next attempt should run on a stronger model.

        Escalation fires after half the attempts (rounded up) or on an error signature that
        repeats, whichever comes first, so the stronger model still has an attempt left to
        use. ``max_attempts`` is the task's effective limit when it is lower than the
        configured one. At the limit the only way forward is a person.
        """
        failed = sorted(
            (r for r in history if r.status is TaskStatus.FAILED), key=lambda r: r.attempt
        )
        count = len(failed)
        limit = min(self._limits.max_attempts, max_attempts or self._limits.max_attempts)
        if count == 0:
            return EscalationDecision(False, GuardAction.CONTINUE, (i18n.t("decisions.esc.few"),))
        if count >= limit:
            reason = i18n.t("decisions.esc.ask_human", count=count, limit=limit)
            return EscalationDecision(True, GuardAction.ASK_HUMAN, (reason,))
        last = failed[-1].error_signature
        if count >= 2 and last and last == failed[-2].error_signature:
            reason = i18n.t("decisions.esc.repeat", signature=last)
            return EscalationDecision(True, GuardAction.ESCALATE, (reason,))
        if count >= math.ceil(limit / ESCALATION_SHARE):
            reason = i18n.t("decisions.esc.limit", count=count, limit=limit)
            return EscalationDecision(True, GuardAction.ESCALATE, (reason,))
        return EscalationDecision(False, GuardAction.CONTINUE, (i18n.t("decisions.esc.keep"),))


def _may_use_remote(agent: AgentLike) -> bool:
    permissions = getattr(agent, "permissions", None)
    return bool(getattr(permissions, "may_use_remote", False))


def _preferred(task: PlanTask, text: str, agents: Sequence[AgentLike]) -> list[AgentLike]:
    """Candidates a routing rule singles out for this task; empty when no rule applies."""
    if lexicon.mentions(text, lexicon.REMOTE):
        remote = [agent for agent in agents if _may_use_remote(agent)]
        if remote:
            return remote
    if task.read_only and lexicon.is_security_review(text):
        return [agent for agent in agents if SECURITY_SPECIALTY in agent.specialties]
    return []
