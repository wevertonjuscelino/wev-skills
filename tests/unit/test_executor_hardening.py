"""Executor hardening: program lookup on the safe path and whole-argv redaction."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from wev_skills.config import PermissionsConfig
from wev_skills.core.contracts import Mode, RawCommandResult, RiskLevel, RunStatus
from wev_skills.core.errors import ApprovalRequired, PermissionDenied
from wev_skills.core.ports import SubprocessRunner
from wev_skills.execution import CommandExecutor, untrusted_output
from wev_skills.security.permissions import PermissionPolicy
from wev_skills.security.redact import redact

SECRET = "example_" + "Hunter2" * 3


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
        self.calls.append(tuple(argv))
        if tuple(argv[1:2]) == ("status",):
            return RawCommandResult(tuple(argv), 128, "", "", 1)
        return RawCommandResult(tuple(argv), 0, "out\x1b[2J", "", 1)


class Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        self.safe = self.base / "safe-bin"
        self.safe.mkdir()
        self.policy = PermissionPolicy(PermissionsConfig(exec_path=(str(self.safe),)))

    def program(self, directory: Path, name: str, body: str = "echo real") -> Path:
        path = directory / name
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def executor(self, runner: object, **kwargs: object) -> CommandExecutor:
        return CommandExecutor(self.policy, runner, self.base / "logs", redact, **kwargs)  # type: ignore[arg-type]

    def run_cmd(self, executor: CommandExecutor, *argv: str, mode: Mode = Mode.EXECUTE):  # type: ignore[no-untyped-def]
        return executor.run(argv, self.root, mode, RiskLevel.LOW, track_changes=False)


class ProgramLookupTests(Case):
    def test_path_in_the_environment_does_not_choose_the_program(self) -> None:
        self.program(self.safe, "tool")
        evil = self.base / "evil-bin"
        evil.mkdir()
        self.program(evil, "tool", f"touch {self.base}/pwned; echo fake")
        previous = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{evil}{os.pathsep}{previous}"
        self.addCleanup(os.environ.__setitem__, "PATH", previous)
        record = self.run_cmd(self.executor(SubprocessRunner()), "tool")
        self.assertEqual((record.status, record.stdout_tail.strip()), (RunStatus.PASSED, "real"))
        self.assertEqual(record.program, str(self.safe / "tool"))
        self.assertEqual(record.argv, ("tool",))
        self.assertFalse((self.base / "pwned").exists())

    def test_a_program_only_on_the_inherited_path_is_refused(self) -> None:
        evil = self.base / "evil-bin"
        evil.mkdir()
        self.program(evil, "onlyevil", f"touch {self.base}/pwned")
        previous = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{evil}{os.pathsep}{previous}"
        self.addCleanup(os.environ.__setitem__, "PATH", previous)
        with self.assertRaises(PermissionDenied) as caught:
            self.run_cmd(self.executor(SubprocessRunner()), "onlyevil")
        self.assertEqual(caught.exception.code, "program_not_on_safe_path")
        self.assertFalse((self.base / "pwned").exists())

    def test_a_program_in_the_run_root_is_refused_and_a_relative_one_needs_approval(self) -> None:
        local = self.program(self.root, "tool")
        with self.assertRaises(PermissionDenied) as caught:
            self.run_cmd(self.executor(SubprocessRunner()), str(local))
        self.assertEqual(caught.exception.code, "program_in_run_root")
        with self.assertRaises(ApprovalRequired):
            self.run_cmd(self.executor(SubprocessRunner()), "./tool")

    def test_a_scripted_runner_is_not_resolved_unless_asked(self) -> None:
        runner = RecordingRunner()
        record = self.run_cmd(self.executor(runner), "make", "test")
        self.assertEqual((runner.calls, record.program), ([("make", "test")], "make"))
        self.program(self.safe, "make")
        resolving = self.executor(runner, resolver=self.policy.resolve_program)
        record = self.run_cmd(resolving, "make", "test")
        self.assertEqual(runner.calls[-1], (str(self.safe / "make"), "test"))
        self.assertEqual(record.program, str(self.safe / "make"))


class RedactionTests(Case):
    def test_the_record_and_the_errors_hold_the_argv_redacted_as_a_whole(self) -> None:
        runner = RecordingRunner()
        record = self.run_cmd(self.executor(runner), "tool", "--password", SECRET, "-v")
        self.assertEqual(runner.calls[-1], ("tool", "--password", SECRET, "-v"))
        self.assertNotIn(SECRET, " ".join(record.argv))
        self.assertEqual((record.argv[0], record.argv[-1], len(record.argv)), ("tool", "-v", 4))
        with self.assertRaises(PermissionDenied) as caught:
            self.run_cmd(self.executor(runner), "touch", "--token", SECRET, mode=Mode.PLAN)
        self.assertNotIn(SECRET, str(caught.exception.to_dict()))

    def test_an_approval_request_carries_the_directory(self) -> None:
        with self.assertRaises(ApprovalRequired) as caught:
            self.run_cmd(self.executor(RecordingRunner()), "rm", "-rf", "build")
        self.assertEqual(caught.exception.details["cwd"], str(self.root))

    def test_output_tails_are_fenced_as_untrusted_for_the_caller(self) -> None:
        record = self.run_cmd(self.executor(RecordingRunner()), "tool")
        view = untrusted_output(record.to_dict())
        self.assertIn("WEV_UNTRUSTED_DATA", view["stdout_tail"])
        self.assertNotIn("\x1b", view["stdout_tail"])
        self.assertEqual(view["stderr_tail"], "")
        self.assertTrue(view["untrusted_output"])
        self.assertEqual(view["argv"], record.to_dict()["argv"])


if __name__ == "__main__":
    unittest.main()
