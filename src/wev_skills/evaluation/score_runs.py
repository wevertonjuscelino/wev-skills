"""Run one configuration of a specialist over the cases and count how often each passes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.config_review import ReviewShape
from wev_skills.core.errors import ProviderError
from wev_skills.core.ports import AgentRunner, Runner
from wev_skills.core.textsafe import clean_text
from wev_skills.evaluation import snapshot
from wev_skills.evaluation.cases import Case
from wev_skills.evaluation.workspace import case_workspace, passed, run_check, skip_git_cleanup
from wev_skills.review.guide import ReviewGuide
from wev_skills.security.permissions import PermissionPolicy

ERROR_CHARS = 200
CONTEXT_CHARS = 8000
"""Most characters of a check's output or an agent's diff handed to the lesson request."""


@dataclass(frozen=True)
class Setup:
    """What every run of a scoring pass shares."""

    root: Path
    runner: Runner
    policy: PermissionPolicy
    agent: AgentRunner
    scratch: Path
    samples: int
    timeout: float
    guard: Callable[[], None]
    """Called right after every agent run, before any git call; raises if git was tampered."""
    shape: ReviewShape = ReviewShape(0, 0, 0)
    """Finders, verifiers and quorum of a review case's sample."""
    guide: ReviewGuide = ReviewGuide()
    lang: str = "en"


@dataclass(frozen=True)
class Failure:
    """A run whose check failed: what the lesson request is built from."""

    case: Case
    output: str
    diff: str


@dataclass(frozen=True)
class Tally:
    passes: dict[str, int]
    failures: tuple[Failure, ...]
    runs: int


def _attempt(setup: Setup, spec: AgentSpec, case: Case, path: Path) -> tuple[bool, Failure | None]:
    before = snapshot.take(path)
    ran = setup.agent.run_agent(path, spec, case.objective, setup.timeout)
    setup.guard()
    after = snapshot.take(path)  # before run_check copies the case files in
    if not ran.ok and not ran.timed_out:
        error = clean_text(ran.output, ERROR_CHARS)
        message = i18n.t("evaluation.scoring.agent_failed", case=case.id, error=error)
        raise ProviderError("score_agent_failed", message)
    if ran.timed_out:  # partial work does not count: no check, a fail
        output = i18n.t("evaluation.scoring.agent_timed_out")
    else:
        result = run_check(setup.runner, setup.policy, case, setup.root, path, setup.timeout)
        setup.guard()  # the check runs what the agent wrote
        if passed(result):
            return True, None
        output = (result.stdout + result.stderr)[-CONTEXT_CHARS:]
    return False, Failure(case, output, snapshot.diff(before, after)[:CONTEXT_CHARS])


def case_runs(setup: Setup, case: Case) -> int:
    """Agent runs one sample of ``case`` can use."""
    return setup.shape.finders + setup.shape.verifiers if case.kind == "review" else 1


def _run_once(setup: Setup, spec: AgentSpec, case: Case) -> tuple[bool, Failure | None, int]:
    """One sample: whether it passed, its failure, and the agent runs it used."""
    if case.kind == "review":
        from wev_skills.evaluation.review_attempt import review_sample  # lazy: imports this module

        return review_sample(setup, spec, case)
    with case_workspace(setup.runner, setup.root, case, setup.scratch) as path:
        try:
            ok, failure = _attempt(setup, spec, case, path)
            return ok, failure, 1
        except BaseException as exc:  # the agent may have planted git state: no git call
            skip_git_cleanup(exc)
            raise


def run_configuration(setup: Setup, spec: AgentSpec, cases: Sequence[Case]) -> Tally:
    """Run ``spec`` ``setup.samples`` times on each case; keep the first failure of each case."""
    passes: dict[str, int] = {}
    failures: dict[str, Failure] = {}
    runs = 0
    for case in cases:
        passes[case.id] = 0
        for _ in range(setup.samples):
            ok, failure, used = _run_once(setup, spec, case)
            runs += used
            passes[case.id] += int(ok)
            if failure is not None:
                failures.setdefault(case.id, failure)
    return Tally(passes, tuple(failures.values()), runs)
