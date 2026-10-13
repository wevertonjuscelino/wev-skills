from __future__ import annotations

import json
import shutil
import stat
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import (
    EvidenceLabel,
    Mode,
    PermissionDecision,
    PermissionOutcome,
    RawCommandResult,
    RiskLevel,
    RunStatus,
)
from wev_skills.core.errors import ApprovalRequired, NotFound, PermissionDenied, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.execution import CommandExecutor, CommandRecord, to_evidence, to_guard_event
from wev_skills.guards import GuardEventKind, command_signature

ALLOW = PermissionDecision(PermissionOutcome.ALLOW)
SECRET = "sk-super-secret-123"


class FakeGate:
    def __init__(self, decision: PermissionDecision = ALLOW) -> None:
        self.decision = decision
        self.calls: list[tuple[str, ...]] = []

    def check_command(
        self, argv: Sequence[str], cwd: str | None, mode: Mode, risk: RiskLevel
    ) -> PermissionDecision:
        self.calls.append(tuple(argv))
        return self.decision


class FakeRunner:
    def __init__(self, result: RawCommandResult | None = None, git: RawCommandResult | None = None):
        self.result = result
        self.git = git
        self.calls: list[tuple[tuple[str, ...], Mapping[str, str] | None]] = []

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> RawCommandResult:
        self.calls.append((tuple(argv), env))
        if tuple(argv[:2]) == ("git", "status"):
            return self.git or RawCommandResult(tuple(argv), 128, "", "not a git repository", 1)
        assert self.result is not None
        return self.result


def raw(
    code: int | None = 0, out: str = "", err: str = "", timed_out: bool = False
) -> RawCommandResult:
    return RawCommandResult(("x",), code, out, err, 7, timed_out)


def redact(text: str) -> str:
    return text.replace(SECRET, "[REDACTED]")


class ExecutorBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.logs = self.root / "logs"

    def executor(
        self,
        runner: object,
        gate: FakeGate | None = None,
        redactor=redact,  # type: ignore[no-untyped-def]
    ) -> CommandExecutor:
        return CommandExecutor(gate or FakeGate(), runner, self.logs, redactor)  # type: ignore[arg-type]

    def run_cmd(self, ex: CommandExecutor, argv: Sequence[str], **kw: object) -> CommandRecord:
        return ex.run(argv, self.cwd, Mode.EXECUTE, RiskLevel.LOW, **kw)  # type: ignore[arg-type]


class GateAndInputTests(ExecutorBase):
    def test_deny_raises_and_runs_nothing(self) -> None:
        runner = FakeRunner(raw())
        gate = FakeGate(PermissionDecision(PermissionOutcome.DENY, "nope"))
        with self.assertRaises(PermissionDenied) as ctx:
            self.run_cmd(self.executor(runner, gate), ["rm", "-rf", "x"])
        self.assertEqual(runner.calls, [])
        self.assertEqual(ctx.exception.details["argv"], ["rm", "-rf", "x"])

    def test_needs_approval_carries_argv(self) -> None:
        runner = FakeRunner(raw())
        gate = FakeGate(PermissionDecision(PermissionOutcome.NEEDS_APPROVAL, "risky"))
        with self.assertRaises(ApprovalRequired) as ctx:
            self.run_cmd(self.executor(runner, gate), ["deploy", "--prod"])
        self.assertEqual(ctx.exception.details["argv"], ["deploy", "--prod"])
        self.assertEqual(runner.calls, [])

    def test_shell_string_and_empty_argv_rejected_before_gate(self) -> None:
        gate = FakeGate()
        ex = self.executor(FakeRunner(raw()), gate)
        for bad in ("ls -la", [], [""]):
            with self.assertRaises(ValidationError):
                self.run_cmd(ex, bad)  # type: ignore[arg-type]
        self.assertEqual(gate.calls, [])

    def test_missing_cwd_rejected_without_running(self) -> None:
        runner = FakeRunner(raw())
        with self.assertRaises(NotFound):
            self.executor(runner).run(["ls"], self.root / "nope", Mode.EXECUTE, RiskLevel.LOW)
        self.assertEqual(runner.calls, [])


class RecordTests(ExecutorBase):
    def test_status_mapping_with_fake_runner(self) -> None:
        cases = [
            (raw(0), RunStatus.PASSED),
            (raw(3), RunStatus.FAILED),
            (raw(None, timed_out=True), RunStatus.UNKNOWN),
            (raw(None), RunStatus.UNKNOWN),
            (
                raw(127, err="FileNotFoundError: [Errno 2] No such file or directory: 'zz'"),
                RunStatus.BLOCKED,
            ),
            (raw(127, err="tool says: not found"), RunStatus.FAILED),
        ]
        for result, expected in cases:
            record = self.run_cmd(self.executor(FakeRunner(result)), ["x"], track_changes=False)
            self.assertEqual(record.status, expected, result)

    def test_blocked_keeps_reason_and_no_exit_code(self) -> None:
        err = "FileNotFoundError: [Errno 2] No such file or directory: 'zz'"
        record = self.run_cmd(self.executor(FakeRunner(raw(127, err=err))), ["zz"])
        self.assertIsNone(record.exit_code)
        self.assertIn("No such file", record.stderr_tail)

    def test_runner_oserror_is_blocked(self) -> None:
        class Boom:
            def run(self, *args: object) -> RawCommandResult:
                raise PermissionError("denied by os")

        record = self.run_cmd(self.executor(Boom()), ["x"], track_changes=False)
        self.assertEqual(record.status, RunStatus.BLOCKED)
        self.assertIn("denied by os", record.stderr_tail)

    def test_logs_are_redacted_private_and_sequenced(self) -> None:
        runner = FakeRunner(raw(0, out=f"token={SECRET}\n", err=f"err {SECRET}"))
        ex = self.executor(runner)
        first = self.run_cmd(ex, ["echo", SECRET], track_changes=False)
        second = self.run_cmd(ex, ["echo", "b"], track_changes=False)
        out = Path(first.stdout_ref)
        self.assertNotIn(SECRET, out.read_text())
        self.assertNotIn(SECRET, Path(first.stderr_ref).read_text())
        self.assertNotIn(SECRET, first.stdout_tail + first.stderr_tail + " ".join(first.argv))
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
        self.assertTrue(out.name.startswith("000001-") and out.name.endswith(".stdout.log"))
        self.assertTrue(Path(second.stdout_ref).name.startswith("000002-"))
        self.assertEqual(stat.S_IMODE(self.logs.stat().st_mode), 0o700)

    def test_sequence_continues_across_executor_instances(self) -> None:
        for _ in range(2):
            record = self.run_cmd(self.executor(FakeRunner(raw())), ["x"], track_changes=False)
        self.assertTrue(Path(record.stdout_ref).name.startswith("000002-"))

    def test_tail_is_bounded(self) -> None:
        record = self.run_cmd(
            self.executor(FakeRunner(raw(0, out="a" * 10000 + "END"))), ["x"], track_changes=False
        )
        self.assertLessEqual(len(record.stdout_tail), 2000)
        self.assertTrue(record.stdout_tail.endswith("END"))
        self.assertIn("END", Path(record.stdout_ref).read_text())

    def test_env_is_never_passed_or_recorded(self) -> None:
        runner = FakeRunner(raw())
        record = self.run_cmd(self.executor(runner), ["x"], track_changes=False)
        self.assertTrue(all(env is None for _, env in runner.calls))
        self.assertNotIn("env", record.to_dict())

    def test_record_round_trips(self) -> None:
        record = self.run_cmd(self.executor(FakeRunner(raw(0, out="hi"))), ["x"], task_id="t9")
        again = CommandRecord.from_dict(json.loads(json.dumps(record.to_dict())))
        self.assertEqual(again, record)
        self.assertEqual(again.task_id, "t9")


class ChangedFilesTests(ExecutorBase):
    def porcelain(self, text: str) -> RawCommandResult:
        return RawCommandResult(("git",), 0, text, "", 1)

    def test_diff_of_status_before_and_after(self) -> None:
        class Seq(FakeRunner):
            def __init__(self) -> None:
                super().__init__(raw())
                self.statuses = [" M old.py\n", " M old.py\n?? new.py\n"]

            def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
                if tuple(argv[:2]) == ("git", "status"):
                    return RawCommandResult(tuple(argv), 0, self.statuses.pop(0), "", 1)
                return super().run(argv, cwd, timeout, env)

        record = self.run_cmd(self.executor(Seq()), ["x"])
        self.assertEqual(record.changed_files, ("new.py",))

    def test_outside_git_repo_is_skipped_quietly(self) -> None:
        record = self.run_cmd(self.executor(FakeRunner(raw())), ["x"])
        self.assertEqual(record.changed_files, ())

    def test_track_changes_false_does_not_call_git(self) -> None:
        runner = FakeRunner(raw())
        self.run_cmd(self.executor(runner), ["x"], track_changes=False)
        self.assertEqual([c[0] for c in runner.calls], [("x",)])


class RealRunnerTests(ExecutorBase):
    def ex(self, redactor=redact) -> CommandExecutor:  # type: ignore[no-untyped-def]
        return self.executor(SubprocessRunner(), redactor=redactor)

    def test_success_and_failure(self) -> None:
        ok = self.run_cmd(self.ex(), [sys.executable, "-c", "print('hi')"], track_changes=False)
        self.assertEqual((ok.status, ok.exit_code), (RunStatus.PASSED, 0))
        self.assertIn("hi", Path(ok.stdout_ref).read_text())
        bad = self.run_cmd(self.ex(), [sys.executable, "-c", "raise SystemExit(4)"])
        self.assertEqual((bad.status, bad.exit_code), (RunStatus.FAILED, 4))

    def test_timeout_is_unknown_never_passed(self) -> None:
        code = "import time; time.sleep(10)"
        record = self.run_cmd(self.ex(), [sys.executable, "-c", code], timeout=0.5)
        self.assertEqual(record.status, RunStatus.UNKNOWN)
        self.assertTrue(record.timed_out)

    def test_missing_binary_is_blocked(self) -> None:
        record = self.run_cmd(self.ex(), ["definitely-not-a-binary-xyz"])
        self.assertEqual(record.status, RunStatus.BLOCKED)
        self.assertIn("definitely-not-a-binary-xyz", record.stderr_tail)

    def test_child_secret_is_redacted_in_log_files(self) -> None:
        code = f"import sys; print('{SECRET}'); print('{SECRET}', file=sys.stderr)"
        record = self.run_cmd(self.ex(), [sys.executable, "-c", code], track_changes=False)
        self.assertNotIn(SECRET, Path(record.stdout_ref).read_text())
        self.assertNotIn(SECRET, Path(record.stderr_ref).read_text())
        self.assertIn("[REDACTED]", record.stdout_tail)
        leaked = self.run_cmd(
            self.ex(lambda s: s), [sys.executable, "-c", code], track_changes=False
        )
        self.assertIn(SECRET, Path(leaked.stdout_ref).read_text())

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_changed_files_in_a_real_repo(self) -> None:
        ex = self.ex()
        self.run_cmd(ex, ["git", "init", "-q"], track_changes=False)
        code = "open('made.txt','w').write('x')"
        record = self.run_cmd(ex, [sys.executable, "-c", code])
        self.assertEqual(record.changed_files, ("made.txt",))


class ConversionTests(ExecutorBase):
    def test_to_evidence_and_guard_event(self) -> None:
        record = self.run_cmd(
            self.executor(FakeRunner(raw(2, out="o"))),
            ["pytest", "-q"],
            task_id="t1",
            track_changes=False,
        )
        with i18n.use_language("en"):
            evidence = to_evidence(record, EvidenceLabel.TESTED)
        self.assertEqual(evidence.label, EvidenceLabel.TESTED)
        self.assertEqual(evidence.exit_code, 2)
        self.assertEqual(evidence.ref, record.stdout_ref)
        self.assertIn("pytest -q", evidence.summary)
        event = to_guard_event(record, polling=True, flaky=True)
        self.assertEqual(event.kind, GuardEventKind.COMMAND)
        self.assertEqual((event.task_id, event.exit_code), ("t1", 2))
        self.assertTrue(event.polling and event.flaky)
        self.assertEqual(event.signature, command_signature(["pytest", "-q"], str(self.cwd)))
        self.assertEqual(event.at, record.started_at)


if __name__ == "__main__":
    unittest.main()
