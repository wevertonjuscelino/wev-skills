"""One layered-review round of a run: checks, finders and verifiers, one commit at the end."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from pathlib import Path

from wev_skills import i18n
from wev_skills.config_review import DEPTH_OFF, ReviewShape, review_shape
from wev_skills.core.contracts import GuardAction, RiskLevel, TaskStatus
from wev_skills.core.engine import Engine, with_trip
from wev_skills.core.errors import GuardTripped, StateConflict, ValidationError
from wev_skills.core.ports import AgentRunner
from wev_skills.review.guide import load_guide
from wev_skills.review.summary import STATUS_OPEN, summarize
from wev_skills.review.trees import diff_trees, touched_lines, touched_or_cut_lines, write_tree
from wev_skills.review.vote import VoteInputs, VoteResult, find_and_vote
from wev_skills.state.model import RunState
from wev_skills.state.records import GuardTrip
from wev_skills.state.review_records import (
    RULE_REVIEW_ROUNDS,
    FindingRecord,
    ReviewRoundRecord,
    all_findings,
    with_finding_closed,
)

SCOPE_FULL, SCOPE_DIFF = "full", "diff"
RECHECK_WINDOW = 3
CLAUDE_MD = "CLAUDE.md"
MAX_CLAUDE_MD_CHARS = 20_000
STATUS_FIXED = "fixed"
RESOLVED_BY_ROUND = "round:{number}"


def _risk(state: RunState) -> RiskLevel:
    return state.classification.risk if state.classification else RiskLevel.LOW


def _trip(engine: Engine, state: RunState, cap: int, lang: str) -> GuardTripped:
    """Record that the run used its rounds, and the error that says so."""
    reason = i18n.t("review.guard.rounds", lang, used=len(state.review_rounds), cap=cap)
    trip = GuardTrip(engine.stamp(), "", GuardAction.STOP.value, RULE_REVIEW_ROUNDS, (reason,))
    engine.commit(lambda current: with_trip(current, trip), "guard.tripped", trip.to_dict())
    details = {"next_step": f"wev guard check --run {state.run_id}"}
    return GuardTripped("review_rounds", reason, details)


def _checked(engine: Engine, state: RunState, lang: str) -> ReviewShape:
    """The shape of the round, or the refusal that stops it before anything runs."""
    config = engine.services.config.review
    if config.depth == DEPTH_OFF or not config.agent:
        raise ValidationError("review_off", i18n.t("review.error.off", lang))
    if any(task.status is TaskStatus.RUNNING for task in state.tasks.values()):
        raise StateConflict("task_running", i18n.t("review.error.task_running", lang))
    if not state.base:
        raise StateConflict("review_no_base", i18n.t("review.error.no_base", lang))
    cap = config.max_rounds + state.review_allowance
    if len(state.review_rounds) >= cap:
        raise _trip(engine, state, cap, lang)
    shape = review_shape(config, _risk(state))
    runs = shape.finders + shape.verifiers
    if runs > config.max_runs_per_round:
        message = i18n.t("review.error.over_cap", lang, runs=runs, cap=config.max_runs_per_round)
        raise GuardTripped("review_over_cap", message)
    print(i18n.t("review.plan", lang, planned=runs, cap=config.max_runs_per_round), file=sys.stderr)
    return shape


def _claude_md(root: Path) -> str:
    path = root / CLAUDE_MD
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        return ""
    with path.open(encoding="utf-8", errors="replace") as handle:
        return handle.read(MAX_CLAUDE_MD_CHARS)


def _intent(state: RunState) -> str:
    tasks = state.plan.tasks if state.plan else ()
    return "\n".join([state.objective, *(f"- {t.title}: {t.objective}" for t in tasks)])


@dataclass(frozen=True)
class _Scene:
    """What a round looks at: where the tree is now and where each question starts."""

    root: Path
    tree: str
    fingerprint: str
    scope: str
    diff: str
    run_touched: dict[str, frozenset[int]]


def _scene(engine: Engine, state: RunState, number: int, full_rounds: int) -> _Scene:
    runner, root = engine.services.runner, Path(engine.cwd(state))
    tree = write_tree(runner, root)
    full = number <= full_rounds or not state.review_rounds
    since = state.base if full else state.review_rounds[-1].tree
    touched = touched_lines(diff_trees(runner, root, state.base, tree, context=0))
    diff = diff_trees(runner, root, since, tree)
    scope = SCOPE_FULL if full else SCOPE_DIFF
    return _Scene(root, tree, engine.fingerprint(state), scope, diff, touched)


def _rechecks(engine: Engine, state: RunState, scene: _Scene) -> tuple[FindingRecord, ...]:
    """Open findings whose lines (within the window) changed since the round that found them."""
    since: dict[int, dict[str, frozenset[int]]] = {}
    found: list[FindingRecord] = []
    for finding in all_findings(state.review_rounds):
        if finding.status != STATUS_OPEN:
            continue
        if finding.round not in since:
            origin = next(r for r in state.review_rounds if r.number == finding.round)
            diff = diff_trees(engine.services.runner, scene.root, origin.tree, scene.tree, 0)
            since[finding.round] = touched_or_cut_lines(diff)
        # shortcut: the window compares the origin round's line number with current-tree
        # lines, so insertions above a finding can move it out of the window; upgrade by
        # mapping the line through the diff when that misses real fixes.
        rows = since[finding.round].get(finding.file, frozenset())
        if any(abs(row - finding.line) <= RECHECK_WINDOW for row in rows):
            found.append(finding)
    return tuple(found)


def _vote(
    engine: Engine,
    agent: AgentRunner,
    state: RunState,
    scene: _Scene,
    shape: ReviewShape,
    lang: str,
) -> tuple[VoteResult, int]:
    services, config = engine.services, engine.services.config.review
    number = len(state.review_rounds) + 1
    inputs = VoteInputs(
        root=scene.root,
        agent=agent,
        spec=services.agents.resolved(config.agent),
        diff=scene.diff,
        run_touched=scene.run_touched,
        intent=engine.clean(_intent(state)),
        guide=load_guide(scene.root),
        claude_md=engine.clean(_claude_md(scene.root)),
        posted=all_findings(state.review_rounds),
        rechecks=_rechecks(engine, state, scene),
        shape=shape,
        timeout=config.timeout_seconds,
        round=number,
        decide=services.provider.resolve_conflict,
        lang=lang,
    )
    return find_and_vote(inputs), number


def run_round(engine: Engine, agent: AgentRunner, lang: str) -> ReviewRoundRecord:
    """Run one round and record it. Raises before any agent runs when the round is refused.

    The round commits once, against the state it read (``base=state``): a second process that
    changed the run in between makes this commit a ``StateConflict`` and records nothing. A
    ``review_incomplete`` or ``review_agent_failed`` error records no round either.
    """
    state = engine.load()
    shape = _checked(engine, state, lang)
    config = engine.services.config.review
    scene = _scene(engine, state, len(state.review_rounds) + 1, config.full_rounds)
    result, number = _vote(engine, agent, state, scene, shape, lang)
    rounds = state.review_rounds
    for fixed_id in result.fixed:
        by = RESOLVED_BY_ROUND.format(number=number)
        rounds = with_finding_closed(rounds, fixed_id, STATUS_FIXED, STATUS_FIXED, "", by)
    summary = engine.clean(summarize([*all_findings(rounds), *result.kept], result.skipped, lang))
    record = ReviewRoundRecord(
        number, engine.stamp(), scene.scope, scene.tree, scene.fingerprint, config.depth,
        result.kept, result.skipped, result.runs_used, summary,
    )  # fmt: skip
    event = {
        "round": number, "scope": scene.scope, "runs_used": result.runs_used,
        "kept": len(result.kept), "fixed": len(result.fixed), "skipped": result.skipped,
    }  # fmt: skip
    engine.commit(
        lambda current: replace(current, review_rounds=(*rounds, record)),
        "review.round",
        event,
        base=state,
    )
    return record
