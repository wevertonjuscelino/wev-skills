"""Run one configuration of a specialist over the cases and count how often each passes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec
from wev_skills.core.errors import ProviderError
from wev_skills.core.ports import AgentRunner, Runner
from wev_skills.core.textsafe import clean_text
from wev_skills.evaluation import snapshot
from wev_skills.evaluation.cases import Case
from wev_skills.evaluation.workspace import case_workspace, passed, run_check
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


def _run_once(setup: Setup, spec: AgentSpec, case: Case) -> tuple[bool, Failure | None]:
    with case_workspace(setup.runner, setup.root, case, setup.scratch) as path:
        before = snapshot.take(path)
        ran = setup.agent.run_agent(path, spec, case.objective, setup.timeout)
        setup.guard()
        after = snapshot.take(path)  # before run_check copies the case files in
        if not ran.ok and not ran.timed_out:
            error = clean_text(ran.output, ERROR_CHARS)
            raise ProviderError(
                "score_agent_failed",
                i18n.t("evaluation.scoring.agent_failed", case=case.id, error=error),
            )
        if ran.timed_out:  # partial work does not count: no check, a fail
            output = i18n.t("evaluation.scoring.agent_timed_out")
        else:
            result = run_check(setup.runner, setup.policy, case, setup.root, path, setup.timeout)
            if passed(result):
                return True, None
            output = (result.stdout + result.stderr)[-CONTEXT_CHARS:]
    return False, Failure(case, output, snapshot.diff(before, after)[:CONTEXT_CHARS])


def run_configuration(setup: Setup, spec: AgentSpec, cases: Sequence[Case]) -> Tally:
    """Run ``spec`` ``setup.samples`` times on each case; keep the first failure of each case."""
    passes: dict[str, int] = {}
    failures: dict[str, Failure] = {}
    for case in cases:
        passes[case.id] = 0
        for _ in range(setup.samples):
            ok, failure = _run_once(setup, spec, case)
            passes[case.id] += int(ok)
            if failure is not None:
                failures.setdefault(case.id, failure)
    return Tally(passes, tuple(failures.values()), len(cases) * setup.samples)
