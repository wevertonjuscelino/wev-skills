"""A score run may add model lessons and accept or retire lessons as `score`; a person's
retirement stays final."""

from __future__ import annotations

from dataclasses import replace

from tests.unit.test_lesson_acceptance import AGENT, SpecialistCase, derived
from wev_skills.agents import learning, project
from wev_skills.agents.experience import ACTIVE, PROPOSED, RETIRED, SCORER
from wev_skills.agents.project import ScoreDecisions
from wev_skills.core.errors import StateConflict, ValidationError

NOW = "2026-10-22T12:00:00Z"


class ScoreDecisionTests(SpecialistCase):
    def stored(self) -> tuple[object, ...]:
        return project.list_specs(self.root, self.config)[0].experience

    def score(self, decisions: ScoreDecisions, seen: object = None, record: object = None) -> None:
        project.record_scores(
            self.root,
            self.config,
            AGENT,
            self.stored() if seen is None else seen,  # type: ignore[arg-type]
            decisions,
            record or (lambda: None),  # type: ignore[arg-type]
        )

    def test_score_accepts_proposed(self) -> None:
        self.score(ScoreDecisions(accepted=(self.lesson.id,)))
        found = self.stored()[0]
        self.assertEqual((found.status, found.accepted_by), (ACTIVE, SCORER))  # type: ignore[attr-defined]

    def test_score_retired_returns_proposed_after_learn(self) -> None:
        self.score(ScoreDecisions(retired=(self.lesson.id,)))
        self.assertEqual(self.stored()[0].status, RETIRED)  # type: ignore[attr-defined]
        back = learning.reconcile(self.stored(), derived())[0]  # type: ignore[arg-type]
        self.assertEqual((back.status, back.accepted_by), (PROPOSED, "engine"))

    def test_person_retired_never_changes(self) -> None:
        self.store(replace(self.lesson, status=RETIRED, accepted_by="alice"))
        self.score(ScoreDecisions(accepted=(self.lesson.id,)))
        self.score(ScoreDecisions(retired=(self.lesson.id,)))
        found = self.stored()[0]
        self.assertEqual((found.status, found.accepted_by), (RETIRED, "alice"))  # type: ignore[attr-defined]

    def test_model_lesson_survives_relearning(self) -> None:
        model = learning.model_lesson("case-1", "check the diff first", "score-1", NOW)
        self.score(ScoreDecisions(new=(model,)))
        self.score(ScoreDecisions(accepted=(model.id,)))
        kept = learning.reconcile(self.stored(), ())  # type: ignore[arg-type]
        self.assertEqual(
            [(i.id, i.status, i.accepted_by) for i in kept], [(model.id, ACTIVE, SCORER)]
        )

    def test_changed_lessons_refuse(self) -> None:
        before = (self.root / "wev-specialists" / f"{AGENT}.json").read_text()
        stale = (replace(self.lesson, confirmations=9),)
        with self.assertRaises(StateConflict) as caught:
            self.score(ScoreDecisions(accepted=(self.lesson.id,)), seen=stale)
        self.assertEqual(caught.exception.code, "lessons_changed")
        self.assertEqual((self.root / "wev-specialists" / f"{AGENT}.json").read_text(), before)

    def test_audit_runs_before_write(self) -> None:
        before = (self.root / "wev-specialists" / f"{AGENT}.json").read_text()

        def fail() -> None:
            raise OSError("audit unavailable")

        with self.assertRaises(OSError):
            self.score(ScoreDecisions(accepted=(self.lesson.id,)), record=fail)
        self.assertEqual((self.root / "wev-specialists" / f"{AGENT}.json").read_text(), before)

    def test_operator_name_score_is_reserved(self) -> None:
        with self.assertRaises(ValidationError):
            project.accept_lesson(self.root, self.config, (AGENT, self.lesson.id), SCORER)
        self.assertEqual(self.stored()[0].status, PROPOSED)  # type: ignore[attr-defined]
