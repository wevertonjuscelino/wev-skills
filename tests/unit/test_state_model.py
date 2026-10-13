from __future__ import annotations

import json
import os
import unittest

from wev_skills import schema
from wev_skills.core.contracts import (
    AttemptRecord,
    Classification,
    Complexity,
    Evidence,
    EvidenceLabel,
    Flow,
    Mode,
    Plan,
    PlanTask,
    RiskLevel,
    RunStatus,
    Strategy,
    TaskResult,
    TaskStatus,
)
from wev_skills.core.errors import ValidationError
from wev_skills.state import model
from wev_skills.state.model import (
    CommandLogEntry,
    DecisionRecord,
    Phase,
    RepoSnapshot,
    RunState,
    TaskRecord,
)

AT = "2026-10-13T12:00:00.000000Z"
PLAN = Plan(
    "ship",
    (
        PlanTask("a", "first", "do a"),
        PlanTask("b", "second", "do b", depends_on=("a",)),
    ),
)


def new_state(**overrides: object) -> RunState:
    fields = {
        "run_id": "run-1",
        "objective": "ship",
        "mode": Mode.EXECUTE,
        "created_at": AT,
        "updated_at": AT,
        **overrides,
    }
    return RunState(**fields)  # type: ignore[arg-type]


def planned() -> RunState:
    return model.with_plan(new_state(), PLAN)


def verified(state: RunState, task_id: str) -> RunState:
    running = model.with_task_status(state, task_id, TaskStatus.RUNNING, AT)
    return model.with_task_status(running, task_id, TaskStatus.VERIFIED, AT)


def full_state() -> RunState:
    state = verified(planned(), "a")
    state = model.with_classification(
        state, Classification(Complexity.SIMPLE, RiskLevel.LOW, 0.2, False, ("r",), "local")
    )
    state = model.with_strategy(state, Strategy(Flow.PLANNED, True, False, False, 1, 3, ("s",)))
    state = model.with_attempt(state, AttemptRecord("a", 1, TaskStatus.VERIFIED, "m"))
    state = model.with_task_status(state, "b", TaskStatus.RUNNING, AT, agent_id="dev", model="m")
    evidence = Evidence("command", "tests pass", "logs/1.txt", 0, EvidenceLabel.TESTED)
    result = TaskResult("b", TaskStatus.PARTIAL, "half", (evidence,), ("x.py",), ("needs key",))
    state = model.with_result(state, result, AT)
    state = model.with_decision(state, DecisionRecord(AT, Phase.DECIDE, "go", ("ok",), "local"))
    state = model.with_command(
        state,
        CommandLogEntry(AT, "b", ("make", "test"), "/repo", 0, 12, RunStatus.PASSED, "o", "e"),
    )
    state = model.with_pending_approval(state, "apr-1")
    state = model.with_next_step(state, "retry b")
    state = model.with_repo(state, RepoSnapshot("/repo", "main", "abc", ("x.py",)))
    state = model.with_discovery(state, "checks", {"test": ["make", "test"]})
    state = model.with_guard_event(state, {"kind": "repeat", "count": 3})
    return model.with_phase(state, Phase.EXECUTE)


class RoundTripTests(unittest.TestCase):
    def test_new_state_defaults(self) -> None:
        state = new_state()
        self.assertEqual((state.schema_version, state.revision, state.phase), (1, 1, Phase.REQUEST))
        self.assertEqual(dict(state.tasks), {})

    def test_full_state_round_trips_through_json(self) -> None:
        state = full_state()
        data = json.loads(json.dumps(state.to_dict()))
        self.assertEqual(RunState.from_dict(data), state)

    def test_full_state_matches_schema(self) -> None:
        self.assertEqual(schema.validate(full_state().to_dict(), schema.load("state")), [])
        self.assertEqual(schema.validate(new_state().to_dict(), schema.load("state")), [])

    def test_schema_rejects_wrong_version_unknown_key_and_bad_status(self) -> None:
        spec = schema.load("state")
        base = full_state().to_dict()
        self.assertTrue(schema.validate({**base, "schema_version": 2}, spec))
        self.assertTrue(schema.validate({**base, "extra": 1}, spec))
        broken = {**base, "tasks": {"a": {**base["tasks"]["a"], "status": "done"}}}
        self.assertTrue(schema.validate(broken, spec))

    def test_schema_field_set_equals_dataclass_fields(self) -> None:
        spec = schema.load("state")
        self.assertEqual(set(spec["properties"]), set(new_state().to_dict()))
        optional = {"remote_runs", "plan_amendments"}  # absent in states written before them
        self.assertEqual(set(spec["required"]), set(spec["properties"]) - optional)

    def test_from_dict_rejects_unknown_task_field_and_wrong_version(self) -> None:
        data = full_state().to_dict()
        data["tasks"]["a"]["surprise"] = 1
        with self.assertRaises(ValidationError):
            RunState.from_dict(data)
        with self.assertRaises(ValidationError) as caught:
            new_state(schema_version=2)
        self.assertEqual(caught.exception.code, "state_version_unsupported")

    def test_invalid_run_ids_are_rejected(self) -> None:
        for bad in ("", ".", "..", "a/b", "a\\b", "../x", ".hidden", "a b", "x" * 65):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                new_state(run_id=bad)


class ImmutabilityTests(unittest.TestCase):
    def test_helpers_return_new_state_and_leave_the_original(self) -> None:
        state = planned()
        changed = model.with_task_status(state, "a", TaskStatus.RUNNING, AT)
        self.assertIsNot(changed, state)
        self.assertEqual(state.tasks["a"].status, TaskStatus.PENDING)
        self.assertEqual(changed.tasks["a"].status, TaskStatus.RUNNING)
        self.assertEqual(changed.tasks["a"].started_at, AT)

    def test_mappings_are_read_only_and_arguments_are_copied(self) -> None:
        facts = {"checks": ["make test"]}
        event = {"kind": "loop", "detail": {"n": 1}}
        state = model.with_guard_event(model.with_discovery(new_state(), "facts", facts), event)
        facts["checks"].append("changed later")
        event["detail"]["n"] = 99
        self.assertEqual(state.discovery["facts"], {"checks": ["make test"]})
        self.assertEqual(state.guard_events[0]["detail"], {"n": 1})
        with self.assertRaises(TypeError):
            state.discovery["x"] = 1  # type: ignore[index]
        with self.assertRaises(TypeError):
            state.tasks["z"] = TaskRecord()  # type: ignore[index]

    def test_to_dict_does_not_expose_internal_state(self) -> None:
        state = model.with_discovery(new_state(), "facts", {"n": [1]})
        state.to_dict()["discovery"]["facts"]["n"].append(2)
        self.assertEqual(state.discovery["facts"], {"n": [1]})

    def test_guard_events_are_stored_uninterpreted_in_order(self) -> None:
        state = model.with_guard_event(new_state(), {"anything": [1, {"deep": None}]})
        state = model.with_guard_event(state, {"second": True})
        self.assertEqual(
            state.to_dict()["guard_events"], [{"anything": [1, {"deep": None}]}, {"second": True}]
        )

    def test_blockers_and_approvals_are_deduplicated_and_removable(self) -> None:
        state = model.with_blocker(model.with_blocker(new_state(), "no key"), "no key")
        self.assertEqual(state.blockers, ("no key",))
        self.assertEqual(model.without_blocker(state, "no key").blockers, ())
        state = model.with_pending_approval(model.with_pending_approval(state, "a1"), "a1")
        self.assertEqual(state.pending_approvals, ("a1",))
        self.assertEqual(model.without_pending_approval(state, "a1").pending_approvals, ())

    def test_with_phase_accepts_strings_and_rejects_unknown(self) -> None:
        self.assertEqual(model.with_phase(new_state(), "verify").phase, Phase.VERIFY)
        with self.assertRaises(ValidationError):
            model.with_phase(new_state(), "celebrate")


class TransitionTests(unittest.TestCase):
    def test_with_plan_registers_pending_tasks_and_keeps_existing_records(self) -> None:
        state = verified(planned(), "a")
        bigger = Plan("ship", (*PLAN.tasks, PlanTask("c", "third", "do c")))
        replanned = model.with_plan(state, bigger)
        self.assertEqual(replanned.tasks["a"].status, TaskStatus.VERIFIED)
        self.assertEqual(replanned.tasks["c"].status, TaskStatus.PENDING)

    def test_with_plan_rejects_invalid_plan(self) -> None:
        cyclic = Plan("x", (PlanTask("a", "t", "o", depends_on=("a",)),))
        with self.assertRaises(ValidationError):
            model.with_plan(new_state(), cyclic)

    def test_plan_status_cannot_smuggle_a_verified_task(self) -> None:
        plan = Plan("x", (PlanTask("a", "t", "o", status=TaskStatus.VERIFIED),))
        self.assertEqual(model.with_plan(new_state(), plan).tasks["a"].status, TaskStatus.PENDING)

    def test_verified_cannot_return_to_running_without_reopen(self) -> None:
        state = verified(planned(), "a")
        with self.assertRaises(ValidationError) as caught:
            model.with_task_status(state, "a", TaskStatus.RUNNING, AT)
        self.assertEqual(caught.exception.code, "illegal_transition")
        reopened = model.reopen(state, "a", AT, "review found a bug")
        self.assertEqual(reopened.tasks["a"].status, TaskStatus.PENDING)
        self.assertEqual(reopened.decisions[-1].source, "reopen")
        self.assertEqual(reopened.decisions[-1].reasons, ("review found a bug",))
        again = model.with_task_status(reopened, "a", TaskStatus.RUNNING, AT)
        self.assertEqual(again.tasks["a"].status, TaskStatus.RUNNING)

    def test_reopen_requires_reason_keeps_attempts_and_clears_result(self) -> None:
        state = model.with_task_status(planned(), "a", TaskStatus.RUNNING, AT)
        state = model.with_attempt(state, AttemptRecord("a", 1, TaskStatus.FAILED, "m", "sig"))
        state = model.with_result(state, TaskResult("a", TaskStatus.FAILED, "broke"), AT)
        with self.assertRaises(ValidationError):
            model.reopen(state, "a", AT, "  ")
        reopened = model.reopen(state, "a", AT, "retry with a new approach")
        self.assertIsNone(reopened.tasks["a"].result)
        self.assertEqual(len(reopened.tasks["a"].attempts), 1)
        self.assertEqual(reopened.tasks["a"].finished_at, "")

    def test_task_cannot_start_while_dependency_is_not_verified(self) -> None:
        state = planned()
        for target in (TaskStatus.RUNNING, TaskStatus.READY):
            with self.subTest(target=target), self.assertRaises(ValidationError) as caught:
                model.with_task_status(state, "b", target, AT)
            self.assertEqual(caught.exception.code, "dependency_not_verified")
        partial = model.with_task_status(state, "a", TaskStatus.RUNNING, AT)
        partial = model.with_task_status(partial, "a", TaskStatus.PARTIAL, AT)
        with self.assertRaises(ValidationError):
            model.with_task_status(partial, "b", TaskStatus.RUNNING, AT)
        started = model.with_task_status(verified(state, "a"), "b", TaskStatus.RUNNING, AT)
        self.assertEqual(started.tasks["b"].status, TaskStatus.RUNNING)

    def test_illegal_transitions(self) -> None:
        state = planned()
        running = model.with_task_status(state, "a", TaskStatus.RUNNING, AT)
        cases = (
            (state, TaskStatus.VERIFIED),
            (state, TaskStatus.FAILED),
            (state, TaskStatus.PENDING),
            (running, TaskStatus.RUNNING),
            (running, TaskStatus.PENDING),
            (model.with_task_status(state, "a", TaskStatus.NOT_EXECUTED, AT), TaskStatus.RUNNING),
        )
        for before, target in cases:
            with self.subTest(target=target), self.assertRaises(ValidationError):
                model.with_task_status(before, "a", target, AT)

    def test_failed_and_partial_tasks_can_be_retried(self) -> None:
        for outcome in (TaskStatus.FAILED, TaskStatus.PARTIAL, TaskStatus.BLOCKED):
            state = model.with_task_status(planned(), "a", TaskStatus.RUNNING, AT)
            state = model.with_task_status(state, "a", outcome, AT)
            retried = model.with_task_status(state, "a", TaskStatus.RUNNING, "later")
            self.assertEqual(retried.tasks["a"].started_at, "later")
            self.assertEqual(retried.tasks["a"].finished_at, "")

    def test_unknown_task_is_rejected_and_adhoc_task_can_be_registered(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            model.with_task_status(new_state(), "ghost", TaskStatus.RUNNING, AT)
        self.assertEqual(caught.exception.code, "unknown_task")
        state = model.with_task(new_state(), "solo")
        self.assertEqual(state.tasks["solo"].status, TaskStatus.PENDING)
        with self.assertRaises(ValidationError):
            model.with_task(state, "solo")

    def test_with_result_moves_status_and_records_evidence_and_blockers(self) -> None:
        state = model.with_task_status(planned(), "a", TaskStatus.RUNNING, AT)
        evidence = Evidence("command", "ok", exit_code=0, label=EvidenceLabel.TESTED)
        result = TaskResult("a", TaskStatus.VERIFIED, "done", (evidence,), ("f.py",), ("b1",))
        done = model.with_result(state, result, "end")
        self.assertEqual(done.tasks["a"].status, TaskStatus.VERIFIED)
        self.assertEqual(done.tasks["a"].result, result)
        self.assertEqual(done.tasks["a"].finished_at, "end")
        self.assertEqual([(e.task_id, e.evidence) for e in done.evidence], [("a", evidence)])
        self.assertEqual(done.blockers, ("b1",))

    def test_with_result_cannot_verify_a_task_that_never_ran(self) -> None:
        with self.assertRaises(ValidationError):
            model.with_result(planned(), TaskResult("a", TaskStatus.VERIFIED, "trust me"))
        with self.assertRaises(ValidationError):
            model.with_result(planned(), TaskResult("a", TaskStatus.RUNNING, "not an outcome"))

    def test_attempt_numbers_must_increase(self) -> None:
        state = model.with_attempt(planned(), AttemptRecord("a", 1, TaskStatus.FAILED, "m"))
        with self.assertRaises(ValidationError):
            model.with_attempt(state, AttemptRecord("a", 1, TaskStatus.FAILED, "m"))
        second = model.with_attempt(state, AttemptRecord("a", 2, TaskStatus.FAILED, "m"))
        self.assertEqual(len(second.tasks["a"].attempts), 2)


class NoSecretsTests(unittest.TestCase):
    def test_environment_mappings_are_rejected(self) -> None:
        cases = (
            lambda: model.with_discovery(new_state(), "env", {"TOKEN": "x"}),
            lambda: model.with_discovery(new_state(), "run", {"nested": {"Environ": {"A": "b"}}}),
            lambda: model.with_discovery(new_state(), "snapshot", os.environ),
            lambda: model.with_discovery(new_state(), "vars", {"PATH": "/bin", "HOME": "/root"}),
            lambda: model.with_guard_event(new_state(), {"environment": {"A": "b"}}),
            lambda: model.with_guard_event(new_state(), {"items": [{"env": {}}]}),
        )
        for attempt in cases:
            with self.assertRaises(ValidationError) as caught:
                attempt()
            self.assertEqual(caught.exception.code, "environment_rejected")

    def test_environment_label_strings_are_allowed(self) -> None:
        state = model.with_discovery(new_state(), "remote", {"environment": "staging"})
        self.assertEqual(state.discovery["remote"], {"environment": "staging"})

    def test_command_log_has_no_environment_field(self) -> None:
        entry = CommandLogEntry(AT, "a", ("ls",), "/", 0, 1, RunStatus.PASSED).to_dict()
        with self.assertRaises(ValidationError):
            CommandLogEntry.from_dict({**entry, "env": {"TOKEN": "x"}})

    def test_non_json_values_are_rejected(self) -> None:
        for bad in (object(), {1: "a"}, float("nan"), {"when": b"bytes"}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                model.with_discovery(new_state(), "k", bad)

    def test_iso_utc(self) -> None:
        self.assertEqual(model.iso_utc(0), "1970-01-01T00:00:00.000000Z")


if __name__ == "__main__":
    unittest.main()
