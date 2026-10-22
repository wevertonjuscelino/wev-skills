import json
import shutil
import subprocess
import tempfile
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from wev_skills.agents import project
from wev_skills.agents.experience import ACTIVE, PROPOSED, PROPOSER, SCORER, Lesson, LessonEvidence
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import Config
from wev_skills.core.contracts import AgentRunResult
from wev_skills.core.errors import GuardTripped, StateConflict
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation.scoring import SCORES_FILE, planned_runs, score_specialist
from wev_skills.governance.audit import AuditLog

AGENT = "spec1"


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def lesson(text: str, status: str = PROPOSED, by: str = PROPOSER) -> Lesson:
    ident = "lesson-" + text.replace(" ", "")
    return Lesson(
        ident, "practice", text, LessonEvidence("r", "t"), "2026-01-01", by, status=status
    )


def shown(spec: AgentSpec, text: str) -> bool:
    return any(
        item.text == text and item.status == ACTIVE and item.accepted_by != PROPOSER
        for item in spec.experience
    )


class FakeAgent:
    """Writes the fix for the cases ``fixes(spec)`` names; ``ask`` gives scripted answers."""

    def __init__(self, fixes: Callable[[AgentSpec], set[str]], answers: tuple[str, ...] = ()):
        self.fixes, self.answers = fixes, list(answers)
        self.runs = 0
        self.prompts: list[str] = []
        self.on_run: Callable[[], None] = lambda: None

    def run_agent(self, workspace: Path, spec: AgentSpec, objective: str, timeout: float):  # type: ignore[no-untyped-def]
        self.runs += 1
        self.on_run()
        if objective in self.fixes(spec):
            (workspace / f"fix-{objective}.txt").write_text("x")
        return AgentRunResult(True, "done")

    def ask(self, prompt: str, timeout: float):  # type: ignore[no-untyped-def]
        self.prompts.append(prompt)
        return AgentRunResult(True, self.answers.pop(0) if self.answers else "no")


class ScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.root = tmp / "repo"
        self.root.mkdir()
        git(self.root, "init", "-q")
        (self.root / "a.txt").write_text("1")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "one")
        self.base = git(self.root, "rev-parse", "HEAD")
        base = Config()
        self.config = replace(base, specialists=replace(base.specialists, score_samples=1))
        project.create(self.root, self.config, AGENT, "senior-engineer", ())
        self.audit = AuditLog(tmp / "audit.jsonl")

    def add_cases(self, *ids: str) -> None:
        for cid in ids:
            folder = self.root / "evals" / "cases"
            (folder / cid).mkdir(parents=True)
            (folder / cid / f"test_{cid}.py").write_text(
                "import pathlib, unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test(self):\n"
                f"        self.assertTrue(pathlib.Path('fix-{cid}.txt').exists())\n"
            )
            data = {
                "id": cid, "title": cid, "source": "e2e", "ref": "r", "agents": [],
                "base_commit": self.base, "objective": cid,
                "check": ["python3", "-m", "unittest", f"test_{cid}"],
                "files": [f"test_{cid}.py"],
            }  # fmt: skip
            (folder / f"{cid}.json").write_text(json.dumps(data))
        git(self.root, "add", "evals")
        git(self.root, "commit", "-qm", "cases")

    def experience(self, *lessons: Lesson) -> None:
        spec = project.list_specs(self.root, self.config)[0]
        project._write(self.root, self.config, replace(spec, experience=tuple(lessons)))

    def stored(self) -> dict[str, Lesson]:
        spec = project.list_specs(self.root, self.config)[0]
        return {item.id: item for item in spec.experience}

    def score(self, agent: FakeAgent):  # type: ignore[no-untyped-def]
        return score_specialist(
            self.root, self.config, SubprocessRunner(), agent, AGENT, self.audit
        )

    def test_planned_runs_formula(self) -> None:
        self.assertEqual(planned_runs(4, 2, 1, 2, 3), (1 + 2 + 3 + 1) * 4 * 2 + 3)

    def test_over_cap_refuses_before_any_run(self) -> None:
        self.add_cases("c1")
        self.experience(lesson("do x"))
        config = replace(
            self.config, specialists=replace(self.config.specialists, score_max_runs=3)
        )
        self.config = config
        agent = FakeAgent(lambda spec: set())
        with self.assertRaises(GuardTripped) as ctx:
            self.score(agent)
        self.assertEqual(ctx.exception.code, "score_over_cap")
        self.assertEqual((agent.runs, agent.prompts), (0, []))

    def test_lesson_that_fixes_a_case_enters(self) -> None:
        self.add_cases("c1")
        item = lesson("do x")
        self.experience(item)
        report = self.score(FakeAgent(lambda s: {"c1"} if shown(s, "do x") else set()))
        self.assertEqual((report.accepted, report.baseline), ((item.id,), {"c1": 0}))
        self.assertEqual(self.stored()[item.id].status, ACTIVE)
        self.assertEqual(self.stored()[item.id].accepted_by, SCORER)

    def test_tie_stays_proposed(self) -> None:
        self.add_cases("c1")
        item = lesson("do x")
        self.experience(item)
        report = self.score(FakeAgent(lambda s: set()))
        self.assertEqual(report.accepted, ())
        self.assertEqual(self.stored()[item.id], item)

    def test_regression_never_enters(self) -> None:
        self.add_cases("c1", "c2", "c3")
        item = lesson("do x")
        self.experience(item)

        def fixes(spec: AgentSpec) -> set[str]:
            return {"c1", "c3"} if shown(spec, "do x") else {"c2"}

        report = self.score(FakeAgent(fixes))
        self.assertEqual(report.accepted, ())
        self.assertEqual(self.stored()[item.id].status, PROPOSED)

    def test_active_lesson_that_hurts_is_retired(self) -> None:
        self.add_cases("c1")
        item = lesson("bad advice", ACTIVE, SCORER)
        self.experience(item)
        report = self.score(FakeAgent(lambda s: set() if shown(s, "bad advice") else {"c1"}))
        self.assertEqual(report.retired, (item.id,))
        self.assertEqual(self.stored()[item.id].status, "retired")

    def test_model_lesson_written_and_scored(self) -> None:
        self.add_cases("c1")
        answer = '{"lesson": "write the fix file"}'
        agent = FakeAgent(lambda s: {"c1"} if shown(s, "write the fix file") else set(), (answer,))
        report = self.score(agent)
        self.assertEqual(len(report.new), 1)
        self.assertEqual(report.accepted, report.new)
        saved = self.stored()[report.new[0]]
        self.assertEqual((saved.kind, saved.status, saved.accepted_by), ("model", ACTIVE, SCORER))
        self.assertEqual(len(agent.prompts), 1)
        self.assertEqual(report.runs_used, 1 + 1 + 1)

    def test_a_single_code_fence_around_the_answer_is_stripped(self) -> None:
        self.add_cases("c1")
        fenced = '```json\n{"lesson": "write the fix file"}\n```'
        report = self.score(FakeAgent(lambda s: set(), (fenced,)))
        self.assertEqual(len(report.new), 1)
        self.assertEqual(self.stored()[report.new[0]].status, PROPOSED)

    def test_two_fences_or_prose_drop_the_lesson(self) -> None:
        self.add_cases("c1")
        double = '```\n```json\n{"lesson": "a b"}\n```\n```'
        report = self.score(FakeAgent(lambda s: set(), (double,)))
        self.assertEqual(report.new, ())

    def test_cases_changed_during_run_decides_nothing(self) -> None:
        self.add_cases("c1")
        item = lesson("do x")
        self.experience(item)
        agent = FakeAgent(lambda s: {"c1"} if shown(s, "do x") else set())
        agent.on_run = lambda: (self.root / "evals" / "cases" / "extra.txt").write_text("new")
        with self.assertRaises(StateConflict) as ctx:
            self.score(agent)
        self.assertEqual(ctx.exception.code, "cases_changed")
        self.assertEqual(self.stored()[item.id], item)
        self.assertFalse((self.root / self.config.state_dir / SCORES_FILE).exists())

    def test_history_line_written(self) -> None:
        self.add_cases("c1")
        first = self.score(FakeAgent(lambda s: set()))
        second = self.score(FakeAgent(lambda s: set()))
        path = self.root / self.config.state_dir / SCORES_FILE
        lines = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(lines, [first.to_dict(), second.to_dict()])

    def test_audit_events_carry_digest_and_counts(self) -> None:
        self.add_cases("c1", "c2")
        good, bad = lesson("do x"), lesson("bad advice", ACTIVE, SCORER)
        self.experience(good, bad)

        def fixes(spec: AgentSpec) -> set[str]:
            return ({"c1"} if shown(spec, "do x") else set()) | (
                set() if shown(spec, "bad advice") else {"c2"}
            )

        report = self.score(FakeAgent(fixes))
        events = {e["type"]: e["data"] for e in self.audit.read()}
        self.assertEqual(set(events), {"specialists.auto_accept", "specialists.auto_retire"})
        for data in events.values():
            self.assertEqual((data["specialist"], data["digest"]), (AGENT, report.digest))
        self.assertEqual(events["specialists.auto_accept"]["lesson"], good.id)
        self.assertEqual(events["specialists.auto_accept"]["before"], 0)


if __name__ == "__main__":
    unittest.main()
