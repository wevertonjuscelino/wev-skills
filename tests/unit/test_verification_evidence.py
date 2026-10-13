"""What counts as evidence: tied checks, generic checks, no-ops and checks that already passed."""

from __future__ import annotations

from dataclasses import replace

from tests.unit.test_verification_engine import EngineBase, contract, status_of
from wev_skills.core.contracts import CheckLink, Mode
from wev_skills.verification.engine import (
    SUPPORT_MANUAL,
    SUPPORT_NONE,
    SUPPORT_TIED,
    SUPPORT_UNTIED,
    CriterionStatus,
    VerificationReport,
    checks_from_contract,
)

MET, UNMET, UNVERIFIED = CriterionStatus.MET, CriterionStatus.UNMET, CriterionStatus.UNVERIFIED


def support_of(report: VerificationReport) -> dict[str, str]:
    return {c.criterion: c.support for c in report.criteria}


class EvidenceBase(EngineBase):
    def run_contract(self, task, script=None, **kw):  # type: ignore[no-untyped-def]
        engine, _ = self.engine(script or {})
        checks = checks_from_contract(task)
        return engine.verify(task, checks, str(self.root), Mode.EXECUTE, **kw)


class TiedCheckTests(EvidenceBase):
    def test_an_object_check_supports_only_the_criteria_it_names(self) -> None:
        task = replace(
            contract(("A", "B"), ("unit", "lint")),
            check_links=(CheckLink("unit", ("A",)), CheckLink("lint", ("B",))),
        )
        report = self.run_contract(task, {"lint": (1, "")}, stop_on_failure=False)
        self.assertEqual(status_of(report), {"A": MET, "B": UNMET})
        self.assertEqual(support_of(report)["A"], SUPPORT_TIED)
        self.assertEqual(report.warnings, ())

    def test_a_criterion_no_check_is_tied_to_stays_unverified(self) -> None:
        task = replace(contract(("A", "B"), ("unit",)), check_links=(CheckLink("unit", ("A",)),))
        report = self.run_contract(task)
        self.assertEqual(status_of(report), {"A": MET, "B": UNVERIFIED})
        self.assertEqual(support_of(report)["B"], SUPPORT_NONE)
        self.assertFalse(report.all_met)

    def test_plain_string_checks_are_labeled_untied_and_warn_on_several_criteria(self) -> None:
        report = self.run_contract(contract(("A", "B"), ("unit",)))
        self.assertEqual(status_of(report), {"A": MET, "B": MET})
        self.assertEqual(set(support_of(report).values()), {SUPPORT_UNTIED})
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("no check is tied", report.warnings[0])

    def test_a_single_criterion_with_an_untied_check_does_not_warn(self) -> None:
        report = self.run_contract(contract(("A",), ("unit",)))
        self.assertEqual(support_of(report), {"A": SUPPORT_UNTIED})
        self.assertEqual(report.warnings, ())


class TrivialCheckTests(EvidenceBase):
    def test_criteria_supported_only_by_no_ops_are_unverified(self) -> None:
        report = self.run_contract(contract(("A",), ("true", "echo done")))
        self.assertEqual(status_of(report), {"A": UNVERIFIED})
        self.assertFalse(report.all_met)
        self.assertTrue(
            all(check.trivial for check in checks_from_contract(contract(("A",), ("true",))))
        )
        self.assertIn("no evidence", report.criteria[0].reason)

    def test_a_real_check_next_to_a_no_op_still_counts(self) -> None:
        report = self.run_contract(contract(("A",), ("true", "unit")))
        self.assertEqual(status_of(report), {"A": MET})

    def test_a_failing_real_check_wins_over_everything(self) -> None:
        report = self.run_contract(contract(("A",), ("true", "unit")), {"unit": (1, "")})
        self.assertEqual(status_of(report), {"A": UNMET})


class BaselineTests(EvidenceBase):
    def test_checks_that_passed_before_any_work_show_nothing(self) -> None:
        report = self.run_contract(
            contract(("A", "B"), ("unit",)), baseline_passed=("unit",), tree_unchanged=True
        )
        self.assertEqual(status_of(report), {"A": UNVERIFIED, "B": UNVERIFIED})
        self.assertFalse(report.all_met)
        self.assertIn("before any work", report.criteria[0].reason)

    def test_a_changed_tree_makes_the_same_checks_count(self) -> None:
        report = self.run_contract(
            contract(("A",), ("unit",)), baseline_passed=("unit",), tree_unchanged=False
        )
        self.assertTrue(report.all_met)

    def test_a_check_that_failed_at_baseline_counts_even_on_an_unchanged_tree(self) -> None:
        report = self.run_contract(
            contract(("A",), ("unit",)), baseline_passed=(), tree_unchanged=True
        )
        self.assertTrue(report.all_met)

    def test_without_a_baseline_the_rule_does_not_apply(self) -> None:
        report = self.run_contract(contract(("A",), ("unit",)), tree_unchanged=True)
        self.assertTrue(report.all_met)


class RequiredCheckTests(EvidenceBase):
    def test_a_required_check_must_pass_but_is_not_evidence_by_itself(self) -> None:
        only_required = replace(contract(("A",), ("gate",)), required_checks=("gate",))
        self.assertEqual(status_of(self.run_contract(only_required)), {"A": UNVERIFIED})
        both = replace(contract(("A",), ("unit", "gate")), required_checks=("gate",))
        self.assertEqual(status_of(self.run_contract(both)), {"A": MET})
        failing = self.run_contract(both, {"gate": (1, "")}, stop_on_failure=False)
        self.assertEqual(status_of(failing), {"A": UNMET})


class ManualEvidenceTests(EvidenceBase):
    def test_manual_evidence_is_labeled_as_such(self) -> None:
        from wev_skills.core.contracts import Evidence, EvidenceLabel

        manual = [Evidence("A", "seen by hand", "notes.txt", label=EvidenceLabel.TESTED)]
        report = self.run_contract(contract(("A",), ()), manual_evidence=manual)
        self.assertEqual(status_of(report), {"A": MET})
        self.assertEqual(support_of(report), {"A": SUPPORT_MANUAL})


if __name__ == "__main__":
    import unittest

    unittest.main()
