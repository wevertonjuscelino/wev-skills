"""Learning proposes lessons; only the person at a terminal accepts or retires one."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.fixtures.operator_prompt import ScriptedPrompt, at_terminal, no_terminal
from tests.unit.test_specialists_learning import recorded
from wev_skills import cli, i18n
from wev_skills.agents import learning, project
from wev_skills.agents.experience import (
    ACTIVE,
    PROPOSED,
    RETIRED,
    STALE,
    AuthoredText,
    active_lessons,
    rendered_lessons,
)
from wev_skills.commands import _human
from wev_skills.config import parse_config
from wev_skills.core.errors import NotFound, StateConflict, ValidationError

AGENT = "project-test"


def derived() -> tuple[Any, ...]:
    return learning.derive((recorded("run-1"),), AGENT)


class ReconcileTests(unittest.TestCase):
    def test_a_new_lesson_is_proposed_and_not_shown(self) -> None:
        found = learning.reconcile((), derived())
        pairs = [(item.status, item.accepted_by) for item in found]
        self.assertEqual(pairs, [(PROPOSED, "engine")])
        self.assertEqual(rendered_lessons(found, 12), ())

    def test_a_lesson_the_engine_accepted_before_needs_acceptance_again(self) -> None:
        legacy = replace(derived()[0], status=ACTIVE, accepted_by="engine")
        self.assertEqual(learning.reconcile((legacy,), derived())[0].status, PROPOSED)

    def test_a_human_acceptance_survives_relearning(self) -> None:
        accepted = replace(derived()[0], status=ACTIVE, accepted_by="ana")
        again = learning.reconcile((accepted,), derived())[0]
        self.assertEqual((again.status, again.accepted_by), (ACTIVE, "ana"))
        stale = replace(derived()[0], status=STALE)
        later = learning.reconcile((accepted,), (stale,))[0]
        self.assertEqual((later.status, later.accepted_by), (STALE, "ana"))

    def test_a_retirement_survives_relearning(self) -> None:
        retired = replace(derived()[0], status=RETIRED, accepted_by="ana")
        self.assertEqual(learning.reconcile((retired,), derived())[0].status, RETIRED)

    def test_a_lesson_the_engine_retired_before_is_proposed_again(self) -> None:
        legacy = replace(derived()[0], status=RETIRED, accepted_by="engine")
        self.assertEqual(learning.reconcile((legacy,), derived())[0].status, PROPOSED)

    def test_the_cap_drops_a_proposal_before_a_decision(self) -> None:
        decided = replace(derived()[0], status=RETIRED, accepted_by="ana")
        louder = replace(derived()[0], id="lesson-new", key=("check", "x"), confirmations=99)
        kept = learning.reconcile((decided,), (*derived(), louder), maximum=1)
        self.assertEqual([(item.id, item.status) for item in kept], [(decided.id, RETIRED)])

    def test_a_person_decision_survives_when_not_derived_again(self) -> None:
        retired = replace(derived()[0], status=RETIRED, accepted_by="ana")
        kept = learning.reconcile((retired,), ())
        self.assertEqual([(item.id, item.status) for item in kept], [(retired.id, RETIRED)])
        again = learning.reconcile(kept, derived())
        self.assertEqual([(item.status, item.accepted_by) for item in again], [(RETIRED, "ana")])

    def test_a_score_decision_not_derived_again_is_dropped(self) -> None:
        scored = replace(derived()[0], status=ACTIVE, accepted_by="score")
        self.assertEqual(learning.reconcile((scored,), ()), ())

    def test_the_cap_drops_a_score_decision_before_a_person_decision(self) -> None:
        person = replace(derived()[0], status=RETIRED, accepted_by="ana")
        louder = replace(derived()[0], id="lesson-s", key=("check", "x"), confirmations=99)
        scored = replace(louder, accepted_by="score")
        kept = learning.reconcile((person, scored), (*derived(), louder), maximum=1)
        self.assertEqual([item.id for item in kept], [person.id])

    def test_a_stored_active_lesson_only_the_engine_accepted_is_not_shown(self) -> None:
        legacy = replace(derived()[0], status=ACTIVE, accepted_by="engine")
        accepted = replace(legacy, accepted_by="ana")
        self.assertEqual(active_lessons((legacy,)), [])
        self.assertEqual(active_lessons((accepted,)), [accepted])


class SpecialistCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        (self.root / "wev.json").write_text(json.dumps({"state_dir": "state"}), encoding="utf-8")
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        self.config = parse_config("wev.json")
        spec = project.create(self.root, self.config, AGENT, "senior-engineer", ())
        self.spec = spec
        self.store(learning.reconcile((), derived())[0])

    def store(self, lesson: Any) -> None:
        self.lesson = lesson
        path = self.root / "wev-specialists" / f"{AGENT}.json"
        data = replace(self.spec, experience=(lesson,)).to_dict()
        path.write_text(json.dumps(data), encoding="utf-8")

    def status(self) -> str:
        found = project.list_specs(self.root, self.config)[0].experience[0]
        return found.status

    def run_cli(self, *argv: str, prompt: ScriptedPrompt | None = None) -> tuple[int, Any, Any]:
        out, err = io.StringIO(), io.StringIO()
        operator = at_terminal(prompt) if prompt is not None else no_terminal()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            i18n.use_language("en"),
            operator,
        ):
            code = cli.main(["--config", "wev.json", *argv])
        stdout = json.loads(out.getvalue()) if out.getvalue().strip() else None
        stderr = json.loads(err.getvalue())["error"] if err.getvalue().strip() else None
        return code, stdout, stderr

    def audit_types(self) -> list[str]:
        path = self.root / "state" / "audit.jsonl"
        return [json.loads(line)["type"] for line in path.read_text().splitlines()]


class ProjectDecisionTests(SpecialistCase):
    def test_accept_activates_a_proposed_lesson_under_the_operator_name(self) -> None:
        spec = project.accept_lesson(self.root, self.config, (AGENT, self.lesson.id), "ana")
        accepted = spec.experience[0]
        self.assertEqual((accepted.status, accepted.accepted_by), (ACTIVE, "ana"))
        with self.assertRaises(ValidationError):
            project.accept_lesson(self.root, self.config, (AGENT, self.lesson.id), "ana")

    def test_retire_holds_and_an_unknown_lesson_is_not_found(self) -> None:
        project.retire_lesson(self.root, self.config, (AGENT, self.lesson.id), "ana")
        self.assertEqual(self.status(), RETIRED)
        with self.assertRaises(ValidationError):
            project.retire_lesson(self.root, self.config, (AGENT, self.lesson.id), "ana")
        with self.assertRaises(NotFound):
            project.accept_lesson(self.root, self.config, (AGENT, "lesson-missing"), "ana")

    def test_the_proposer_name_cannot_be_recorded_as_an_operator(self) -> None:
        with self.assertRaises(ValidationError):
            project.accept_lesson(self.root, self.config, (AGENT, self.lesson.id), "engine")
        self.assertEqual(self.status(), PROPOSED)

    def test_a_lesson_that_changed_after_it_was_shown_is_not_decided(self) -> None:
        shown = replace(self.lesson, confirmations=self.lesson.confirmations + 1)
        with self.assertRaises(StateConflict):
            project.accept_lesson(self.root, self.config, (AGENT, self.lesson.id), "ana", shown)
        self.assertEqual(self.status(), PROPOSED)

    def test_a_failed_record_leaves_no_decision(self) -> None:
        def fail() -> None:
            raise OSError("audit unavailable")

        ids = (AGENT, self.lesson.id)
        with self.assertRaises(OSError):
            project.accept_lesson(self.root, self.config, ids, "ana", self.lesson, fail)
        self.assertEqual(self.status(), PROPOSED)


class CommandTests(SpecialistCase):
    def test_without_a_terminal_accept_is_refused_and_audited(self) -> None:
        code, _, err = self.run_cli("specialists", "accept", AGENT, self.lesson.id)
        self.assertEqual((code, err["code"]), (3, "human_required"))
        self.assertIn("ask the human", err["message"])
        self.assertEqual(self.status(), PROPOSED)
        self.assertIn("specialists.accept_refused", self.audit_types())

    def test_a_wrong_word_changes_nothing(self) -> None:
        prompt = ScriptedPrompt(answer="nope")
        code, _, err = self.run_cli("specialists", "retire", AGENT, self.lesson.id, prompt=prompt)
        self.assertEqual((code, err["code"]), (3, "confirmation_mismatch"))
        self.assertEqual(self.status(), PROPOSED)

    def test_the_operator_sees_the_lesson_and_the_decision_is_recorded(self) -> None:
        prompt = ScriptedPrompt()
        code, out, err = self.run_cli("specialists", "accept", AGENT, self.lesson.id, prompt=prompt)
        self.assertEqual((code, err), (0, None))
        self.assertIn(self.lesson.id, prompt.shown[0])
        self.assertIn(self.lesson.evidence.run_id, prompt.shown[0])
        self.assertEqual(out["operator"], _human.operator_name())
        self.assertEqual(self.status(), ACTIVE)
        self.assertIn("specialists.accept", self.audit_types())
        code, _, _ = self.run_cli("specialists", "retire", AGENT, self.lesson.id, prompt=prompt)
        self.assertEqual((code, self.status()), (0, RETIRED))

    def test_the_prompt_shows_the_full_text_and_the_note_and_the_audit_has_the_terminal(
        self,
    ) -> None:
        authored = (AuthoredText("review summary", "a" * 239 + "?"),)
        changed = replace(self.lesson, text="t" * 299 + "!", note="watch the flaky step")
        self.store(replace(changed, contains_authored_text=True, authored=authored))
        prompt = ScriptedPrompt()
        code, _, _ = self.run_cli("specialists", "accept", AGENT, self.lesson.id, prompt=prompt)
        self.assertEqual(code, 0)
        self.assertIn("t" * 299 + "!", prompt.shown[0])
        self.assertIn("watch the flaky step", prompt.shown[0])
        self.assertIn("review summary: " + "a" * 239 + "?", prompt.shown[0])
        path = self.root / "state" / "audit.jsonl"
        events = [json.loads(line) for line in path.read_text().splitlines()]
        accepted = [event for event in events if event["type"] == "specialists.accept"]
        self.assertEqual(accepted[0]["data"]["terminal"], "/dev/ttys-test")

    def test_a_missing_lesson_is_refused_before_any_prompt(self) -> None:
        prompt = ScriptedPrompt()
        code, _, err = self.run_cli("specialists", "accept", AGENT, "lesson-x", prompt=prompt)
        self.assertEqual((code, err["code"]), (7, "lesson_not_found"))
        self.assertEqual(prompt.shown, [])


if __name__ == "__main__":
    unittest.main()
