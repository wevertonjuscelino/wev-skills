"""Intake: the bounded questions that turn a request into an objective brief."""

from __future__ import annotations

import unittest

from wev_skills import i18n
from wev_skills.core.errors import ValidationError
from wev_skills.intake import model
from wev_skills.intake.model import IntakeRecord

AT = "2026-10-13T00:00:00.000000Z"
REQUEST = "Add a CSV export to the reports page"


def filled(record: IntakeRecord, *names: str, source: str = "request") -> IntakeRecord:
    values = {
        "goal": ("A CSV export button on the reports page",),
        "done": ("make test passes", "the button downloads a file"),
        "scope": ("reports page only; billing is out",),
        "kind": ("feature",),
        "constraints": ("no new dependency",),
        "outcome": ("support stops exporting reports by hand",),
    }
    current = record
    for name in names:
        current = model.set_field(current, name, values[name], source)
    return current


class IntakeCase(unittest.TestCase):
    def setUp(self) -> None:
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)
        self.record = model.start(REQUEST, AT)


class StartAndSetTests(IntakeCase):
    def test_a_new_intake_misses_the_four_required_fields(self) -> None:
        self.assertEqual(model.missing(self.record), ("goal", "done", "scope", "kind"))
        self.assertEqual(self.record.rounds_used, 0)

    def test_an_empty_request_is_refused(self) -> None:
        for text in ("", "   \n"):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                model.start(text, AT)

    def test_setting_a_field_closes_it_and_does_not_change_the_argument(self) -> None:
        after = model.set_field(self.record, "goal", ("An export button",), "request")
        self.assertEqual(model.missing(after), ("done", "scope", "kind"))
        self.assertEqual(model.missing(self.record), ("goal", "done", "scope", "kind"))

    def test_bad_fields_sources_and_kinds_are_refused(self) -> None:
        bad = (
            ("priority", ("high",), "request"),
            ("goal", ("x",), "guess"),
            ("kind", ("party",), "request"),
            ("goal", (), "request"),
            ("goal", ("one", "two"), "request"),
            ("goal", ("  ",), "answer"),
        )
        for name, values, source in bad:
            with self.subTest(name=name, source=source), self.assertRaises(ValidationError):
                model.set_field(self.record, name, values, source)

    def test_done_keeps_every_criterion(self) -> None:
        after = filled(self.record, "done")
        self.assertEqual(
            model.value_of(after, "done"), ("make test passes", "the button downloads a file")
        )

    def test_text_is_cleaned_and_secrets_are_redacted(self) -> None:
        secret = "ghp_" + "a1B2c3D4e5" * 4
        after = model.set_field(
            self.record, "goal", (f"\x1b[31mexport\x1b[0m\nwith token {secret}",), "answer"
        )
        (text,) = model.value_of(after, "goal")
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\n", text)
        self.assertNotIn(secret, text)

    def test_an_assumption_without_a_value_gets_the_conservative_default(self) -> None:
        after = model.set_field(self.record, "scope", (), "assumption")
        (text,) = model.value_of(after, "scope")
        self.assertIn("only what the request names", text)
        kind = model.set_field(self.record, "kind", (), "assumption")
        self.assertEqual(model.value_of(kind, "kind"), ("investigation",))


class RoundTests(IntakeCase):
    def test_a_clear_request_leads_to_zero_questions_and_no_round(self) -> None:
        ready = filled(self.record, "goal", "done", "scope", "kind")
        after, asked = model.next_round(ready, 3)
        self.assertEqual(asked.questions, ())
        self.assertTrue(asked.complete)
        self.assertEqual(after.rounds_used, 0)

    def test_at_most_three_questions_one_per_missing_field(self) -> None:
        after, asked = model.next_round(self.record, 3)
        self.assertEqual([q.field for q in asked.questions], ["goal", "done", "scope"])
        self.assertFalse(asked.complete)
        self.assertEqual(after.rounds_used, 1)
        self.assertIn("CSV export", asked.questions[0].question)

    def test_the_question_carries_a_clean_bounded_part_of_the_request(self) -> None:
        hostile = model.start("\x1b[2Jdo it\nnow " + "y" * 900, AT)
        _, asked = model.next_round(hostile, 3)
        text = asked.questions[0].question
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\n", text)
        self.assertLess(len(text), 400)

    def test_a_fourth_round_is_impossible(self) -> None:
        record = self.record
        for expected in (1, 2, 3):
            record, asked = model.next_round(record, 3)
            self.assertEqual(record.rounds_used, expected)
            self.assertTrue(asked.questions)
        for _ in range(5):
            record, asked = model.next_round(record, 3)
            self.assertEqual(asked.questions, ())
            self.assertFalse(asked.complete)
            self.assertTrue(asked.rounds_exhausted)
            self.assertEqual(asked.must_assume, ("goal", "done", "scope", "kind"))
            self.assertEqual(record.rounds_used, 3)

    def test_the_bound_comes_from_the_limit_given(self) -> None:
        record, _ = model.next_round(self.record, 1)
        record, asked = model.next_round(record, 1)
        self.assertEqual((asked.questions, asked.rounds_exhausted), ((), True))
        self.assertEqual(record.rounds_used, 1)

    def test_answers_shrink_the_next_round(self) -> None:
        record, _ = model.next_round(self.record, 3)
        record = filled(record, "goal", "done", source="answer")
        record, asked = model.next_round(record, 3)
        self.assertEqual([q.field for q in asked.questions], ["scope", "kind"])


class FinishTests(IntakeCase):
    def test_finish_refuses_while_a_field_is_missing(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            model.finish(filled(self.record, "goal"))
        self.assertEqual(caught.exception.code, "intake_incomplete")
        self.assertEqual(caught.exception.details["missing"], ["done", "scope", "kind"])

    def test_the_brief_separates_assumptions_from_what_was_stated(self) -> None:
        record = filled(self.record, "goal", "done")
        record = filled(record, "kind", source="answer")
        record, _ = model.next_round(record, 3)
        record = model.set_field(record, "scope", (), "assumption")
        _, brief = model.finish(record)
        self.assertEqual(brief.goal, "A CSV export button on the reports page")
        self.assertEqual(brief.done, ("make test passes", "the button downloads a file"))
        self.assertEqual(brief.kind, "feature")
        self.assertEqual([item.field for item in brief.assumptions], ["scope"])
        self.assertEqual(brief.intake_rounds, 1)
        self.assertEqual(brief.constraints, "")
        self.assertEqual(brief.outcome, "")

    def test_the_outcome_is_optional_and_carried_into_the_brief(self) -> None:
        record = filled(self.record, "goal", "done", "scope", "kind")
        self.assertEqual(model.missing(record), ())
        _, brief = model.finish(filled(record, "outcome"))
        self.assertEqual(brief.outcome, "support stops exporting reports by hand")

    def test_an_assumed_outcome_gets_a_conservative_default(self) -> None:
        record = model.set_field(self.record, "outcome", (), "assumption")
        self.assertEqual(model.value_of(record, "outcome"), ("Deliver the stated goal only",))

    def test_a_finished_intake_cannot_be_changed(self) -> None:
        done, _ = model.finish(filled(self.record, "goal", "done", "scope", "kind"))
        with self.assertRaises(ValidationError):
            model.set_field(done, "goal", ("another",), "answer")

    def test_the_run_command_carries_the_objective_and_the_signals_of_the_kind(self) -> None:
        record = filled(self.record, "goal", "done")
        record = model.set_field(record, "kind", ("operations",), "request")
        record = model.set_field(record, "scope", (), "assumption")
        _, brief = model.finish(record)
        command = model.run_start_command(brief)
        self.assertTrue(command.startswith("wev run start --objective "))
        self.assertIn("'A CSV export button on the reports page'", command)
        self.assertIn("--from-intake", command)
        self.assertIn("--external", command)
        self.assertIn("--unknowns 1", command)
        plain = model.run_start_command(
            model.finish(filled(self.record, "goal", "done", "scope", "kind"))[1]
        )
        self.assertNotIn("--external", plain)
        self.assertNotIn("--unknowns", plain)


if __name__ == "__main__":
    unittest.main()
