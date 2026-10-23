"""Score a specialist against the committed cases and decide its lessons by score alone."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents import project
from wev_skills.agents.experience import ACTIVE, PROPOSED, SCORER, Lesson
from wev_skills.agents.project import ScoreDecisions
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import Config
from wev_skills.core import wiring
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import GuardTripped, NotFound, StateConflict, ValidationError
from wev_skills.core.fsutil import append_line
from wev_skills.core.ports import AgentRunner, Runner
from wev_skills.evaluation import cases as case_store
from wev_skills.evaluation.gitguard import tamper_guard
from wev_skills.evaluation.ratchet import improves
from wev_skills.evaluation.score_pass import Pass
from wev_skills.evaluation.score_runs import Setup
from wev_skills.governance.audit import AuditLog
from wev_skills.state.model import iso_utc

SCORES_FILE = "scores.jsonl"
LOGS_DIR = "score-logs"


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
    planned_runs: int
    skipped: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()


def planned_runs(cases: int, proposals: int, active: int, samples: int, new_lessons: int) -> int:
    """Agent runs plus lesson requests a full pass would use."""
    return (1 + proposals + new_lessons + active) * cases * samples + new_lessons


def _load(root: Path, config: Config, agent_id: str) -> AgentSpec:
    for spec in project.list_specs(root, config):
        if spec.id == agent_id:
            return spec
    raise NotFound(
        "specialist_not_found", i18n.t("evaluation.scoring.no_specialist", specialist=agent_id)
    )


def _refuse_if_baseline_over_cap(config: Config, cases: int) -> None:
    """Only a baseline that alone exceeds the cap refuses; anything else is scored in part."""
    cfg = config.specialists
    needed = cases * cfg.score_samples
    if needed > cfg.score_max_runs:
        message = i18n.t("evaluation.scoring.over_cap", planned=needed, cap=cfg.score_max_runs)
        raise GuardTripped(
            "score_over_cap", message, {"planned": needed, "cap": cfg.score_max_runs}
        )


@dataclass(frozen=True)
class Outcome:
    pass_: Pass
    accepted: tuple[str, ...]
    retired: tuple[str, ...]
    new: tuple[Lesson, ...]


def _measure(
    setup: Setup, config: Config, spec: AgentSpec, cases: tuple[case_store.Case, ...], score_id: str
) -> Outcome:
    """Run the baseline, then proposals oldest first, then ablations, then model lessons."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    run = Pass(setup, config, spec, cases, now)
    proposals = sorted(
        (i for i in spec.experience if i.status == PROPOSED), key=lambda i: (i.created_at, i.id)
    )
    ablatable = [i for i in spec.experience if i.status == ACTIVE and i.accepted_by == SCORER]
    for item in proposals:
        run.variant(item, True)
    for item in ablatable:
        run.variant(item, False)
    run.ask_new(score_id)
    better = {k for k, passes in run.scores.items() if improves(run.baseline.passes, passes)}
    new = tuple(item for item in run.new.values() if item.id in better)
    accepted = tuple(i.id for i in (*proposals, *new) if i.id in better)
    return Outcome(run, accepted, tuple(i.id for i in ablatable if i.id in better), new)


def _audit(audit: AuditLog, agent_id: str, digest: str, outcome: Outcome) -> Callable[[], None]:
    before = sum(outcome.pass_.baseline.passes.values())

    def write() -> None:
        for kind, ids in (
            ("specialists.auto_accept", outcome.accepted),
            ("specialists.auto_retire", outcome.retired),
        ):
            for lesson_id in ids:
                after = sum(outcome.pass_.scores[lesson_id].values())
                payload = {"specialist": agent_id, "lesson": lesson_id, "digest": digest}
                audit.append(kind, {**payload, "before": before, "after": after})

    return write


def _decided(
    root: Path, config: Config, spec: AgentSpec, outcome: Outcome, record: Callable[[], None]
) -> None:
    if outcome.new or outcome.accepted or outcome.retired:
        decisions = ScoreDecisions(outcome.new, outcome.accepted, outcome.retired)
        project.record_scores(root, config, spec.id, spec.experience, decisions, record)


def _in_scratch(
    root: Path,
    config: Config,
    runner: Runner,
    agent: AgentRunner,
    spec: AgentSpec,
    score_id: str,
    guard: Callable[[], None],
) -> Outcome:
    """Measure ``spec`` in a scratch directory outside the state dir, always removed."""
    cfg = config.specialists
    policy = wiring.build_grantless_policy(config, root)
    resolved = wiring.build_agents(config, root).factory.resolve(spec)
    cases = case_store.cases_for(case_store.load_cases(root), spec.id)
    scratch = Path(tempfile.mkdtemp(prefix="wev-scoring-"))
    try:
        setup = Setup(
            root,
            runner,
            policy,
            agent,
            scratch,
            cfg.score_samples,
            cfg.score_timeout_seconds,
            guard,
            wiring.state_dir(config, root) / LOGS_DIR / score_id,
        )
        return _measure(setup, config, resolved, cases, score_id)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _planned(config: Config, spec: AgentSpec, cases: int) -> int:
    cfg = config.specialists
    proposals = sum(1 for item in spec.experience if item.status == PROPOSED)
    ablatable = sum(1 for i in spec.experience if i.status == ACTIVE and i.accepted_by == SCORER)
    return planned_runs(cases, proposals, ablatable, cfg.score_samples, cfg.score_max_new_lessons)


def _report(
    config: Config, spec: AgentSpec, digest: str, score_id: str, outcome: Outcome
) -> ScoreReport:
    run = outcome.pass_
    planned = _planned(config, spec, len(run.cases))
    return ScoreReport(
        score_id, spec.id, digest, run.baseline.passes, outcome.accepted, outcome.retired,
        tuple(item.id for item in outcome.new), run.runs, planned,
        tuple(run.skipped), tuple(run.deferred),
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
    _refuse_if_baseline_over_cap(config, len(cases))
    score_id = f"score-{uuid.uuid4().hex[:12]}"
    cap = config.specialists.score_max_runs
    planned = _planned(config, spec, len(cases))
    print(i18n.t("evaluation.scoring.plan", planned=planned, cap=cap), file=sys.stderr)
    guard = tamper_guard(runner, root)
    outcome = _in_scratch(root, config, runner, agent, spec, score_id, guard)
    guard()
    if case_store.case_set_digest(root) != digest:
        raise StateConflict("cases_changed", i18n.t("evaluation.scoring.cases_changed"))
    _decided(root, config, spec, outcome, _audit(audit, agent_id, digest, outcome))
    report = _report(config, spec, digest, score_id, outcome)
    line = json.dumps({**report.to_dict(), "at": iso_utc(time.time())}, ensure_ascii=False)
    append_line(wiring.state_dir(config, root) / SCORES_FILE, line)
    return report
