"""``wev exec`` in an execute run acts for a RUNNING task, whatever the caller names.

Regressions for the second independent pass: a read-only reviewer's limits were skipped by
omitting ``--task`` or naming another task, and the same reviewer could not run the test
suite, which is how a reviewer verifies.
"""

from __future__ import annotations

from typing import Any

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.contracts import Mode, TaskStatus
from wev_skills.core.errors import PermissionDenied

IMPL = {"id": "impl", "files": ["calc.py"], "agent_hint": "builder", "checks": ["make test"]}
AUDIT = {
    "id": "audit",
    "files": ["docs.md"],
    "agent_hint": "reviewer",
    "read_only": True,
    "checks": ["make test", "unit --quick"],
}
MAKEFILE = "test:\n\t@true\nlint:\n\t@true\n"


class BindingCase(OrchestratorCase):
    def setUp(self) -> None:
        super().setUp()
        (self.root / "Makefile").write_text(MAKEFILE, encoding="utf-8")

    def planned(self, *tasks: dict[str, Any], parallel: int = 3) -> None:
        self.start("Add sub and review it", files_touched_estimate=6, independent_subtasks=parallel)
        self.set_plan(*(tasks or (IMPL, AUDIT)))
        self.orch().next_tasks()

    def refused(self, argv: tuple[str, ...], task_id: str | None = None) -> PermissionDenied:
        with self.assertRaises(PermissionDenied) as caught:
            self.orch().exec_command(argv, task_id=task_id)
        return caught.exception

    def ran(self, argv: tuple[str, ...], task_id: str | None = None) -> dict[str, Any]:
        payload, code = self.orch().exec_command(argv, task_id=task_id)
        self.assertEqual(code, 0)
        result: dict[str, Any] = payload
        return result


class NoRunningTaskTests(BindingCase):
    def test_only_read_only_commands_are_accepted(self) -> None:
        self.planned()
        error = self.refused(("touch", "before.txt"))
        self.assertEqual(error.code, "exec_no_running_task")
        self.assertIn("No task is running", error.message)
        self.assertIn("wev task", error.details["next_step"])
        self.assertEqual(self.runner.commands(), [])
        self.assertEqual(self.ran(("ls",))["task_id"], "")
        self.assertEqual(self.ran(("git", "status"))["task_id"], "")

    def test_the_test_suite_is_not_read_only_either(self) -> None:
        self.planned()
        self.assertEqual(self.refused(("make", "test")).code, "exec_no_running_task")

    def test_after_the_last_task_is_verified_mutation_is_refused_again(self) -> None:
        self.planned(IMPL)
        self.orch().start_task("impl")
        self.verify("impl")
        self.assertEqual(self.status_of("impl"), TaskStatus.VERIFIED)
        self.assertEqual(self.refused(("touch", "after.txt")).code, "exec_no_running_task")

    def test_plan_mode_is_unchanged(self) -> None:
        self.start(mode=Mode.PLAN)
        self.assertEqual(self.ran(("ls",))["task_id"], "")
        self.assertEqual(self.refused(("touch", "x")).code, "permission_denied")


class NamedTaskTests(BindingCase):
    def test_a_task_that_is_not_running_is_refused_and_the_running_ones_are_named(self) -> None:
        self.planned()
        self.orch().start_task("audit")
        for named, status in (("impl", "ready"), ("ghost", "unknown")):
            with self.subTest(named=named):
                error = self.refused(("touch", "x.txt"), task_id=named)
                self.assertEqual(error.code, "exec_task_not_running")
                self.assertIn("audit", error.message)
                self.assertIn(status, error.message)
                self.assertEqual(error.details["running"], ["audit"])
        self.assertEqual(self.refused(("ls",), task_id="impl").code, "exec_task_not_running")
        self.assertEqual(self.runner.commands(), [("make", "test"), ("unit", "--quick")])

    def test_a_verified_task_is_refused(self) -> None:
        self.planned(IMPL, {"id": "other", "files": ["o.txt"], "agent_hint": "fixer"})
        self.orch().start_task("impl")
        self.orch().start_task("other")
        self.verify("impl")
        error = self.refused(("touch", "x.txt"), task_id="impl")
        self.assertEqual(error.code, "exec_task_not_running")
        self.assertIn("verified", error.message)
        self.assertEqual(error.details["running"], ["other"])

    def test_the_only_running_task_is_used_and_the_output_says_so(self) -> None:
        self.planned()
        self.orch().start_task("impl")
        payload = self.ran(("touch", "x.txt"))
        self.assertEqual(payload["task_id"], "impl")
        self.assertTrue(payload["task_implied"])
        self.assertIn("impl", payload["task_note"])
        named = self.ran(("touch", "y.txt"), task_id="impl")
        self.assertEqual((named["task_id"], named["task_implied"]), ("impl", False))
        self.assertNotIn("task_note", named)

    def test_with_several_running_the_task_must_be_named(self) -> None:
        self.planned()
        self.orch().start_task("impl")
        self.orch().start_task("audit")
        error = self.refused(("touch", "x.txt"))
        self.assertEqual(error.code, "exec_task_required")
        self.assertIn("impl", error.message)
        self.assertIn("audit", error.message)
        self.assertEqual(self.ran(("touch", "x.txt"), task_id="impl")["task_id"], "impl")
        self.assertEqual(self.ran(("ls",))["task_id"], "")


class ReadOnlyAgentTests(BindingCase):
    """The reproduction: the reviewer's task is the only one running."""

    def reviewing(self) -> None:
        self.planned()
        self.orch().start_task("audit")

    def test_the_reviewer_cannot_mutate_by_omitting_or_changing_the_task(self) -> None:
        self.reviewing()
        for task_id in (None, "audit"):
            for argv in (("touch", "x.txt"), ("cp", "calc.py", "y.py"), ("git", "stash")):
                with self.subTest(task_id=task_id, argv=argv):
                    self.assertEqual(self.refused(argv, task_id).code, "agent_read_only")
        self.assertEqual(self.refused(("touch", "x.txt"), "impl").code, "exec_task_not_running")
        self.assertNotIn(("touch", "x.txt"), self.runner.commands())

    def test_the_reviewer_reads(self) -> None:
        self.reviewing()
        self.assertEqual(self.ran(("cat", "calc.py"))["task_id"], "audit")
        self.assertEqual(self.ran(("git", "diff"), "audit")["task_id"], "audit")

    def test_the_reviewer_runs_the_tasks_declared_checks(self) -> None:
        self.reviewing()
        for argv in (("make", "test"), ("unit", "--quick")):
            with self.subTest(argv=argv):
                self.assertEqual(self.ran(argv, "audit")["record"]["status"], "passed")

    def test_the_reviewer_runs_the_discovered_checks_of_the_repository(self) -> None:
        self.reviewing()
        self.assertEqual(self.ran(("make", "lint"), "audit")["record"]["status"], "passed")

    def test_the_match_is_on_the_exact_argv(self) -> None:
        self.reviewing()
        for argv in (
            ("make", "test", "install"),
            ("make",),
            ("make", "deploy"),
            ("unit",),
            ("unit", "--quick", "--write"),
            ("python3", "-m", "unittest", "-q", "test_calc"),
            ("sh", "-c", "make test"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(self.refused(argv, "audit").code, "agent_read_only")

    def test_a_check_that_needs_approval_still_needs_it(self) -> None:
        risky = {**AUDIT, "checks": ["rm -rf build"]}
        self.planned(IMPL, risky)
        self.orch().start_task("audit")
        with self.assertRaises(Exception) as caught:
            self.orch().exec_command(("rm", "-rf", "build"), task_id="audit")
        self.assertEqual(getattr(caught.exception, "code", ""), "approval_required")

    def test_an_agent_that_may_mutate_is_not_limited(self) -> None:
        self.planned()
        self.orch().start_task("impl")
        self.assertEqual(self.ran(("touch", "x.txt"), "impl")["task_id"], "impl")
