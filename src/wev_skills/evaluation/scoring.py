"""Score a specialist against the committed cases and decide its lessons by score alone."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents import project
from wev_skills.agents.experience import ACTIVE, PROPOSED, SCORER, Lesson
from wev_skills.agents.learning import model_lesson
from wev_skills.agents.project import ScoreDecisions
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import Config
from wev_skills.core import wiring
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import GuardTripped, NotFound, StateConflict, ValidationError
from wev_skills.core.fsutil import append_line
from wev_skills.core.ports import AgentRunner, Runner
from wev_skills.evaluation import cases as case_store
from wev_skills.evaluation.lesson_writer import lesson_request, parse_lesson
from wev_skills.evaluation.ratchet import improves
from wev_skills.evaluation.score_runs import Setup, Tally, run_configuration
from wev_skills.governance.audit import AuditLog

SCORES_FILE = "scores.jsonl"
_FENCE = re.compile(r"\A```[A-Za-z]*\n(.*)\n```\Z", re.DOTALL)


@dataclass(frozen=True)
class ScoreReport(Serializable):
    score_id: str
    agent: str
    digest: str
    baseline: dict[str, int]
    accepted: tuple[str, ...]
    retired: tuple[str, ...]
    new: tuple[str, ...]
    runs_used: int


def planned_runs(cases: int, proposals: int, active: int, samples: int, new_lessons: int) -> int:
    """Agent runs plus lesson requests one pass may use (the cap is checked against this)."""
    return (1 + proposals + new_lessons + active) * cases * samples + new_lessons


def _unfence(answer: str) -> str:
    """Drop exactly one surrounding code fence; the lesson filter judges the rest."""
    found = _FENCE.match(answer.strip())
    return found.group(1) if found else answer


def _shown_as(lesson: Lesson) -> Lesson:
    return replace(lesson, status=ACTIVE, accepted_by=SCORER)


def _with(spec: AgentSpec, lesson: Lesson) -> AgentSpec:
    kept = tuple(item for item in spec.experience if item.id != lesson.id)
    return replace(spec, experience=(*kept, _shown_as(lesson)))


def _without(spec: AgentSpec, lesson_id: str) -> AgentSpec:
    return replace(spec, experience=tuple(i for i in spec.experience if i.id != lesson_id))


def _load(root: Path, config: Config, agent_id: str) -> AgentSpec:
    for spec in project.list_specs(root, config):
        if spec.id == agent_id:
            return spec
    raise NotFound(
        "specialist_not_found", i18n.t("evaluation.scoring.no_specialist", specialist=agent_id)
    )


def _refuse_over_cap(config: Config, cases: int, proposals: int, active: int) -> None:
    cfg = config.specialists
    planned = planned_runs(cases, proposals, active, cfg.score_samples, cfg.score_max_new_lessons)
    if planned > cfg.score_max_runs:
        message = i18n.t("evaluation.scoring.over_cap", planned=planned, cap=cfg.score_max_runs)
        raise GuardTripped(
            "score_over_cap", message, {"planned": planned, "cap": cfg.score_max_runs}
        )


def _new_lessons(
    setup: Setup, config: Config, spec: AgentSpec, baseline: Tally, score_id: str
) -> tuple[tuple[Lesson, ...], int]:
    """Ask for one lesson per failed case (at most the configured number); keep the safe ones."""
    known = {item.id for item in spec.experience}
    now = datetime.now(UTC).isoformat(timespec="seconds")
    found: dict[str, Lesson] = {}
    asked = 0
    for failure in baseline.failures[: config.specialists.score_max_new_lessons]:
        prompt = lesson_request(failure.case, failure.output, failure.diff, config.language)
        answer = setup.agent.ask(prompt, setup.timeout)
        asked += 1
        text = parse_lesson(_unfence(answer.output)) if answer.ok else None
        if text is None:
            continue
        lesson = model_lesson(failure.case.id, text, score_id, now)
        if lesson.id not in known:
            found.setdefault(lesson.id, lesson)
    return tuple(found.values()), asked


def _totals(passes: Mapping[str, int]) -> int:
    return sum(passes.values())


@dataclass(frozen=True)
class Outcome:
    baseline: dict[str, int]
    scores: dict[str, dict[str, int]]
    new: tuple[Lesson, ...]
    accepted: tuple[str, ...]
    retired: tuple[str, ...]
    runs_used: int


def _measure(
    setup: Setup,
    config: Config,
    spec: AgentSpec,
    cases: tuple[case_store.Case, ...],
    ablatable: tuple[Lesson, ...],
    score_id: str,
) -> Outcome:
    baseline = run_configuration(setup, spec, cases)
    new, asked = _new_lessons(setup, config, spec, baseline, score_id)
    proposals = tuple(item for item in spec.experience if item.status == PROPOSED)
    variants = {item.id: _with(spec, item) for item in (*proposals, *new)}
    variants |= {item.id: _without(spec, item.id) for item in ablatable}
    scores = {key: run_configuration(setup, v, cases).passes for key, v in variants.items()}
    better = {key for key, passes in scores.items() if improves(baseline.passes, passes)}
    return Outcome(
        baseline.passes,
        scores,
        new,
        tuple(item.id for item in (*proposals, *new) if item.id in better),
        tuple(item.id for item in ablatable if item.id in better),
        baseline.runs + asked + len(variants) * len(cases) * setup.samples,
    )


def _audit_writer(
    audit: AuditLog, agent_id: str, digest: str, outcome: Outcome
) -> Callable[[str, tuple[str, ...]], Callable[[], None]]:
    before = _totals(outcome.baseline)

    def writer(kind: str, ids: tuple[str, ...]) -> Callable[[], None]:
        def write() -> None:
            for lesson_id in ids:
                after = _totals(outcome.scores[lesson_id])
                payload = {"specialist": agent_id, "lesson": lesson_id, "digest": digest}
                audit.append(kind, {**payload, "before": before, "after": after})

        return write

    return writer


def _record(
    root: Path,
    config: Config,
    spec: AgentSpec,
    outcome: Outcome,
    writer: Callable[[str, tuple[str, ...]], Callable[[], None]],
) -> None:
    """A model lesson is written first and accepted by a second call: the first call adds it."""
    fresh = {item.id for item in outcome.new}
    first = tuple(i for i in outcome.accepted if i not in fresh)
    later = tuple(i for i in outcome.accepted if i in fresh)
    accept, retire = (
        writer("specialists.auto_accept", first),
        writer("specialists.auto_retire", outcome.retired),
    )

    def record() -> None:
        accept()
        retire()

    updated = spec
    if outcome.new or first or outcome.retired:
        decisions = ScoreDecisions(outcome.new, first, outcome.retired)
        updated = project.record_scores(root, config, spec.id, spec.experience, decisions, record)
    if later:
        project.record_scores(
            root, config, spec.id, updated.experience, ScoreDecisions(accepted=later),
            writer("specialists.auto_accept", later),
        )  # fmt: skip


def score_specialist(
    root: Path, config: Config, runner: Runner, agent: AgentRunner, agent_id: str, audit: AuditLog
) -> ScoreReport:
    case_store.ensure_committed(runner, root)
    digest = case_store.case_set_digest(root)
    spec = _load(root, config, agent_id)
    cases = case_store.cases_for(case_store.load_cases(root), agent_id)
    if not cases:
        raise ValidationError("score_no_cases", i18n.t("evaluation.scoring.no_cases"))
    ablatable = tuple(i for i in spec.experience if i.status == ACTIVE and i.accepted_by == SCORER)
    proposals = sum(1 for item in spec.experience if item.status == PROPOSED)
    _refuse_over_cap(config, len(cases), proposals, len(ablatable))
    resolved = wiring.build_agents(config, root).factory.resolve(spec)
    scratch = Path(tempfile.mkdtemp(prefix="wev-scoring-"))
    policy = wiring.build_grantless_policy(config, root)
    cfg = config.specialists
    setup = Setup(
        root, runner, policy, agent, scratch, cfg.score_samples, cfg.score_timeout_seconds
    )
    score_id = f"score-{uuid.uuid4().hex[:12]}"
    try:
        outcome = _measure(setup, config, resolved, cases, ablatable, score_id)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if case_store.case_set_digest(root) != digest:
        raise StateConflict("cases_changed", i18n.t("evaluation.scoring.cases_changed"))
    _record(root, config, spec, outcome, _audit_writer(audit, agent_id, digest, outcome))
    report = ScoreReport(
        score_id, agent_id, digest, outcome.baseline, outcome.accepted, outcome.retired,
        tuple(item.id for item in outcome.new), outcome.runs_used,
    )  # fmt: skip
    line = json.dumps(report.to_dict(), ensure_ascii=False)
    append_line(wiring.state_dir(config, root) / SCORES_FILE, line)
    return report
