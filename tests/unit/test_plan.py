from __future__ import annotations

import unittest

from wev_skills import schema
from wev_skills.core.contracts import Plan, PlanTask, TaskStatus
from wev_skills.core.errors import ValidationError


def task(tid: str, *deps: str, status: TaskStatus = TaskStatus.PENDING) -> PlanTask:
    return PlanTask(tid, tid.upper(), f"do {tid}", depends_on=deps, status=status)


class PlanValidationTests(unittest.TestCase):
    def test_valid_plan_has_no_problems(self) -> None:
        plan = Plan("o", (task("a"), task("b", "a"), task("c", "a", "b")))
        self.assertEqual(plan.problems(), [])
        plan.validate()

    def test_duplicate_ids_are_reported(self) -> None:
        plan = Plan("o", (task("a"), task("a")))
        self.assertIn("duplicate task id: a", plan.problems())
        with self.assertRaises(ValidationError) as ctx:
            plan.validate()
        self.assertEqual(ctx.exception.code, "invalid_plan")

    def test_unknown_dependency_is_reported(self) -> None:
        problems = Plan("o", (task("a", "ghost"),)).problems()
        self.assertEqual(problems, ["task a depends on unknown task ghost"])

    def test_cycle_is_reported(self) -> None:
        plan = Plan("o", (task("a", "c"), task("b", "a"), task("c", "b"), task("d")))
        problems = plan.problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("a, b, c", problems[0])
        self.assertNotIn("d", problems[0].split(":")[1])

    def test_self_dependency_is_a_cycle(self) -> None:
        self.assertTrue(any("cycle" in p for p in Plan("o", (task("a", "a"),)).problems()))


class ReadyTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = Plan("o", (task("a"), task("b", "a"), task("c"), task("d", "b", "c")))

    def ids(self, completed: tuple[str, ...]) -> list[str]:
        return [t.id for t in self.plan.ready_tasks(completed)]

    def test_roots_are_ready_first_in_plan_order(self) -> None:
        self.assertEqual(self.ids(()), ["a", "c"])

    def test_dependents_unlock_as_dependencies_complete(self) -> None:
        self.assertEqual(self.ids(("a",)), ["b", "c"])
        self.assertEqual(self.ids(("a", "b")), ["c"])
        self.assertEqual(self.ids(("a", "b", "c")), ["d"])

    def test_everything_done_leaves_nothing_ready(self) -> None:
        self.assertEqual(self.ids(("a", "b", "c", "d")), [])

    def test_non_runnable_statuses_are_skipped(self) -> None:
        plan = Plan("o", (task("a", status=TaskStatus.RUNNING), task("b", status=TaskStatus.READY)))
        self.assertEqual([t.id for t in plan.ready_tasks()], ["b"])

    def test_invalid_plan_cannot_be_scheduled(self) -> None:
        with self.assertRaises(ValidationError):
            Plan("o", (task("a", "b"), task("b", "a"))).ready_tasks()


class PlanSchemaTests(unittest.TestCase):
    def test_plan_dict_validates_against_plan_schema(self) -> None:
        plan = Plan("o", (task("a"), task("b", "a")))
        self.assertEqual(schema.validate(plan.to_dict(), schema.load("plan")), [])
        self.assertEqual(Plan.from_dict(plan.to_dict()), plan)

    def test_schema_rejects_bad_task(self) -> None:
        data = {"objective": "o", "tasks": [{"id": "bad id", "title": "t", "objective": ""}]}
        errs = schema.validate(data, schema.load("plan"))
        self.assertTrue(any(e.startswith("/tasks/0/id") for e in errs))


if __name__ == "__main__":
    unittest.main()
