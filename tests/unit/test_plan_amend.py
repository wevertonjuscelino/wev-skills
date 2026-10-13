"""A plan change to a task that has started is refused unless it is a recorded amendment.

Regression for the second independent pass: after a failed check, ``plan set`` replaced the
task's criteria and checks with trivial ones and the run was reported complete.
"""

from __future__ import annotations

from typing import Any

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.contracts import TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.core.report_markdown import render_markdown

HARD = {
    "id": "notes",
    "files": ["NOTES.md"],
    "acceptance_criteria": ["NOTES.md exists", "NOTES.md mentions sub"],
    "checks": ["test -f NOTES.md", {"command": "grep -q sub NOTES.md", "criteria": [1]}],
}
EASY = {
    "id": "notes",
    "files": ["NOTES.md"],
    "acceptance_criteria": ["work is done"],
    "checks": ["make test"],
}
OTHER = {"id": "later", "files": ["later.txt"], "acceptance_criteria": ["later"]}


class PlanAmendCase(OrchestratorCase):
    def begin(self, *tasks: dict[str, Any]) -> None:
        self.start("Add notes and helpers", files_touched_estimate=6, independent_subtasks=2)
        self.set_plan(*(tasks or (HARD, OTHER)))

    def started(self) -> None:
        self.begin()
        self.runner.on(("test", "-f", "NOTES.md"), exit_code=1)
        self.runner.on(("grep", "-q", "sub", "NOTES.md"), exit_code=1)
        self.orch().next_tasks()
        self.orch().start_task("notes")
        self.runner.edit("scratch")

    def amend(self, *tasks: dict[str, Any], reason: str | None = "the criterion was wrong") -> Any:
        return self.orch().set_plan(self.plan_file(*tasks), amend_reason=reason)


class RefusalTests(PlanAmendCase):
    def test_the_reproduction_is_refused(self) -> None:
        self.started()
        self.assertFalse(self.orch().check_task("notes")["all_met"])
        with self.assertRaises(ValidationError) as caught:
            self.set_plan(EASY, OTHER)
        error = caught.exception
        self.assertEqual(error.code, "plan_amendment_required")
        self.assertIn("notes", error.message)
        self.assertIn("--amend --reason", error.details["next_step"])
        changed = error.details["changes"]["notes"]
        self.assertEqual(sorted(changed), ["acceptance_criteria", "check_links", "checks"])
        plan = self.state().plan
        self.assertEqual(plan.tasks[0].acceptance_criteria, tuple(HARD["acceptance_criteria"]))
        self.assertNotIn("plan.amended", self.audit_types())

    def test_each_guarded_field_is_refused_on_its_own(self) -> None:
        self.started()
        for field, value in (
            ("acceptance_criteria", ["NOTES.md exists", "NOTES.md mentions add"]),
            ("checks", ["test -f NOTES.md"]),
            ("read_only", True),
            ("risk", "medium"),
            ("files", ["OTHER.md"]),
        ):
            with self.subTest(field=field), self.assertRaises(ValidationError) as caught:
                self.set_plan({**HARD, field: value}, OTHER)
            self.assertEqual(caught.exception.code, "plan_amendment_required")

    def test_a_finished_task_is_guarded_too(self) -> None:
        self.begin(EASY, OTHER)
        self.orch().next_tasks()
        self.orch().start_task("notes")
        self.verify("notes")
        self.assertEqual(self.status_of("notes"), TaskStatus.VERIFIED)
        with self.assertRaises(ValidationError) as caught:
            self.set_plan({**EASY, "acceptance_criteria": ["something else"]}, OTHER)
        self.assertEqual(caught.exception.code, "plan_amendment_required")

    def test_a_reason_is_required(self) -> None:
        self.started()
        for reason in ("", "   "):
            with self.subTest(reason=reason), self.assertRaises(ValidationError) as caught:
                self.amend(EASY, OTHER, reason=reason)
            self.assertEqual(caught.exception.code, "amend_reason_required")


class AllowedChangeTests(PlanAmendCase):
    def test_unstarted_tasks_and_new_tasks_change_freely(self) -> None:
        self.started()
        changed = {**OTHER, "acceptance_criteria": ["changed"], "checks": ["make test"]}
        added = {"id": "extra", "files": ["extra.txt"]}
        out = self.set_plan(HARD, changed, added)
        self.assertEqual([row["id"] for row in out["tasks"]], ["notes", "later", "extra"])
        self.assertEqual(self.state().plan_amendments, ())

    def test_unguarded_fields_of_a_started_task_change_freely(self) -> None:
        self.started()
        self.set_plan({**HARD, "title": "Write the notes", "objective": "reworded"}, OTHER)
        self.assertEqual(self.state().plan.tasks[0].title, "Write the notes")

    def test_the_same_plan_again_is_not_an_amendment(self) -> None:
        self.started()
        self.set_plan(HARD, OTHER)
        self.amend(HARD, OTHER)
        self.assertEqual(self.state().plan_amendments, ())


class AmendmentTests(PlanAmendCase):
    def test_an_amendment_is_recorded_with_before_and_after(self) -> None:
        self.started()
        self.amend(EASY, OTHER)
        state = self.state()
        (amendment,) = state.plan_amendments
        self.assertEqual(
            (amendment.task_id, amendment.reason), ("notes", "the criterion was wrong")
        )
        by_field = {change.field: change for change in amendment.changes}
        criteria = by_field["acceptance_criteria"]
        self.assertEqual(criteria.before, ("NOTES.md exists", "NOTES.md mentions sub"))
        self.assertEqual(criteria.after, ("work is done",))
        self.assertEqual(by_field["checks"].after, ("make test",))
        self.assertIn("plan.amended", self.audit_types())
        decisions = [d for d in state.decisions if d.source == "plan-amend"]
        self.assertEqual(len(decisions), 1)
        self.assertIn("notes", decisions[0].decision)
        self.assertIn("the criterion was wrong", decisions[0].reasons)

    def test_an_amendment_resets_a_running_tasks_verification(self) -> None:
        self.begin(EASY, OTHER)
        self.orch().next_tasks()
        self.orch().start_task("notes")
        self.runner.edit("work")
        self.assertTrue(self.orch().check_task("notes")["all_met"])
        self.amend({**EASY, "acceptance_criteria": ["something else"]}, OTHER)
        with self.assertRaises(ValidationError) as caught:
            self.orch().record_task("notes", TaskStatus.VERIFIED, "done")
        self.assertEqual(caught.exception.code, "verification_required")
        self.assertIn("wev task check notes", self.orch().status()["next_step"])

    def test_an_amendment_sends_a_verified_task_back(self) -> None:
        self.begin(EASY, OTHER)
        self.orch().next_tasks()
        self.orch().start_task("notes")
        self.verify("notes")
        self.amend({**EASY, "acceptance_criteria": ["something else"]}, OTHER)
        self.assertEqual(self.status_of("notes"), TaskStatus.PENDING)
        self.assertNotEqual(self.orch().report()["status"], "complete")

    def test_the_report_lists_every_amendment(self) -> None:
        self.started()
        self.amend(EASY, OTHER)
        self.amend({**EASY, "files": ["NOTES.md", "README.md"]}, OTHER, reason="one more file")
        report = self.orch().report()
        rows = report["plan_amendments"]
        self.assertEqual(
            [row["reason"] for row in rows], ["the criterion was wrong", "one more file"]
        )
        self.assertEqual(rows[1]["changes"][0]["field"], "files")
        self.assertEqual(rows[1]["changes"][0]["before"], ["NOTES.md"])
        self.assertEqual(rows[1]["changes"][0]["after"], ["NOTES.md", "README.md"])
        for lang, heading in (("en", "## Plan amendments"), ("pt-BR", "## Alterações do plano")):
            with self.subTest(lang=lang):
                text = render_markdown(self.orch().report(lang), lang)
                self.assertIn(heading, text)
                self.assertIn("NOTES.md mentions sub", text)
                self.assertIn("work is done", text)
                self.assertIn("one more file", text)

    def test_the_reproduction_no_longer_ends_complete(self) -> None:
        self.started()
        self.orch().check_task("notes")
        with self.assertRaises(ValidationError):
            self.set_plan(EASY)
        with self.assertRaises(ValidationError):
            self.orch().record_task("notes", TaskStatus.VERIFIED, "done")
        self.assertNotEqual(self.orch().report()["status"], "complete")
