import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from wev_skills.agents import project
from wev_skills.agents.experience import ACTIVE, PROPOSED, PROPOSER, SCORER, Lesson, LessonEvidence
from wev_skills.agents.spec import AgentSpec
from wev_skills.commands import specialists
from wev_skills.config import Config
from wev_skills.core.contracts import AgentRunResult
from wev_skills.core.errors import GuardTripped, ProviderError, StateConflict, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation import snapshot
from wev_skills.evaluation.gitguard import MAX_READ_BYTES
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
        self.extra_file = False
        self.outcome: AgentRunResult | None = None

    def run_agent(self, workspace: Path, spec: AgentSpec, objective: str, timeout: float):  # type: ignore[no-untyped-def]
        self.runs += 1
        self.on_run()
        if self.extra_file:
            (workspace / "scratch.txt").write_text("agent-wrote-this\n")
        if objective in self.fixes(spec):
            (workspace / f"fix-{objective}.txt").write_text("x")
        return self.outcome or AgentRunResult(True, "done")

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

    def limits(self, **fields: object) -> None:
        self.config = replace(self.config, specialists=replace(self.config.specialists, **fields))

    def test_over_cap_refuses_before_any_run(self) -> None:
        self.add_cases("c1", "c2")
        self.experience(lesson("do x"))
        self.limits(score_max_runs=1)
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
        self.assertEqual(report.new, ())  # a tying model lesson is not stored
        self.assertEqual(self.stored(), {})

    def test_a_losing_model_lesson_is_not_stored(self) -> None:
        self.add_cases("c1")
        report = self.score(FakeAgent(lambda s: set(), ('{"lesson": "write the fix file"}',)))
        self.assertEqual((report.new, self.stored()), ((), {}))
        self.assertEqual(report.runs_used, 3)

    def test_a_fenced_answer_that_helps_is_stored(self) -> None:
        self.add_cases("c1")
        fenced = '```json\n{"lesson": "write the fix file"}\n```'
        agent = FakeAgent(lambda s: {"c1"} if shown(s, "write the fix file") else set(), (fenced,))
        self.assertEqual(len(self.score(agent).new), 1)

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

    def test_a_file_the_agent_wrote_is_in_the_diff_and_the_check_files_are_not(self) -> None:
        self.add_cases("c1")
        agent = FakeAgent(lambda s: set(), ('{"lesson": "write the fix file"}',))
        agent.extra_file = True
        self.score(agent)
        prompt = agent.prompts[0]
        self.assertIn("+++ b/scratch.txt", prompt)
        self.assertIn("agent-wrote-this", prompt)
        self.assertNotIn("b/test_c1.py", prompt)

    def test_a_changed_git_config_decides_nothing(self) -> None:
        self.add_cases("c1")
        item = lesson("do x")
        self.experience(item)
        agent = FakeAgent(lambda s: {"c1"} if shown(s, "do x") else set())
        config_path = self.root / ".git" / "config"
        agent.on_run = lambda: config_path.write_text(config_path.read_text() + "\n[x]\n")
        with self.assertRaises(StateConflict) as ctx:
            self.score(agent)
        self.assertEqual(ctx.exception.code, "git_config_changed")
        self.assertEqual(self.stored()[item.id], item)

    def test_git_after_the_agent_ran_is_hardened(self) -> None:
        self.add_cases("c1")
        calls: list[tuple[tuple[str, ...], object]] = []

        class Recording(SubprocessRunner):
            def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
                calls.append((tuple(argv), env))
                return super().run(argv, cwd, timeout, env)

        score_specialist(
            self.root, self.config, Recording(), FakeAgent(lambda s: set()), AGENT, self.audit
        )
        removals = [c for c in calls if "remove" in c[0] and "worktree" in c[0]]
        self.assertTrue(removals)
        for argv, env in removals:
            self.assertIn("core.hooksPath=/dev/null", argv)
            self.assertIn("core.fsmonitor=", argv)
            self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")  # type: ignore[index]
            self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")  # type: ignore[index]

    def test_an_agent_that_fails_aborts_and_a_timeout_is_a_fail(self) -> None:
        self.add_cases("c1")
        item = lesson("do x")
        self.experience(item)
        agent = FakeAgent(lambda s: set())
        agent.outcome = AgentRunResult(False, "boom")
        with self.assertRaises(ProviderError) as ctx:
            self.score(agent)
        self.assertEqual(ctx.exception.code, "score_agent_failed")
        self.assertEqual(self.stored()[item.id], item)
        self.assertFalse((self.root / self.config.state_dir / SCORES_FILE).exists())
        agent.outcome = AgentRunResult(False, "slow", True)
        self.assertEqual(self.score(agent).baseline, {"c1": 0})

    def test_a_timed_out_agent_fails_even_when_its_work_would_pass(self) -> None:
        self.add_cases("c1")
        agent = FakeAgent(lambda s: {"c1"}, ('{"lesson": "write the fix file"}',))
        agent.outcome = AgentRunResult(False, "slow", True)
        report = self.score(agent)
        self.assertEqual(report.baseline, {"c1": 0})
        self.assertIn("timed out", agent.prompts[0])
        self.assertIn("+++ b/fix-c1.txt", agent.prompts[0])  # the partial work reaches the diff

    def run_recorded(
        self,
        act: Callable[[], None],
        error: type[Exception],
        at_check: Callable[[], None] | None = None,
    ) -> Exception:
        """Score with an agent that calls ``act``; the git calls after it must be none, its
        workspace gone and the lessons unchanged. Returns the error raised."""
        self.add_cases("c1")
        item = lesson("do x")
        self.experience(item)
        calls: list[tuple[str, ...]] = []
        paths: list[Path] = []
        marks: list[int] = []

        class Recording(SubprocessRunner):
            def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
                calls.append(tuple(argv))
                return super().run(argv, cwd, timeout, env)

        agent = FakeAgent(lambda s: set())

        def run() -> None:
            marks.append(len(calls))
            paths.extend(self.scratch_dirs())
            act()

        agent.on_run = run

        def check(*args: object, **kwargs: object) -> SimpleNamespace:
            assert at_check is not None
            at_check()
            return SimpleNamespace()

        patched = (
            mock.patch("wev_skills.evaluation.score_runs.run_check", check)
            if at_check
            else contextlib.nullcontext()
        )
        with patched, self.assertRaises(error) as ctx:
            score_specialist(self.root, self.config, Recording(), agent, AGENT, self.audit)
        self.assertEqual(len(calls), marks[0])  # not one git call after the agent ran
        self.assertTrue(paths)
        self.assertFalse(any(p.exists() for p in paths))
        self.assertEqual(self.stored()[item.id], item)
        return ctx.exception

    def hooks(self) -> Path:
        return self.root / ".git" / "hooks"

    def test_a_hook_planted_by_the_agent_stops_the_run_before_any_git_call(self) -> None:
        err = self.run_recorded(
            lambda: (self.hooks() / "post-checkout").write_text("#!/bin/sh\ntouch /x\n"),
            StateConflict,
        )
        self.assertEqual(err.code, "git_config_changed")  # type: ignore[attr-defined]

    def test_an_unreadable_file_planted_in_hooks_counts_as_tampering(self) -> None:
        def plant() -> None:
            hook = self.hooks() / "unreadable"
            hook.write_text("x")
            hook.chmod(0)

        err = self.run_recorded(plant, StateConflict)
        self.assertEqual(err.code, "git_config_changed")  # type: ignore[attr-defined]

    def test_an_unreadable_directory_planted_in_hooks_counts_as_tampering(self) -> None:
        def plant() -> None:
            folder = self.hooks() / "sub"
            (folder).mkdir()
            (folder / "x").write_text("x")
            folder.chmod(0)
            self.addCleanup(folder.chmod, 0o755)

        err = self.run_recorded(plant, StateConflict)
        self.assertEqual(err.code, "git_config_changed")  # type: ignore[attr-defined]

    def test_chmod_plus_x_on_an_existing_hook_is_detected(self) -> None:
        hook = self.hooks() / "pre-commit"
        hook.write_text("#!/bin/sh\n")
        hook.chmod(0o644)
        err = self.run_recorded(lambda: hook.chmod(0o755), StateConflict)
        self.assertEqual(err.code, "git_config_changed")  # type: ignore[attr-defined]

    def test_a_hook_planted_by_the_check_step_is_caught_after_run_check(self) -> None:
        err = self.run_recorded(
            lambda: None,
            StateConflict,
            at_check=lambda: (self.hooks() / "post-checkout").write_text("#!/bin/sh\n"),
        )
        self.assertEqual(err.code, "git_config_changed")  # type: ignore[attr-defined]

    def test_an_oversized_file_planted_by_the_agent_counts_as_tampering(self) -> None:
        def plant() -> None:
            (self.hooks() / "big").write_bytes(b"x" * (MAX_READ_BYTES + 1))

        err = self.run_recorded(plant, StateConflict)
        self.assertEqual(err.code, "git_config_changed")  # type: ignore[attr-defined]

    def refused_before_any_agent(self, plant: Callable[[], None]) -> None:
        self.add_cases("c1")
        plant()
        agent = FakeAgent(lambda s: set())
        with self.assertRaises(StateConflict) as ctx:
            self.score(agent)
        self.assertEqual(ctx.exception.code, "git_config_changed")
        self.assertEqual(agent.runs, 0)

    def test_an_oversized_file_present_before_the_run_refuses_it(self) -> None:
        self.refused_before_any_agent(
            lambda: (self.hooks() / "big").write_bytes(b"x" * (MAX_READ_BYTES + 1))
        )

    def test_an_unreadable_file_present_before_the_run_refuses_it(self) -> None:
        def plant() -> None:
            hook = self.hooks() / "locked"
            hook.write_text("x")
            hook.chmod(0)

        self.refused_before_any_agent(plant)

    def test_an_agent_that_raises_leaves_no_git_call_and_no_workspace(self) -> None:
        def boom() -> None:
            raise RuntimeError("boom")

        self.run_recorded(boom, RuntimeError)

    def scratch_dirs(self) -> list[Path]:
        return [
            child
            for base in Path(tempfile.gettempdir()).glob("wev-scoring-*")
            for child in base.iterdir()
        ]

    def test_a_candidate_the_render_cap_hides_is_skipped_not_run(self) -> None:
        self.add_cases("c1")
        self.limits(max_lessons_rendered=1)
        held = replace(lesson("held", ACTIVE, "alice"), confirmations=5)
        late = lesson("late")
        bad = lesson("bad advice", ACTIVE, SCORER)
        self.experience(held, late, bad)
        agent = FakeAgent(lambda s: {"c1"})
        report = self.score(agent)
        self.assertEqual(agent.runs, 1)
        self.assertEqual(
            sorted(report.skipped),
            sorted([f"{late.id}: not_shown", f"{bad.id}: ablation_changes_other_lessons"]),
        )

    def test_over_cap_with_a_fitting_baseline_scores_the_oldest_and_defers_the_rest(self) -> None:
        self.add_cases("c1")
        self.limits(score_max_runs=2)
        old = replace(lesson("old tip"), created_at="2026-01-01")
        newer = replace(lesson("newer tip"), created_at="2026-02-01")
        self.experience(newer, old)
        agent = FakeAgent(lambda s: {"c1"} if shown(s, "old tip") else set())
        report = self.score(agent)
        self.assertEqual((report.accepted, report.deferred), ((old.id,), (newer.id, "new:c1")))
        self.assertEqual((agent.runs, agent.prompts), (2, []))
        self.assertGreater(report.planned_runs, 2)

    def test_no_applicable_case_is_refused(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self.score(FakeAgent(lambda s: set()))
        self.assertEqual(ctx.exception.code, "score_no_cases")

    def test_the_scratch_directory_is_removed_when_the_agent_raises(self) -> None:
        self.add_cases("c1")
        made: list[Path] = []
        real = tempfile.mkdtemp

        def spy(*a: object, **k: object) -> str:
            made.append(Path(real(*a, **k)))  # type: ignore[arg-type]
            return str(made[-1])

        agent = FakeAgent(lambda s: set())
        agent.on_run = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        with mock.patch.object(tempfile, "mkdtemp", spy), self.assertRaises(RuntimeError):
            self.score(agent)
        self.assertTrue(made[0].name.startswith("wev-scoring-"))
        self.assertFalse(made[0].exists())

    def test_score_history_command_filters_and_survives_a_missing_file(self) -> None:
        state = self.root / "state"
        scope = SimpleNamespace(state_dir=state, source="s")
        args = SimpleNamespace(config=None, id="a")
        with mock.patch.object(specialists, "resolve_scope", return_value=scope):
            self.assertEqual(specialists._scores(args)["scores"], [])
            state.mkdir()
            lines = [{"agent": "a", "n": 1}, {"agent": "b", "n": 2}, {"agent": "a", "n": 3}]
            (state / SCORES_FILE).write_text("\n".join(json.dumps(x) for x in lines) + "\n")
            self.assertEqual([x["n"] for x in specialists._scores(args)["scores"]], [1, 3])
            args.id = None
            self.assertEqual(len(specialists._scores(args)["scores"]), 3)
            (state / SCORES_FILE).write_text("{oops\n")
            with self.assertRaises(ValidationError):
                specialists._scores(args)


class SnapshotCapsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def take_with_timeout(self) -> snapshot.Snapshot:
        found: list[snapshot.Snapshot] = []
        thread = threading.Thread(target=lambda: found.append(snapshot.take(self.tmp)), daemon=True)
        thread.start()
        thread.join(10)
        self.assertFalse(thread.is_alive(), "snapshot.take hung")
        return found[0]

    def test_a_fifo_is_skipped(self) -> None:
        os.mkfifo(self.tmp / "pipe")
        (self.tmp / "real.txt").write_text("x")
        self.assertEqual(list(self.take_with_timeout().files), ["real.txt"])

    def test_a_symlink_is_skipped(self) -> None:
        (self.tmp / "t.txt").write_text("x")
        os.symlink(self.tmp / "t.txt", self.tmp / "link")
        self.assertEqual(list(self.take_with_timeout().files), ["t.txt"])

    def test_a_huge_file_is_not_read_past_the_cap(self) -> None:
        with open(self.tmp / "huge", "wb") as handle:
            handle.truncate(1 << 31)
        entry = self.take_with_timeout().files["huge"]
        digest = hashlib.sha256(b"\0" * (snapshot.MAX_FILE_BYTES + 1)).digest()
        self.assertEqual((entry.big, entry.size, entry.data), (True, 1 << 31, digest))

    def test_the_file_cap_stops_the_walk_and_the_diff_says_so(self) -> None:
        for name in "abcde":
            (self.tmp / f"{name}.txt").write_text(name)
        full = snapshot.take(self.tmp)
        with mock.patch.object(snapshot, "MAX_FILES", 3):
            capped = snapshot.take(self.tmp)
        self.assertEqual(
            (capped.truncated, sorted(capped.files)), (True, ["a.txt", "b.txt", "c.txt"])
        )
        out = snapshot.diff(full, capped)
        self.assertNotIn("/dev/null", out)  # d and e are unknown, not deleted
        self.assertIn("snapshot truncated", out)

    def test_the_byte_cap_truncates(self) -> None:
        (self.tmp / "a.txt").write_text("x" * 50)
        (self.tmp / "b.txt").write_text("y" * 50)
        with mock.patch.object(snapshot, "MAX_TOTAL_BYTES", 60):
            self.assertTrue(snapshot.take(self.tmp).truncated)


class SnapshotTest(unittest.TestCase):
    def test_diff_covers_new_deleted_changed_and_large_files(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".git").mkdir()
        (tmp / ".git" / "x").write_text("ignored")
        (tmp / "gone.txt").write_text("bye\n")
        (tmp / "same.txt").write_text("a\n")
        (tmp / "big.bin").write_bytes(b"\0" * 10)
        before = snapshot.take(tmp)
        (tmp / "gone.txt").unlink()
        (tmp / "same.txt").write_text("b\n")
        (tmp / "new.txt").write_text("hi\n")
        (tmp / "big.bin").write_bytes(b"\1" * 10)
        (tmp / ".git" / "x").write_text("changed")
        out = snapshot.diff(before, snapshot.take(tmp))
        for text in ("--- a/gone.txt", "+++ /dev/null", "-a", "+b", "+++ b/new.txt", "+hi"):
            self.assertIn(text, out)
        self.assertIn("Binary or large file changed: big.bin", out)
        self.assertNotIn(".git", out)


if __name__ == "__main__":
    unittest.main()
