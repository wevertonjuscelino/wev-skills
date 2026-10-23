"""One review round's core: finders look for defects, verifiers vote on what they found."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.config_review import ReviewShape
from wev_skills.core.contracts import AgentRunResult, Verdict
from wev_skills.core.errors import ProviderError
from wev_skills.core.ports import READ_ONLY_TOOLS, AgentRunner
from wev_skills.review.findings import (
    RawFinding,
    Vote,
    answered,
    finding_id,
    parse_findings,
    parse_votes,
    proven,
)
from wev_skills.review.guide import ReviewGuide, skipped
from wev_skills.review.prompts import check_size, finder_prompt, verifier_prompt
from wev_skills.state.review_records import FindingRecord

DUPLICATE_LINE_WINDOW = 3
REAL_KINDS = frozenset({"bug", "security"})
TAG_IMPORTANT, TAG_NIT, TAG_PRE_EXISTING = "important", "nit", "pre_existing"


@dataclass(frozen=True)
class VoteInputs:
    root: Path
    agent: AgentRunner
    spec: AgentSpec
    diff: str
    run_touched: Mapping[str, frozenset[int]]
    """Lines the whole run touched (from a ``--unified=0`` diff), not only this round's."""
    intent: str
    guide: ReviewGuide
    claude_md: str
    posted: tuple[FindingRecord, ...]
    rechecks: tuple[FindingRecord, ...]
    shape: ReviewShape
    timeout: float
    round: int
    decide: Callable[[Sequence[Verdict], int], Verdict]
    lang: str


@dataclass(frozen=True)
class VoteResult:
    kept: tuple[FindingRecord, ...]
    fixed: tuple[str, ...]
    skipped: int
    runs_used: int


def _run_all(inputs: VoteInputs, prompt: str, count: int) -> list[AgentRunResult]:
    def run(_: int) -> AgentRunResult:
        return inputs.agent.run_agent(
            inputs.root, inputs.spec, prompt, inputs.timeout, READ_ONLY_TOOLS
        )

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(run, range(count)))


def _found(inputs: VoteInputs) -> list[RawFinding]:
    prompt = check_size(
        finder_prompt(
            inputs.diff, inputs.intent, inputs.guide, inputs.claude_md, inputs.posted, inputs.lang
        ),
        inputs.lang,
    )
    results = _run_all(inputs, prompt, inputs.shape.finders)
    details = {"runs_used": len(results)}
    if all(not r.ok and not r.timed_out for r in results):
        message = i18n.t("review.error.agent_failed", inputs.lang, count=len(results))
        raise ProviderError("review_agent_failed", message, details)
    good = [r for r in results if r.ok and answered(r.output, "findings")]
    if not good:
        message = i18n.t("review.error.incomplete_finders", inputs.lang)
        raise ProviderError("review_incomplete", message, details)
    return [raw for r in good for raw in parse_findings(r.output)]


def _near(a: RawFinding, b: RawFinding) -> bool:
    return a.file == b.file and abs(a.line - b.line) <= DUPLICATE_LINE_WINDOW


def _candidates(inputs: VoteInputs, found: Sequence[RawFinding]) -> tuple[list[RawFinding], int]:
    seen = {r.id for r in inputs.posted}
    kept: list[RawFinding] = []
    skipped_ids: set[str] = set()
    for raw in found:
        ident = finding_id(raw.file, raw.line, raw.title)
        if ident in seen or not proven(raw, inputs.root):
            continue
        if skipped(raw.file, inputs.guide):
            skipped_ids.add(ident)
        elif not any(_near(raw, other) for other in kept):
            kept.append(raw)
    return kept, len(skipped_ids)


def _ballots(inputs: VoteInputs, candidates: Sequence[RawFinding]) -> list[Mapping[int, Vote]]:
    """One ``index -> vote`` map per verifier that answered (a failed run did not)."""
    prompt = check_size(
        verifier_prompt(inputs.diff, candidates, inputs.rechecks, inputs.guide, inputs.lang),
        inputs.lang,
    )
    results = _run_all(inputs, prompt, inputs.shape.verifiers)
    count = len(candidates) + len(inputs.rechecks)
    good = [r for r in results if r.ok and answered(r.output, "votes")]
    return [{v.index: v for v in parse_votes(r.output, count)} for r in good]


def _passes(inputs: VoteInputs, verdicts: Sequence[Verdict]) -> bool:
    quorum = inputs.shape.quorum
    return len(verdicts) >= quorum and inputs.decide(verdicts, quorum).accepted


def _record(
    inputs: VoteInputs, raw: RawFinding, accepting: Sequence[Vote], total: int
) -> FindingRecord:
    important = sum(v.tag == TAG_IMPORTANT for v in accepting) * 2 > len(accepting)
    tag = TAG_IMPORTANT if important else TAG_NIT
    if raw.line not in inputs.run_touched.get(raw.file, frozenset()):
        tag = TAG_PRE_EXISTING
    return FindingRecord(
        finding_id(raw.file, raw.line, raw.title), inputs.round, raw.file, raw.line,
        raw.title, raw.body, tag, raw.class_wide, len(accepting), total,
    )  # fmt: skip


def _judged(
    inputs: VoteInputs, candidates: Sequence[RawFinding], ballots: Sequence[Mapping[int, Vote]]
) -> list[FindingRecord]:
    kept: list[FindingRecord] = []
    for index, raw in enumerate(candidates):
        votes = [b.get(index) for b in ballots]
        accepting = [v for v in votes if v and v.real and v.kind in REAL_KINDS]
        verdicts = [Verdict(accepted=bool(v and v in accepting), score=1.0) for v in votes]
        if _passes(inputs, verdicts):
            kept.append(_record(inputs, raw, accepting, len(ballots)))
    return kept


def _capped(kept: Sequence[FindingRecord], cap: int) -> tuple[FindingRecord, ...]:
    nits = sorted((r for r in kept if r.tag == TAG_NIT), key=lambda r: -r.votes_real)[:cap]
    return tuple(r for r in kept if r.tag != TAG_NIT or r in nits)


def _fixed(
    inputs: VoteInputs, first_index: int, ballots: Sequence[Mapping[int, Vote]]
) -> tuple[str, ...]:
    fixed: list[str] = []
    for offset, record in enumerate(inputs.rechecks):
        votes = [b.get(first_index + offset) for b in ballots]
        verdicts = [Verdict(accepted=bool(v and not v.real), score=1.0) for v in votes]
        if _passes(inputs, verdicts):
            fixed.append(record.id)
    return tuple(fixed)


def find_and_vote(inputs: VoteInputs) -> VoteResult:
    finders = inputs.shape.finders
    candidates, skipped_count = _candidates(inputs, _found(inputs) if finders else [])
    if not (candidates or inputs.rechecks) or not inputs.shape.verifiers:
        return VoteResult((), (), skipped_count, finders)
    ballots = _ballots(inputs, candidates)
    if len(ballots) < inputs.shape.quorum:
        message = i18n.t(
            "review.error.incomplete_verifiers",
            inputs.lang,
            answered=len(ballots),
            quorum=inputs.shape.quorum,
        )
        runs = {"runs_used": finders + inputs.shape.verifiers}
        raise ProviderError("review_incomplete", message, runs)
    kept = _capped(_judged(inputs, candidates, ballots), inputs.guide.nit_cap)
    fixed = _fixed(inputs, len(candidates), ballots)
    return VoteResult(kept, fixed, skipped_count, finders + inputs.shape.verifiers)
