"""End-to-end: the real ``bin/wev`` as subprocesses, a real temporary git repository.

Nothing is mocked here. Each scenario drives a run with ``wev`` commands only, the way an
AI coding session or a person would.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.fixtures.operator_prompt import last_json, run_at_pty

ROOT = Path(__file__).resolve().parents[2]
WEV = ROOT / "bin" / "wev"
SECRET = "example_" + "Hunter2" * 3
GIT = (
    "git",
    "-c",
    "user.name=wev-test",
    "-c",
    "user.email=wev-test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)
PASSING_MAKEFILE = "test:\n\t@echo checks ok\n"
GREETING_MAKEFILE = "test:\n\t@test -f greeting.txt\n"
"""A check that fails before the work (no greeting.txt) and passes after it."""
HIGH_RISK_AGENT = {
    "schema_version": 1,
    "id": "release-engineer",
    "name": {"en": "Release engineer", "pt-BR": "Engenheiro de release"},
    "description": {
        "en": "Carries out approved high-risk changes.",
        "pt-BR": "Executa mudanças de alto risco aprovadas.",
    },
    "extends": "base-engineer",
    "specialties": ["release"],
    "permissions": {"max_risk": "high"},
}
"""The shipped engineers stop at medium risk; a gated scenario needs an agent that may
take high-risk work, added the way a team would: as a spec in a configured directory."""
FAILING_MAKEFILE = "test:\n\t@echo checks failed; exit 1\n"
TIMEOUT_SECONDS = 60


@unittest.skipUnless(shutil.which("git") and shutil.which("make"), "needs git and make")
class CliFlowCase(unittest.TestCase):
    makefile = PASSING_MAKEFILE
    config: dict[str, Any] = {"state_dir": ".wev"}

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        self.write("Makefile", self.makefile)
        self.write("wev.json", json.dumps(self.config))
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "initial")

    def write(self, name: str, text: str) -> None:
        (self.work / name).write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(
            [*GIT, *args], cwd=self.work, check=True, capture_output=True, timeout=TIMEOUT_SECONDS
        )

    def command(self, *args: str, config: str | None = "wev.json") -> list[str]:
        chosen = ["--config", config] if config else []
        return [sys.executable, str(WEV), "--lang", "en", *chosen, *args]

    def wev(
        self, *args: str, cwd: Path | None = None, config: str | None = "wev.json"
    ) -> tuple[int, Any, Any]:
        """``(exit code, stdout JSON, stderr error object)`` of one real CLI call."""
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "WEV_LANG")}
        proc = subprocess.run(
            self.command(*args, config=config),
            cwd=cwd or self.work,
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        err = json.loads(proc.stderr)["error"] if proc.stderr.strip() else None
        return proc.returncode, out, err

    def ok(self, *args: str) -> Any:
        code, out, err = self.wev(*args)
        self.assertEqual(code, 0, f"wev {' '.join(args)} failed: {err}")
        return out

    def follow(self, step: str) -> list[str]:
        """The arguments of a ``next_step`` command line, so tests run what the engine says."""
        self.assertTrue(step.startswith("wev "), step)
        return step.split()[1:]

    def plan(self, *tasks: dict[str, Any]) -> Any:
        filled = [{"title": t["id"], "objective": f"do {t['id']}", **t} for t in tasks]
        self.write(
            "plan.json",
            json.dumps(
                {
                    "risk_notes": "None.",
                    "revert": "git revert",
                    "objective": "planned work",
                    "tasks": filled,
                }
            ),
        )
        return self.ok("plan", "set", "--file", "plan.json")

    def begin(self, *signals: str) -> str:
        """start, next and start the single synthesized task of a DIRECT run."""
        self.ok("run", "start", "--objective", "Add a greeting", "--files", "1", *signals)
        self.ok("task", "next")
        self.ok("task", "start", "task-1")
        return "task-1"

    def work_on(self, name: str = "greeting.txt", text: str = "hello\n") -> None:
        """What an agent's edit tool would do: change a file in the repository."""
        self.write(name, text)

    def verified(self, task_id: str = "task-1") -> tuple[int, Any, Any]:
        return self.wev("task", "record", task_id, "--status", "verified", "--summary", "done")

    def as_operator(self, *args: str, answer: str | None = None) -> tuple[int, Any, Any]:
        """One real CLI call on a pseudo-terminal, typing the confirmation word it shows."""
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "WEV_LANG")}
        code, shown, stderr = run_at_pty(self.command(*args), str(self.work), env, answer)
        err = json.loads(stderr)["error"] if stderr.strip() else None
        return code, last_json(shown), err

    def grant(self, approval_id: str) -> None:
        code, out, err = self.as_operator("approval", "grant", approval_id)
        self.assertEqual((code, out["status"]), (0, "granted"), err)

    def state_text(self) -> str:
        files = [p for p in (self.work / ".wev").rglob("*") if p.is_file()]
        return "".join(p.read_text(encoding="utf-8", errors="replace") for p in files)


class HappyPathTests(CliFlowCase):
    makefile = GREETING_MAKEFILE

    def test_direct_run_from_request_to_complete_report(self) -> None:
        started = self.ok("run", "start", "--objective", "Add a greeting", "--files", "1")
        self.assertEqual(started["strategy"]["flow"], "direct")
        self.assertTrue(started["discovery"]["untrusted"])
        self.assertIn("make test", started["discovery"]["text"])
        self.assertEqual(started["discovery"]["count"], 1)
        self.assertEqual(started["config"]["source"], str(self.work / "wev.json"))
        offered = self.ok(*self.follow(started["next_step"]))
        self.assertEqual([t["task_id"] for t in offered["tasks"]], ["task-1"])
        running = self.ok(*self.follow(offered["next_step"]))
        self.assertEqual((running["status"], running["attempt"]), ("running", 1))
        self.assertEqual(running["baseline"]["failed"], ["make test"])
        ran = self.ok("exec", "--", "touch", "greeting.txt")
        self.assertEqual(ran["record"]["status"], "passed")
        self.assertEqual(ran["record"]["changed_files"], ["greeting.txt"])
        self.assertTrue((self.work / "greeting.txt").exists())
        checked = self.ok(*self.follow(running["next_step"]))
        self.assertTrue(checked["all_met"])
        self.assertEqual((checked["baseline"], checked["tree_changed"]), ("taken", True))
        self.assertIn("does not judge whether they are sufficient", checked["notice"])
        recorded = self.ok(
            "task",
            "record",
            "task-1",
            "--status",
            "verified",
            "--summary",
            "greeting added",
            "--changed-file",
            "greeting.txt",
        )
        finished = self.ok(*self.follow(recorded["next_step"]))
        self.assertEqual((finished["phase"], finished["complete"]), ("done", True))
        report = self.ok(*self.follow(finished["next_step"]))
        self.assertEqual((report["status"], report["reasons"]), ("complete", []))
        task = report["tasks"][0]
        self.assertEqual((task["status"], task["evidence"]), ("verified", "tested"))
        self.assertEqual(task["criteria"][0]["support"], "untied")
        self.assertIn("not tied to this criterion", task["criteria"][0]["support_note"])
        self.assertEqual(task["checks_run"][0]["exit_code"], 0)
        self.assertTrue(Path(task["checks_run"][0]["log_ref"]).is_file())
        self.assertEqual(report["changed_files"], ["greeting.txt"])
        self.assertIn("ran and passed", report["notices"][0])

    def test_the_state_directory_ignores_itself_and_never_shows_as_untracked(self) -> None:
        self.begin()
        self.assertEqual((self.work / ".wev" / ".gitignore").read_text(encoding="utf-8"), "*\n")
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=self.work, capture_output=True, text=True
        ).stdout
        self.assertNotIn(".wev", status)
        self.assertEqual(self.ok("run", "resume")["drift"]["new_dirty_files"], [])

    def test_markdown_report_in_portuguese(self) -> None:
        self.begin()
        self.work_on()
        code, _, _ = self.wev("task", "check", "task-1")
        self.assertEqual(code, 0)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [
                sys.executable,
                str(WEV),
                "--config",
                "wev.json",
                "run",
                "report",
                "--format",
                "md",
                "--lang",
                "pt-BR",
            ],
            cwd=self.work,
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("# Relatório de entrega", proc.stdout)
        self.assertIn("**Status geral:** incompleta", proc.stdout)
        self.assertIn("não avalia se são suficientes", proc.stdout)
        self.assertIn("<<<WEV_UNTRUSTED_DATA", proc.stdout)


class VerifiedNeedsEvidenceTests(CliFlowCase):
    makefile = FAILING_MAKEFILE

    def test_verified_is_refused_without_a_passing_check(self) -> None:
        self.begin()
        record = ("task", "record", "task-1", "--status", "verified", "--summary", "trust me")
        code, out, err = self.wev(*record)
        self.assertEqual((code, out, err["code"]), (2, None, "verification_required"))
        self.work_on()
        checked = self.ok("task", "check", "task-1")
        self.assertFalse(checked["all_met"])
        self.assertEqual(checked["report"]["checks"][0]["record"]["exit_code"], 2)
        self.assertEqual(self.wev(*record)[0], 2)
        report = self.ok("run", "report")
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["tasks"][0]["criteria"][0]["status"], "unmet")


class PlanModeTests(CliFlowCase):
    def test_plan_mode_refuses_next_and_mutating_exec(self) -> None:
        started = self.ok("run", "start", "--objective", "Plan a refactor", "--mode", "plan")
        self.assertIn("wev plan set", started["next_step"])
        planned = self.plan({"id": "a", "files": ["src/a.py"]})
        self.assertIn("wev plan show", planned["next_step"])
        code, _, err = self.wev("task", "next")
        self.assertEqual((code, err["code"]), (3, "plan_mode"))
        self.assertIn("ready for review", err["message"])
        code, _, err = self.wev("exec", "--", "touch", "should-not-exist.txt")
        self.assertEqual(code, 3)
        self.assertFalse((self.work / "should-not-exist.txt").exists())
        self.assertEqual(self.wev("exec", "--", "git", "status", "--short")[0], 0)
        self.assertEqual(self.ok("run", "report")["status"], "incomplete")


class GatedTests(CliFlowCase):
    config = {"state_dir": ".wev", "agents": {"directories": ["team-agents"]}}

    def setUp(self) -> None:
        super().setUp()
        (self.work / "team-agents").mkdir()
        self.write("team-agents/release-engineer.json", json.dumps(HIGH_RISK_AGENT))

    def test_only_the_senior_engineer_takes_shipped_high_risk_work_that_changes_files(self) -> None:
        self.write("wev.json", json.dumps({"state_dir": ".wev"}))
        self.ok("run", "start", "--objective", "Ship it", "--production")
        self.write(
            "plan.json",
            json.dumps(
                {
                    "risk_notes": "None.",
                    "revert": "git revert",
                    "objective": "x",
                    "tasks": [
                        {"id": "a", "title": "a", "objective": "do a", "files": ["gated.txt"]}
                    ],
                }
            ),
        )
        planned = self.ok("plan", "set", "--file", "plan.json")
        self.assertIn("senior-engineer", json.dumps(planned))
        listed = self.ok("agent", "list")["agents"]
        resolved = {a["id"]: self.ok("agent", "show", a["id"], "--resolved") for a in listed}
        high = sorted(
            agent
            for agent, spec in resolved.items()
            if spec["permissions"]["max_risk"] == "high" and spec["permissions"]["may_mutate"]
        )
        self.assertEqual(high, ["senior-engineer"])

    def test_objective_text_alone_makes_a_run_gated(self) -> None:
        started = self.ok("run", "start", "--objective", "Drop the legacy table in production")
        self.assertEqual(
            (started["strategy"]["flow"], started["classification"]["risk"]), ("gated", "high")
        )
        self.assertTrue(started["strategy"]["needs_approval"])
        self.assertIn("'drop'", " ".join(started["classification"]["reasons"]))

    def test_gated_run_waits_for_a_human_and_each_grant_is_single_use(self) -> None:
        started = self.ok("run", "start", "--objective", "Ship it", "--production")
        self.assertEqual(
            (started["strategy"]["flow"], started["classification"]["risk"]), ("gated", "high")
        )
        self.plan({"id": "a", "files": ["gated.txt"]})
        code, _, err = self.wev("task", "next")
        self.assertEqual((code, err["code"]), (4, "approval_required"))
        task_approval = err["details"]["approval_ids"][0]
        self.assertEqual(self.ok("run", "status")["pending_approvals"], [task_approval])
        code, _, refused = self.wev("approval", "grant", task_approval)
        self.assertEqual((code, refused["code"]), (3, "human_required"))
        code, _, refused = self.as_operator("approval", "grant", task_approval, answer="yes")
        self.assertEqual((code, refused["code"]), (3, "confirmation_mismatch"))
        self.assertEqual(self.wev("task", "next")[0], 4)
        self.grant(task_approval)
        self.assertEqual([t["task_id"] for t in self.ok("task", "next")["tasks"]], ["a"])
        self.assertEqual(self.ok("task", "start", "a")["agent_id"], "senior-engineer")
        command = ("exec", "--", "touch", "gated.txt")
        code, _, err = self.wev(*command)
        self.assertEqual(code, 4)
        self.assertFalse((self.work / "gated.txt").exists())
        self.assertIn(err["details"]["approval_id"], err["details"]["next_step"])
        self.assertNotIn(task_approval, err["details"]["next_step"])
        self.grant(err["details"]["approval_id"])
        self.assertEqual(self.wev(*command)[0], 0)
        self.assertTrue((self.work / "gated.txt").exists())
        code, _, again = self.wev(*command)
        self.assertEqual(code, 4)
        self.assertEqual(again["details"]["approval_id"], err["details"]["approval_id"])
        self.assertEqual(
            self.ok("approval", "show", again["details"]["approval_id"])["status"], "pending"
        )


class LoopTests(CliFlowCase):
    def test_repeating_a_failing_command_trips_the_guard_and_exec_is_refused(self) -> None:
        self.begin()
        results = [self.wev("exec", "--", "false") for _ in range(5)]
        self.assertEqual([code for code, _, _ in results], [1, 1, 6, 6, 6])
        self.assertEqual(results[2][1]["guard"]["action"], "change_strategy")
        self.assertEqual(results[4][1]["guard"]["action"], "ask_human")
        for refused in (("exec", "--", "ls"), ("task", "check", "task-1"), ("task", "next")):
            code, _, err = self.wev(*refused)
            self.assertEqual((code, err["code"]), (6, "guard_tripped"), refused)
        code, verdict, _ = self.wev("guard", "check")
        self.assertEqual((code, verdict["action"]), (6, "ask_human"))
        report = self.ok("run", "report")
        self.assertEqual(report["status"], "blocked")
        self.assertIn("ignored_loop", [trip["rule"] for trip in report["guard"]["trips"]])

    def test_a_test_driven_loop_with_edits_between_runs_is_not_a_loop(self) -> None:
        self.write("Makefile", GREETING_MAKEFILE)
        self.git("commit", "-q", "-am", "check for the greeting")
        self.begin()
        for attempt in range(6):
            self.work_on("notes.txt", f"attempt {attempt}\n")
            code, out, _ = self.wev("exec", "--", "make", "test")
            self.assertIn(code, (1, 6), out)
            others = [item["rule"] for item in out["guard"]["details"].get("other_rules", [])]
            tripped = {out["guard"]["rule"], *others}
            self.assertFalse(tripped & {"identical_commands", "no_progress", "ignored_loop"})
            self.assertNotIn(out["guard"]["action"], ("ask_human", "stop"))
        self.work_on()
        self.assertEqual(self.wev("exec", "--", "make", "test")[0], 0)


class ResumeTests(CliFlowCase):
    def test_resume_asks_for_a_new_check_before_verified(self) -> None:
        self.begin()
        self.work_on()
        self.assertTrue(self.ok("task", "check", "task-1")["all_met"])
        self.write("Makefile", PASSING_MAKEFILE + "# edited while the session was away\n")
        resumed = self.ok("run", "resume")
        self.assertEqual(resumed["needs_reverification"], ["task-1"])
        self.assertIn("Makefile", resumed["drift"]["new_dirty_files"])
        self.assertIn("wev task check task-1", resumed["next_step"])
        code, _, err = self.verified()
        self.assertEqual((code, err["code"]), (2, "verification_required"))
        self.ok("task", "check", "task-1")
        self.assertEqual(self.verified()[0], 0)


class EvidenceIntegrityTests(CliFlowCase):
    def test_verified_is_refused_after_the_tree_changed_since_the_check(self) -> None:
        self.begin()
        self.work_on()
        self.assertTrue(self.ok("task", "check", "task-1")["all_met"])
        self.work_on("greeting.txt", "changed after the check\n")
        code, _, err = self.verified()
        self.assertEqual((code, err["code"]), (2, "tree_changed"))
        self.assertIn("wev task check task-1", err["message"])
        self.ok(*self.follow(err["details"]["next_step"]))
        self.assertEqual(self.verified()[0], 0)

    def test_checks_that_passed_at_baseline_do_not_verify_untouched_work(self) -> None:
        self.begin()
        checked = self.ok("task", "check", "task-1")
        self.assertFalse(checked["all_met"])
        criterion = checked["report"]["criteria"][0]
        self.assertEqual(criterion["status"], "unverified")
        self.assertIn("before any work", criterion["reason"])
        code, _, err = self.verified()
        self.assertEqual((code, err["code"]), (2, "verification_required"))
        self.work_on()
        self.assertTrue(self.ok("task", "check", "task-1")["all_met"])
        self.assertEqual(self.verified()[0], 0)

    def test_a_no_op_check_and_a_missing_evidence_file_are_not_evidence(self) -> None:
        self.ok("run", "start", "--objective", "Add a greeting", "--files", "1")
        self.plan({"id": "a", "acceptance_criteria": ["greets"], "checks": ["true", "echo ok"]})
        self.ok("task", "next")
        self.ok("task", "start", "a")
        self.work_on()
        checked = self.ok("task", "check", "a")
        self.assertFalse(checked["all_met"])
        self.assertIn("no-op", checked["report"]["criteria"][0]["reason"])
        evidence = {
            "evidence": [{"kind": "greets", "summary": "x", "ref": "nope.txt", "label": "tested"}]
        }
        self.write("evidence.json", json.dumps(evidence))
        code, _, err = self.wev(
            "task", "record", "a", "--status", "verified", "--summary", "x",
            "--evidence-file", "evidence.json",
        )  # fmt: skip
        self.assertEqual((code, err["code"]), (2, "invalid_evidence_ref"))

    def test_checks_tied_to_criteria_are_reported_per_criterion(self) -> None:
        self.ok("run", "start", "--objective", "Add a greeting", "--files", "1")
        self.plan(
            {
                "id": "a",
                "acceptance_criteria": ["greeting exists", "documented"],
                "checks": [{"command": "test -f greeting.txt", "criteria": [0]}],
            }
        )
        self.ok("task", "next")
        self.ok("task", "start", "a")
        self.work_on()
        checked = self.ok("task", "check", "a")
        statuses = {
            c["criterion"]: (c["status"], c["support"]) for c in checked["report"]["criteria"]
        }
        self.assertEqual(
            statuses, {"greeting exists": ("met", "tied"), "documented": ("unverified", "none")}
        )
        self.assertFalse(checked["all_met"])


class AttemptTests(CliFlowCase):
    config = {"state_dir": ".wev", "limits": {"max_attempts": 2}}

    def test_exhausted_attempts_block_the_task_until_a_person_reopens_it(self) -> None:
        self.begin()
        failed = ("task", "record", "task-1", "--status", "failed", "--summary", "boom")
        first = self.ok(*failed)
        self.assertEqual(first["recommended_action"], "escalate")
        self.assertIsNotNone(first["next_model"])
        self.ok("task", "next")
        self.assertEqual(self.ok("task", "start", "task-1")["model"], first["next_model"])
        second = self.ok(*failed)
        self.assertEqual((second["status"], second["attempts_exhausted"]), ("blocked", True))
        self.assertIn("wev task reopen task-1", second["next_step"])
        code, _, err = self.wev("task", "start", "task-1")
        self.assertEqual((code, err["code"]), (2, "attempts_exhausted"))
        code, _, err = self.wev(*failed)
        self.assertEqual((code, err["code"]), (2, "task_not_running"))
        self.assertIn("wev task reopen", self.ok("run", "status")["next_step"])
        reopen = ("task", "reopen", "task-1", "--reason", "the fixture was wrong")
        code, _, err = self.wev(*reopen)
        self.assertEqual((code, err["code"]), (3, "human_required"))
        code, reopened, err = self.as_operator(*reopen)
        self.assertEqual(code, 0, err)
        self.assertEqual((reopened["status"], reopened["previous_attempts"]), ("pending", 2))
        self.ok("task", "next")
        self.assertEqual(self.ok("task", "start", "task-1")["attempt"], 1)


class PinningTests(CliFlowCase):
    def test_a_different_config_is_refused_once_the_run_started(self) -> None:
        self.begin()
        relaxed = {"state_dir": ".wev", "limits": {"max_identical_commands": 99}}
        self.write("relaxed.json", json.dumps(relaxed))
        code, _, err = self.wev("exec", "--", "ls", config="relaxed.json")
        self.assertEqual((code, err["code"]), (2, "config_pinned"))
        self.write("wev.json", json.dumps(relaxed))
        code, _, err = self.wev("exec", "--", "ls")
        self.assertEqual((code, err["code"]), (2, "config_pinned"))
        codes = [self.wev("exec", "--", "ls", config=None)[0] for _ in range(4)]
        self.assertEqual(codes, [0, 0, 0, 6], "the pinned limit of 3 still applies")

    def test_a_second_run_cannot_start_while_one_is_active(self) -> None:
        first = self.ok("run", "start", "--objective", "Add a greeting", "--files", "1")
        code, _, err = self.wev("run", "start", "--objective", "Something else")
        self.assertEqual((code, err["code"]), (5, "run_active"))
        self.assertIn(f"wev run finish --run {first['run_id']}", err["message"])
        self.ok(*self.follow(err["details"]["next_step"]))
        self.ok("run", "start", "--objective", "Something else")

    def test_commands_run_from_a_subdirectory_use_the_same_run(self) -> None:
        nested = self.work / "src" / "pkg"
        nested.mkdir(parents=True)
        self.write("wev.config.json", json.dumps({"state_dir": ".wev"}))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "config")
        code, started, err = self.wev(
            "run", "start", "--objective", "Add a greeting", "--files", "1", cwd=nested, config=None
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(started["config"]["source"], str(self.work / "wev.config.json"))
        self.assertTrue((self.work / ".wev" / "runs" / started["run_id"]).is_dir())
        self.assertFalse((nested / ".wev").exists())
        code, status, err = self.wev("run", "status", cwd=nested, config=None)
        self.assertEqual((code, status["run_id"]), (0, started["run_id"]), err)
        self.assertEqual(self.wev("task", "next", cwd=nested, config=None)[0], 0)
        self.assertEqual(self.wev("run", "status", config=None)[1]["run_id"], started["run_id"])


class ConcurrencyTests(CliFlowCase):
    TRIALS = 6

    def test_racing_starts_of_tasks_that_share_a_file_never_both_run(self) -> None:
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "WEV_LANG")}
        for trial in range(self.TRIALS):
            self.ok("run", "start", "--objective", "Two changes", "--files", "2", "--subtasks", "2")
            self.plan({"id": "a", "files": ["shared.py"]}, {"id": "b", "files": ["shared.py"]})
            racers = [
                subprocess.Popen(
                    self.command("task", "start", task),
                    cwd=self.work,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                )
                for task in ("a", "b")
            ]
            for racer in racers:
                racer.communicate(timeout=TIMEOUT_SECONDS)
            codes = sorted(racer.returncode for racer in racers)
            statuses = [task["status"] for task in self.ok("plan", "show")["tasks"]]
            self.assertEqual(statuses.count("running"), 1, f"trial {trial}: {statuses} {codes}")
            self.assertEqual(codes, [0, 2], f"trial {trial}")
            self.ok("run", "finish")


class EveryPhaseTests(CliFlowCase):
    makefile = GREETING_MAKEFILE
    MAX_STEPS = 20

    def test_every_printed_next_step_runs_as_printed_from_request_to_report(self) -> None:
        started = self.ok("run", "start", "--objective", "Refactor the parser", "--files", "8")
        self.assertTrue(started["strategy"]["needs_independent_review"])
        tasks = [{"id": "a", "title": "a", "objective": "do a", "files": ["greeting.txt"]}]
        self.write(
            "plan.json",
            json.dumps(
                {
                    "risk_notes": "None.",
                    "revert": "git revert",
                    "objective": "planned work",
                    "tasks": tasks,
                }
            ),
        )
        step, phases, commands = started["next_step"], [], []
        for _ in range(self.MAX_STEPS):
            argv = self.follow(step)
            commands.append(" ".join(argv[:2]))
            out = self.ok(*argv)
            phases.append(self.ok("run", "status", "--run", started["run_id"])["phase"])
            if argv[:2] == ["task", "start"]:
                self.work_on()
            if argv[:2] == ["run", "report"]:
                break
            step = out["next_step"]
        expected = [
            "plan set", "task next", "task start", "task check", "task record",
            "task review", "run finish", "run report",
        ]  # fmt: skip
        self.assertEqual(commands, expected)
        self.assertEqual(phases[-1], "done")
        self.assertTrue({"execute", "verify", "review", "deliver", "done"} <= set(phases), phases)
        self.assertEqual(out["status"], "complete")

    def test_a_direct_run_without_checks_asks_for_them_and_accepts_a_plan(self) -> None:
        (self.work / "Makefile").unlink()
        self.git("commit", "-q", "-am", "no checks")
        started = self.ok("run", "start", "--objective", "Add a greeting", "--files", "1")
        self.assertEqual(started["strategy"]["flow"], "direct")
        self.assertIn("wev plan set", started["next_step"])
        self.assertIn("Supply the checks", started["hint"])
        code, _, err = self.wev("task", "next")
        self.assertEqual((code, err["code"]), (2, "checks_required"))
        tasks = [{"id": "a", "title": "a", "objective": "a", "checks": ["test -f greeting.txt"]}]
        self.write(
            "plan.json",
            json.dumps(
                {"risk_notes": "None.", "revert": "git revert", "objective": "x", "tasks": tasks}
            ),
        )
        planned = self.ok(*self.follow(started["next_step"]))
        self.assertIn("wev task next", planned["next_step"])


class ReviewTests(CliFlowCase):
    def test_self_review_is_refused_and_another_agent_completes_the_run(self) -> None:
        started = self.ok("run", "start", "--objective", "Refactor the parser", "--files", "8")
        self.assertTrue(started["strategy"]["needs_independent_review"])
        self.plan(
            {
                "id": "a",
                "files": ["parser.py"],
                "acceptance_criteria": ["tests pass"],
                "checks": ["make test"],
            }
        )
        self.ok("task", "next")
        executor = self.ok("task", "start", "a")["agent_id"]
        self.work_on("parser.py", "# refactored\n")
        self.ok("task", "check", "a")
        recorded = self.ok("task", "record", "a", "--status", "verified", "--summary", "done")
        suggested = self.follow(recorded["next_step"])
        self.assertEqual(suggested[:3], ["task", "review", "a"])
        reviewer = suggested[suggested.index("--reviewer") + 1]
        self.assertNotEqual(reviewer, executor)
        self.assertEqual(self.ok("run", "report")["status"], "incomplete")

        def review(who: str) -> tuple[int, Any, Any]:
            return self.wev(
                "task",
                "review",
                "a",
                "--reviewer",
                who,
                "--verdict",
                "accept",
                "--summary",
                "read the diff and the test output",
            )

        code, _, err = review(executor)
        self.assertEqual((code, err["code"]), (3, "self_review"))
        code, _, err = review("nobody-by-this-name")
        self.assertEqual((code, err["code"]), (2, "unknown_reviewer"))
        code, out, _ = review(reviewer)
        self.assertEqual((code, out["complete"]), (0, True))
        self.assertIn("wev run finish", out["next_step"])
        report = self.ok("run", "report")
        self.assertEqual(report["status"], "complete")
        recorded_review = report["tasks"][0]["review"]["reviews"][0]
        self.assertEqual(recorded_review["reviewer"], reviewer)
        self.assertEqual(recorded_review["reviewer_identity"], "self-declared")


class ParallelTests(CliFlowCase):
    def test_overlapping_tasks_are_not_offered_together(self) -> None:
        started = self.ok(
            "run", "start", "--objective", "Two changes", "--files", "2", "--subtasks", "2"
        )
        self.assertGreaterEqual(started["strategy"]["max_parallel"], 2)
        self.plan(
            {"id": "a", "files": ["src/app.py"]},
            {"id": "b", "files": ["src/app.py"]},
            {"id": "c", "files": ["docs/guide.md"]},
        )
        offered = self.ok("task", "next")
        self.assertEqual([t["task_id"] for t in offered["tasks"]], ["a", "c"])
        self.assertEqual([d["task_id"] for d in offered["deferred"]], ["b"])
        self.ok("task", "start", "a")
        code, _, err = self.wev("task", "start", "b")
        self.assertEqual((code, err["code"]), (2, "task_not_startable"))


class SecretTests(CliFlowCase):
    def test_secret_printed_by_a_command_is_not_stored_anywhere(self) -> None:
        self.write("leak.txt", f"api_key={SECRET}\nplain line\n")
        self.ok("run", "start", "--objective", f"Add a greeting api_key={SECRET}", "--files", "1")
        self.ok("task", "next")
        self.ok("task", "start", "task-1")
        code, out, _ = self.wev("exec", "--", "cat", "leak.txt")
        self.assertEqual(code, 0)
        self.assertIn("plain line", out["record"]["stdout_tail"])
        self.assertNotIn(SECRET, json.dumps(out))
        stored = self.state_text()
        self.assertNotIn(SECRET, stored)
        self.assertIn("[REDACTED]", stored)
        self.assertIn("plain line", stored)


if __name__ == "__main__":
    unittest.main()
