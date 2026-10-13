from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import (
    Evidence,
    EvidenceLabel,
    Mode,
    PermissionDecision,
    PermissionOutcome,
    RawCommandResult,
    RiskLevel,
    TaskContract,
    TaskStatus,
)
from wev_skills.core.errors import ValidationError
from wev_skills.execution import CommandExecutor
from wev_skills.verification import (
    Check,
    CheckState,
    CriterionStatus,
    VerificationEngine,
    VerificationReport,
    build_result,
    checks_from_contract,
)

CRITERIA = ("A", "B")


def contract(criteria: Sequence[str] = CRITERIA, checks: Sequence[str] = ()) -> TaskContract:
    return TaskContract(
        "t1",
        "obj",
        "",
        (),
        (),
        (),
        tuple(criteria),
        tuple(checks),
        "",
        (),
        "agent",
        "model",
        RiskLevel.LOW,
    )


class ScriptedGate:
    def __init__(self, refused: Mapping[str, PermissionOutcome] | None = None) -> None:
        self.refused = dict(refused or {})

    def check_command(self, argv, cwd, mode, risk):  # type: ignore[no-untyped-def]
        outcome = self.refused.get(argv[0], PermissionOutcome.ALLOW)
        return PermissionDecision(outcome, f"gate said {outcome.value}")


class ScriptedRunner:
    """Maps argv[0] to (exit_code, timed_out | 'missing')."""

    def __init__(self, script: Mapping[str, tuple[int | None, str]]) -> None:
        self.script = dict(script)
        self.ran: list[str] = []

    def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
        name = argv[0]
        self.ran.append(name)
        code, mode = self.script.get(name, (0, ""))
        if mode == "timeout":
            return RawCommandResult(tuple(argv), None, "", "", 1, True)
        if mode == "missing":
            err = f"FileNotFoundError: [Errno 2] No such file or directory: '{name}'"
            return RawCommandResult(tuple(argv), 127, "", err, 1)
        return RawCommandResult(tuple(argv), code, f"out {name}", "", 1)


class EngineBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def engine(
        self,
        script: Mapping[str, tuple[int | None, str]] | None = None,
        gate: ScriptedGate | None = None,
    ) -> tuple[VerificationEngine, ScriptedRunner]:
        runner = ScriptedRunner(script or {})
        executor = CommandExecutor(gate or ScriptedGate(), runner, self.root / "logs")
        return VerificationEngine(executor), runner

    def verify(self, engine: VerificationEngine, checks: Sequence[Check], **kw: object):  # type: ignore[no-untyped-def]
        return engine.verify(contract(), checks, str(self.root), Mode.EXECUTE, **kw)  # type: ignore[arg-type]


def chk(name: str, cost: int = 10, criteria: Sequence[str] = CRITERIA) -> Check:
    return Check(name, (name,), cost, tuple(criteria))


def status_of(report: VerificationReport) -> dict[str, CriterionStatus]:
    return {c.criterion: c.status for c in report.criteria}


class OrderingAndStoppingTests(EngineBase):
    def test_cheapest_first(self) -> None:
        engine, runner = self.engine()
        self.verify(engine, [chk("slow", 50), chk("fast", 1), chk("mid", 20)])
        self.assertEqual(runner.ran, ["fast", "mid", "slow"])

    def test_stop_on_failure_lists_unexecuted(self) -> None:
        engine, runner = self.engine({"lint": (1, "")})
        report = self.verify(engine, [chk("lint", 1), chk("unit", 2), chk("e2e", 3)])
        self.assertEqual(runner.ran, ["lint"])
        self.assertEqual(report.unexecuted_checks, ("unit", "e2e"))
        self.assertEqual(set(status_of(report).values()), {CriterionStatus.UNMET})

    def test_without_stop_everything_runs(self) -> None:
        engine, runner = self.engine({"lint": (1, "")})
        report = self.verify(engine, [chk("lint", 1), chk("unit", 2)], stop_on_failure=False)
        self.assertEqual(runner.ran, ["lint", "unit"])
        self.assertEqual(report.unexecuted_checks, ())


class CriterionTests(EngineBase):
    def test_all_passing_is_met(self) -> None:
        engine, _ = self.engine()
        report = self.verify(engine, [chk("a"), chk("b")])
        self.assertTrue(report.all_met)
        self.assertEqual(set(status_of(report).values()), {CriterionStatus.MET})
        self.assertTrue(all(c.evidence_refs for c in report.criteria))

    def test_failure_makes_only_its_criteria_unmet(self) -> None:
        engine, _ = self.engine({"bad": (1, "")})
        report = self.verify(engine, [chk("good", 1, ["A"]), chk("bad", 2, ["B"])])
        self.assertEqual(status_of(report), {"A": CriterionStatus.MET, "B": CriterionStatus.UNMET})
        self.assertFalse(report.all_met)

    def test_unexecuted_supporting_check_blocks_met(self) -> None:
        engine, _ = self.engine({"bad": (1, "")})
        report = self.verify(
            engine, [chk("good", 1, ["A"]), chk("bad", 2, ["B"]), chk("later", 3, ["A"])]
        )
        self.assertEqual(status_of(report)["A"], CriterionStatus.UNVERIFIED)

    def test_no_supporting_check_is_unverified(self) -> None:
        engine, _ = self.engine()
        report = self.verify(engine, [chk("only-a", 1, ["A"])])
        self.assertEqual(status_of(report)["B"], CriterionStatus.UNVERIFIED)
        self.assertFalse(report.all_met)

    def test_timeout_and_missing_binary_are_unverified_never_met(self) -> None:
        for mode, state in (("timeout", CheckState.INCONCLUSIVE), ("missing", CheckState.BLOCKED)):
            engine, _ = self.engine({"x": (None, mode)})
            report = self.verify(engine, [chk("x")])
            self.assertEqual(report.checks[0].state, state)
            self.assertEqual(set(status_of(report).values()), {CriterionStatus.UNVERIFIED})

    def test_passing_check_plus_timed_out_check_is_not_met(self) -> None:
        engine, _ = self.engine({"slow": (None, "timeout")})
        report = self.verify(engine, [chk("ok", 1), chk("slow", 2)])
        self.assertEqual(set(status_of(report).values()), {CriterionStatus.UNVERIFIED})

    def test_gate_refusal_is_unverified_with_reason_not_a_crash(self) -> None:
        for outcome in (PermissionOutcome.DENY, PermissionOutcome.NEEDS_APPROVAL):
            engine, runner = self.engine(gate=ScriptedGate({"x": outcome}))
            report = self.verify(engine, [chk("x")])
            self.assertEqual(runner.ran, [])
            self.assertEqual(report.checks[0].state, CheckState.REFUSED)
            self.assertIn("gate said", report.checks[0].reason)
            self.assertEqual(set(status_of(report).values()), {CriterionStatus.UNVERIFIED})

    def test_zero_criteria_is_never_all_met(self) -> None:
        engine, _ = self.engine()
        with i18n.use_language("en"):
            report = engine.verify(contract(()), [chk("a")], str(self.root), Mode.EXECUTE)
        self.assertFalse(report.all_met)
        self.assertIn("no acceptance criteria", report.summary)

    def test_report_round_trips(self) -> None:
        engine, _ = self.engine({"bad": (1, "")})
        report = self.verify(engine, [chk("good", 1), chk("bad", 2), chk("never", 3)])
        again = VerificationReport.from_dict(json.loads(json.dumps(report.to_dict())))
        self.assertEqual(again, report)


class ManualEvidenceTests(EngineBase):
    def test_tested_evidence_with_ref_marks_met(self) -> None:
        engine, _ = self.engine()
        manual = [Evidence("A", "checked by hand", "notes/a.txt", None, EvidenceLabel.TESTED)]
        report = self.verify(engine, [chk("b", 1, ["B"])], manual_evidence=manual)
        self.assertEqual(status_of(report)["A"], CriterionStatus.MET)
        self.assertIn("notes/a.txt", report.criteria[0].evidence_refs)
        self.assertTrue(report.all_met)

    def test_note_without_ref_or_wrong_label_does_not(self) -> None:
        engine, _ = self.engine()
        for ev in (
            Evidence("A", "trust me", "", None, EvidenceLabel.TESTED),
            Evidence("A", "doc", "docs/a.md", None, EvidenceLabel.DOCUMENTED_ONLY),
        ):
            report = self.verify(engine, [chk("b", 1, ["B"])], manual_evidence=[ev])
            self.assertEqual(status_of(report)["A"], CriterionStatus.UNVERIFIED)

    def test_manual_evidence_cannot_override_a_failed_check(self) -> None:
        engine, _ = self.engine({"a": (1, "")})
        manual = [Evidence("A", "hand", "n.txt", None, EvidenceLabel.TESTED)]
        report = self.verify(engine, [chk("a", 1, ["A"])], manual_evidence=manual)
        self.assertEqual(status_of(report)["A"], CriterionStatus.UNMET)


class ChecksFromContractTests(unittest.TestCase):
    def test_parses_with_shlex_and_supports_all_criteria(self) -> None:
        checks = checks_from_contract(contract(checks=["pytest -k 'a b'", "ruff check ."]))
        self.assertEqual(checks[0].argv, ("pytest", "-k", "a b"))
        self.assertEqual(checks[0].criteria, CRITERIA)
        self.assertEqual([c.id for c in checks], ["check-1", "check-2"])

    def test_cost_heuristic_orders_lint_unit_integration_e2e(self) -> None:
        cmds = [
            "npm run e2e",
            "pytest tests/integration",
            "python -m unittest tests/unit",
            "ruff check src",
            "mypy src",
            "npx playwright test",
            "run end-to-end suite",
        ]
        costs = [c.cost for c in checks_from_contract(contract(checks=cmds))]
        lint, typecheck, unit, integ = costs[3], costs[4], costs[2], costs[1]
        self.assertLess(lint, unit)
        self.assertLess(typecheck, unit)
        self.assertLess(unit, integ)
        self.assertLess(unit, costs[0])
        self.assertLess(integ, costs[0])
        self.assertEqual({costs[0], costs[5], costs[6]}, {max(costs)})

    def test_unparseable_or_blank_command_raises_validation_error(self) -> None:
        for bad in ("echo 'unterminated", "   "):
            with self.assertRaises(ValidationError):
                checks_from_contract(contract(checks=[bad]))


class BuildResultTests(EngineBase):
    def result(self, script, checks, criteria=CRITERIA, **kw):  # type: ignore[no-untyped-def]
        engine, _ = self.engine(script, kw.pop("gate", None))
        c = contract(criteria)
        report = engine.verify(c, checks, str(self.root), Mode.EXECUTE, **kw)
        return build_result(c, report, ["f.py"]), report

    def test_verified(self) -> None:
        result, _ = self.result({}, [chk("a")])
        self.assertEqual(result.status, TaskStatus.VERIFIED)
        self.assertEqual(result.changed_files, ("f.py",))
        self.assertEqual(result.evidence[0].label, EvidenceLabel.TESTED)
        self.assertEqual(result.blockers, ())

    def test_failed_beats_everything(self) -> None:
        result, _ = self.result({"a": (1, "")}, [chk("a", 1, ["A"]), chk("b", 2, ["B"])])
        self.assertEqual(result.status, TaskStatus.FAILED)
        labels = {e.label for e in result.evidence}
        self.assertEqual(labels, {EvidenceLabel.TESTED, EvidenceLabel.UNTESTED})
        self.assertEqual(len(result.blockers), 2)

    def test_partial_when_some_met_and_rest_unverified(self) -> None:
        result, _ = self.result({}, [chk("a", 1, ["A"])])
        self.assertEqual(result.status, TaskStatus.PARTIAL)

    def test_blocked_when_nothing_could_run(self) -> None:
        gate = ScriptedGate({"a": PermissionOutcome.DENY})
        result, _ = self.result({}, [chk("a")], gate=gate)
        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.evidence[0].label, EvidenceLabel.BLOCKED)

    def test_blocked_when_only_timeouts_and_missing_binaries(self) -> None:
        result, _ = self.result({"a": (None, "timeout")}, [chk("a")])
        self.assertEqual(result.status, TaskStatus.BLOCKED)
        self.assertEqual(result.evidence[0].label, EvidenceLabel.UNTESTED)
        missing, _ = self.result({"a": (None, "missing")}, [chk("a")])
        self.assertEqual(missing.evidence[0].label, EvidenceLabel.BLOCKED)

    def test_no_criteria_never_verified(self) -> None:
        result, _ = self.result({}, [chk("a")], criteria=())
        self.assertNotEqual(result.status, TaskStatus.VERIFIED)


if __name__ == "__main__":
    unittest.main()
