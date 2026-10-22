"""One scoring pass: the baseline, then each candidate variant while the run budget lasts."""

from __future__ import annotations

import re
from dataclasses import replace

from wev_skills.agents.experience import ACTIVE, SCORER, Lesson, shown_lesson_ids
from wev_skills.agents.learning import model_lesson
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import Config
from wev_skills.evaluation.cases import Case
from wev_skills.evaluation.lesson_writer import lesson_request, parse_lesson
from wev_skills.evaluation.score_runs import Setup, run_configuration


def with_lesson(spec: AgentSpec, lesson: Lesson) -> AgentSpec:
    """``spec`` with ``lesson`` shown as active (a candidate is hidden otherwise)."""
    kept = tuple(item for item in spec.experience if item.id != lesson.id)
    return replace(spec, experience=(*kept, replace(lesson, status=ACTIVE, accepted_by=SCORER)))


def without_lesson(spec: AgentSpec, lesson_id: str) -> AgentSpec:
    return replace(spec, experience=tuple(i for i in spec.experience if i.id != lesson_id))


_FENCE = re.compile(r"\A```[A-Za-z]*\n(.*)\n```\Z", re.DOTALL)


class Pass:
    """Mutable bookkeeping of one run: passes per variant, runs spent, what was left out."""

    def __init__(
        self, setup: Setup, config: Config, spec: AgentSpec, cases: tuple[Case, ...], now: str
    ) -> None:
        self.setup, self.config, self.spec, self.cases, self.now = setup, config, spec, cases, now
        self.cost = len(cases) * setup.samples
        self.baseline = run_configuration(setup, spec, cases)
        self.runs = self.baseline.runs
        self.shown = self._shown(spec)
        self.scores: dict[str, dict[str, int]] = {}
        self.new: dict[str, Lesson] = {}
        self.skipped: list[str] = []
        self.deferred: list[str] = []

    def _shown(self, spec: AgentSpec) -> set[str]:
        return set(shown_lesson_ids(spec.experience, self.config.specialists.max_lessons_rendered))

    def _budget_left(self, extra: int = 0) -> bool:
        return self.runs + extra + self.cost <= self.config.specialists.score_max_runs

    def variant(self, lesson: Lesson, add: bool) -> None:
        """Run ``lesson`` added (``add``) or removed, if it fits the budget and is really shown."""
        if not self._budget_left():
            self.deferred.append(lesson.id)
            return
        spec = with_lesson(self.spec, lesson) if add else without_lesson(self.spec, lesson.id)
        shown = self._shown(spec)
        if add and lesson.id not in shown:
            self.skipped.append(f"{lesson.id}: not_shown")
        elif not add and (lesson.id not in self.shown or shown != self.shown - {lesson.id}):
            self.skipped.append(f"{lesson.id}: ablation_changes_other_lessons")
        else:
            self.scores[lesson.id] = run_configuration(self.setup, spec, self.cases).passes
            self.runs += self.cost

    def ask_new(self, score_id: str) -> None:
        """Ask for a lesson per failed case, as far as ask plus variant fit the budget."""
        known = {item.id for item in self.spec.experience}
        for failure in self.baseline.failures[: self.config.specialists.score_max_new_lessons]:
            if not self._budget_left(1):
                self.deferred.append(f"new:{failure.case.id}")
                continue
            prompt = lesson_request(
                failure.case, failure.output, failure.diff, self.config.language
            )
            answer = self.setup.agent.ask(prompt, self.setup.timeout)
            self.runs += 1
            text = parse_lesson(unfence(answer.output)) if answer.ok else None
            lesson = model_lesson(failure.case.id, text, score_id, self.now) if text else None
            if lesson is not None and lesson.id not in known and lesson.id not in self.new:
                self.new[lesson.id] = lesson
                self.variant(lesson, True)


def unfence(answer: str) -> str:
    """Drop exactly one surrounding code fence; the lesson filter judges the rest."""
    found = _FENCE.match(answer.strip())
    return found.group(1) if found else answer
