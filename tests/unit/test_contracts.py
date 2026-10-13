from __future__ import annotations

import dataclasses
import unittest

from wev_skills.core import contracts as c
from wev_skills.core import errors


def _samples() -> list[object]:
    evidence = c.Evidence("command", "ran", "log.txt", 0, c.EvidenceLabel.TESTED)
    return [
        c.TaskSignals("do it", files_touched_estimate=3, destructive=True, unknowns=2),
        c.Classification(c.Complexity.MODERATE, c.RiskLevel.HIGH, 0.4, False, ("a", "b"), "local"),
        c.Strategy(c.Flow.GATED, True, True, True, 2, 3, ("r",)),
        c.TaskContract(
            "t1",
            "obj",
            "ctx",
            ("src",),
            ("docs",),
            ("k",),
            ("ac",),
            ("make test",),
            "json",
            ("Read",),
            "agent",
            "model",
            c.RiskLevel.MEDIUM,
        ),
        evidence,
        c.TaskResult("t1", c.TaskStatus.VERIFIED, "ok", (evidence,), ("a.py",), ("b",)),
        c.Verdict(True, 0.9, ("good",), "local"),
        c.AttemptRecord("t1", 2, c.TaskStatus.FAILED, "m", "sig"),
        c.EscalationDecision(True, c.GuardAction.ESCALATE, ("loop",)),
        c.ModelChoice("m", "premium", ("risk",)),
        c.PermissionDecision(c.PermissionOutcome.NEEDS_APPROVAL, "why"),
        c.RawCommandResult(("echo", "x"), 0, "x\n", "", 5, False),
        c.PlanTask("a", "A", "do a", ("b",), ("f.py",), c.RiskLevel.HIGH, ("ac",), ("chk",), "h"),
        c.Plan("obj", (c.PlanTask("a", "A", "do a"),)),
    ]


class ContractRoundTripTests(unittest.TestCase):
    def test_every_contract_round_trips(self) -> None:
        for sample in _samples():
            with self.subTest(type=type(sample).__name__):
                data = sample.to_dict()  # type: ignore[attr-defined]
                self.assertEqual(type(sample).from_dict(data), sample)  # type: ignore[attr-defined]

    def test_tuples_serialize_as_lists_and_enums_as_strings(self) -> None:
        data = _samples()[1].to_dict()  # type: ignore[attr-defined]
        self.assertEqual(data["reasons"], ["a", "b"])
        self.assertEqual(data["risk"], "high")
        self.assertIs(type(data["risk"]), str)

    def test_nested_dataclasses_serialize_to_plain_dicts(self) -> None:
        data = _samples()[5].to_dict()  # type: ignore[attr-defined]
        self.assertIsInstance(data["evidence"][0], dict)
        self.assertEqual(data["evidence"][0]["label"], "tested")

    def test_defaults_apply_when_keys_omitted(self) -> None:
        signals = c.TaskSignals.from_dict({"objective": "x"})
        self.assertTrue(signals.has_tests)
        self.assertEqual(signals.independent_subtasks, 1)

    def test_unknown_key_is_rejected(self) -> None:
        with self.assertRaises(errors.ValidationError) as ctx:
            c.TaskSignals.from_dict({"objective": "x", "bogus": 1})
        self.assertEqual(ctx.exception.details["unknown"], ["bogus"])

    def test_unknown_key_in_nested_object_is_rejected(self) -> None:
        data = _samples()[5].to_dict()  # type: ignore[attr-defined]
        data["evidence"][0]["extra"] = True
        with self.assertRaises(errors.ValidationError):
            c.TaskResult.from_dict(data)

    def test_missing_required_field_is_rejected(self) -> None:
        with self.assertRaises(errors.ValidationError):
            c.TaskSignals.from_dict({})

    def test_bad_enum_value_is_rejected(self) -> None:
        with self.assertRaises(errors.ValidationError):
            data = _samples()[2].to_dict()  # type: ignore[attr-defined]
            c.Strategy.from_dict({**data, "flow": "sideways"})

    def test_wrong_scalar_types_are_rejected(self) -> None:
        for bad in (
            {"objective": 5},
            {"objective": "x", "unknowns": True},
            {"objective": "x", "has_tests": "yes"},
        ):
            with self.subTest(bad=bad), self.assertRaises(errors.ValidationError):
                c.TaskSignals.from_dict(bad)

    def test_list_field_must_be_a_list(self) -> None:
        with self.assertRaises(errors.ValidationError):
            c.Verdict.from_dict({"accepted": True, "score": 1, "reasons": "oops"})

    def test_uncertainty_out_of_range_is_rejected(self) -> None:
        with self.assertRaises(errors.ValidationError):
            c.Classification(c.Complexity.SIMPLE, c.RiskLevel.LOW, 1.5, True, (), "x")

    def test_contracts_are_frozen(self) -> None:
        verdict = c.Verdict(True, 1.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            verdict.accepted = False  # type: ignore[misc]

    def test_enum_values_match_architecture(self) -> None:
        self.assertEqual([m.value for m in c.RiskLevel], ["low", "medium", "high"])
        self.assertEqual(c.Mode("auto"), c.Mode.AUTO)
        self.assertEqual(len(c.TaskStatus), 8)
        self.assertEqual(len(c.GuardAction), 6)


class ErrorTests(unittest.TestCase):
    def test_exit_codes_match_architecture_section_6(self) -> None:
        expected = {
            errors.ValidationError: 2,
            errors.PermissionDenied: 3,
            errors.ApprovalRequired: 4,
            errors.StateConflict: 5,
            errors.GuardTripped: 6,
            errors.NotFound: 7,
            errors.RemoteError: 8,
            errors.ProviderError: 8,
            errors.WevError: 1,
        }
        for cls, code in expected.items():
            self.assertEqual(cls.exit_code, code, cls.__name__)

    def test_error_carries_code_message_details(self) -> None:
        err = errors.NotFound("nf", "missing", {"k": 1})
        self.assertEqual(err.to_dict(), {"code": "nf", "message": "missing", "details": {"k": 1}})
        self.assertEqual(str(err), "missing")
        self.assertEqual(errors.WevError("c", "m").details, {})


if __name__ == "__main__":
    unittest.main()
