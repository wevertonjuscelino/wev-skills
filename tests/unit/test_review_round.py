"""A layered-review round: what it records, refuses, caps and commits."""

from __future__ import annotations

import contextlib
import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.fixtures.fake_agent import FakeAgent
from tests.unit._review_helpers import ReviewRepo, found, item, vote, votes
from wev_skills import schema
from wev_skills.config_review import ReviewConfig
from wev_skills.core import guard_ack
from wev_skills.core.contracts import AgentRunResult, TaskStatus
from wev_skills.core.errors import GuardTripped, ProviderError, StateConflict, ValidationError
from wev_skills.review.round import run_round
from wev_skills.review.summary import summarize
from wev_skills.state.review_records import all_findings


class RecordingAgent(FakeAgent):
    """A FakeAgent that keeps the prompt of each run."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.objectives: list[str] = []

    def run_agent(self, workspace: Path, spec: Any, objective: str, timeout: float, tools=()):  # type: ignore[no-untyped-def]
        self.objectives.append(objective)
        return super().run_agent(workspace, spec, objective, timeout, tools)


def one_finding_agent(line: int = 5, title: str = "Off by one") -> FakeAgent:
    return FakeAgent(finder_replies=[found(item(line, title))], verifier_replies=[votes(vote(0))])


class RoundTests(ReviewRepo):
    def run_round(self, agent: FakeAgent, orch: Any = None) -> Any:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            record = run_round(orch or self.orch(), agent, "en")
        self.stderr = err.getvalue()
        return record

    def state(self) -> Any:
        return self.orch().load()

    def test_round_records_findings_and_summary(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        record = self.run_round(one_finding_agent())
        (finding,) = record.findings
        self.assertEqual((finding.file, finding.line, finding.tag), ("a.py", 5, "important"))
        self.assertEqual((record.number, record.scope, record.runs_used), (1, "full", 2))
        self.assertEqual(record.summary.splitlines()[0], "Open: 1 Important, 0 Nit, 0 Pre-existing")
        self.assertIn("a.py:5", record.summary)
        self.assertEqual(self.state().review_rounds, (record,))
        self.assertIn("2 agent runs", self.stderr)
        self.assertIn("review.round", [e["type"] for e in self.orch().services.audit.read()])

    def test_a_state_with_rounds_matches_the_schema(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        self.run_round(one_finding_agent())
        data = self.state().to_dict()
        self.assertEqual(schema.validate(data, schema.load("state")), [])

    def test_summary_nothing_to_fix(self) -> None:
        self.assertEqual(summarize([], 0, "en"), "Nothing to fix")

    def test_summary_counts_skips_when_skip_matches_everything(self) -> None:
        self.assertEqual(
            summarize([], 4, "en").splitlines(), ["Nothing to fix", "4 skipped by REVIEW.md"]
        )
        self.write("REVIEW.md", "## Skip\n- *\n")
        self.start()
        self.edit(5, "x5 = 'changed'")
        record = self.run_round(one_finding_agent())
        self.assertEqual(record.findings, ())
        self.assertEqual(record.summary.splitlines(), ["Nothing to fix", "1 skipped by REVIEW.md"])

    def test_off_refused(self) -> None:
        self.overrides = {}
        self.start()
        with self.assertRaises(ValidationError) as caught:
            self.run_round(FakeAgent())
        self.assertEqual((caught.exception.code, caught.exception.exit_code), ("review_off", 2))

    def test_no_agent_refused(self) -> None:
        self.start()
        orch = self.orch()
        config = replace(orch.services.config, review=ReviewConfig(depth="quick"))
        orch.services = replace(orch.services, config=config)
        with self.assertRaises(ValidationError) as caught:
            self.run_round(FakeAgent(), orch)
        self.assertEqual(caught.exception.code, "review_off")

    def test_no_base_refused(self) -> None:
        self.start()
        path = self.orch().store.state_path
        data = json.loads(path.read_text())
        data["base"] = ""
        path.write_text(json.dumps(data))
        agent = FakeAgent()
        with self.assertRaises(StateConflict) as caught:
            self.run_round(agent)
        self.assertEqual((caught.exception.code, agent.runs), ("review_no_base", 0))

    def test_running_task_refused(self) -> None:
        self.start()
        plan = self.root / "plan.json"
        task = {"id": "a", "title": "a", "objective": "do a", "acceptance_criteria": ["ok"],
                "checks": ["make test"]}  # fmt: skip
        plan.write_text(json.dumps({"objective": "o", "tasks": [task]}))
        self.orch().set_plan(str(plan))
        self.orch().next_tasks()
        self.orch().start_task("a")
        self.assertIs(self.state().tasks["a"].status, TaskStatus.RUNNING)
        agent = FakeAgent()
        with self.assertRaises(StateConflict) as caught:
            self.run_round(agent)
        self.assertEqual((caught.exception.code, agent.runs), ("task_running", 0))

    def test_over_cap_refused_before_any_run(self) -> None:
        self.overrides = {"review": {"agent": "reviewer", "depth": "deep", "finders": 8}}
        self.start()
        agent = FakeAgent()
        with self.assertRaises(GuardTripped) as caught:
            self.run_round(agent)
        self.assertEqual(
            (caught.exception.code, caught.exception.exit_code), ("review_over_cap", 6)
        )
        self.assertEqual((agent.runs, self.state().review_rounds), (0, ()))

    def three_rounds(self) -> RecordingAgent:
        self.start()
        agent = RecordingAgent()
        for number in (1, 2, 3):
            self.edit(number * 6, f"x{number} = 'EDIT{number}'")
            self.run_round(agent)
        return agent

    def test_third_round_is_diff_only(self) -> None:
        agent = self.three_rounds()
        self.assertEqual([r.scope for r in self.state().review_rounds], ["full", "full", "diff"])
        second, third = agent.objectives[1], agent.objectives[2]
        self.assertTrue("EDIT1" in second and "EDIT2" in second)
        self.assertTrue("EDIT3" in third and "EDIT1" not in third and "EDIT2" not in third)

    def test_fourth_round_trips_guard(self) -> None:
        self.three_rounds()
        agent = FakeAgent()
        with self.assertRaises(GuardTripped) as caught:
            self.run_round(agent)
        self.assertEqual((caught.exception.code, caught.exception.exit_code), ("review_rounds", 6))
        (trip,) = self.state().guard_trips
        self.assertEqual((trip.task_id, trip.rule, trip.action), ("", "review_rounds", "stop"))
        self.assertEqual((agent.runs, len(self.state().review_rounds)), (0, 3))

    def test_acknowledge_allows_exactly_one_more(self) -> None:
        self.three_rounds()
        with self.assertRaises(GuardTripped):
            self.run_round(FakeAgent())
        guard_ack.acknowledge(self.orch(), None, "one more", "ana", "tty")
        self.assertEqual(self.state().review_allowance, 1)
        self.edit(20, "x20 = 'LATE'")
        self.assertEqual(self.run_round(FakeAgent()).number, 4)
        with self.assertRaises(GuardTripped):
            self.run_round(FakeAgent())
        self.assertEqual(self.state().review_allowance, 1)

    def test_concurrent_round_conflicts(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        agent = one_finding_agent()
        other = self.orch()
        fired: list[int] = []

        def interfere() -> None:
            if not fired:
                fired.append(1)
                other.commit(lambda state: state, "other.process")

        agent.on_run = interfere
        with self.assertRaises(StateConflict) as caught:
            self.run_round(agent)
        self.assertEqual(caught.exception.code, "revision_mismatch")
        self.assertEqual(self.state().review_rounds, ())

    def test_fixed_recheck_marks_the_earlier_finding(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        first = self.run_round(one_finding_agent())
        self.edit(5, "x5 = 'repaired'")
        agent = FakeAgent(verifier_replies=[votes(vote(0, real=False))])
        second = self.run_round(agent)
        self.assertEqual(second.findings, ())
        (old,) = all_findings(self.state().review_rounds)
        self.assertEqual(
            (old.id, old.status, old.outcome), (first.findings[0].id, "fixed", "fixed")
        )
        self.assertIn("Nothing to fix", second.summary)

    def test_far_edit_does_not_recheck_an_open_finding(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        self.run_round(one_finding_agent())
        self.edit(25, "x25 = 'elsewhere'")
        agent = FakeAgent()
        second = self.run_round(agent)
        self.assertEqual((agent.runs, second.runs_used), (1, 1))
        self.assertEqual(all_findings(self.state().review_rounds)[0].status, "open")

    def test_agent_failure_records_no_round(self) -> None:
        self.start()
        self.edit(5, "x5 = 'changed'")
        agent = FakeAgent(finder_replies=[AgentRunResult(False, "")])
        with self.assertRaises(ProviderError) as caught:
            self.run_round(agent)
        self.assertEqual((caught.exception.exit_code, self.state().review_rounds), (8, ()))

    def test_state_without_rounds_loads(self) -> None:
        self.start()
        path = self.orch().store.state_path
        data = json.loads(path.read_text())
        data.pop("review_rounds", None)
        data.pop("review_allowance", None)
        path.write_text(json.dumps(data))
        state = self.state()
        self.assertEqual((state.review_rounds, state.review_allowance), ((), 0))
