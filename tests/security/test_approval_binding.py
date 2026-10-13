"""Grant binding, expiry, final denials and tamper evidence of the approval store."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wev_skills.core.contracts import RiskLevel
from wev_skills.governance.approvals import (
    DEFAULT_TTL_SECONDS,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
    approval_id,
)
from wev_skills.governance.audit import AuditLog

RM_BUILD = ("rm", "-rf", "build")


class ManualClock:
    def __init__(self) -> None:
        self.value = 1000.0

    def now(self) -> float:
        return self.value


class BindingCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.path = self.base / "state" / "approvals.json"
        self.audit_path = self.base / "state" / "audit.jsonl"
        self.clock = ManualClock()
        self.run = "run-1"
        self.store = self.make_store()
        self.here = str(self.base / "repo")
        (self.base / "repo" / "sub").mkdir(parents=True)

    def make_store(self, ttl: float = DEFAULT_TTL_SECONDS) -> ApprovalStore:
        return ApprovalStore(self.path, self.clock, ttl, run_lookup=lambda: self.run)

    def granted(self, cwd: str | None = None) -> ApprovalRequest:
        place = self.here if cwd is None else cwd
        record = self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=place)
        return self.store.grant(record.id, "ana", "/dev/ttys001")

    def events(self) -> list[str]:
        return [event["type"] for event in AuditLog(self.audit_path).read()]


class BindingTests(BindingCase):
    def test_a_grant_is_bound_to_the_working_directory(self) -> None:
        self.granted()
        other = str(self.base / "repo" / "sub")
        self.assertFalse(self.store.is_granted(RM_BUILD, other))
        self.assertFalse(self.store.consume(RM_BUILD, other))
        self.assertFalse(self.store.consume(RM_BUILD))
        self.assertTrue(self.store.consume(RM_BUILD, self.here))

    def test_the_directory_is_compared_resolved(self) -> None:
        (self.base / "link").symlink_to(self.base / "repo", target_is_directory=True)
        self.granted(str(self.base / "link"))
        self.assertTrue(self.store.consume(RM_BUILD, self.here + "/."))

    def test_a_grant_is_bound_to_the_run(self) -> None:
        self.granted()
        self.run = "run-2"
        self.assertFalse(self.store.is_granted(RM_BUILD, self.here))
        self.assertFalse(self.store.consume(RM_BUILD, self.here))

    def test_an_unreadable_run_state_honors_nothing(self) -> None:
        self.granted()
        store = ApprovalStore(self.path, self.clock, run_lookup=lambda: None)
        self.assertFalse(store.consume(RM_BUILD, self.here))

    def test_a_remote_grant_is_bound_to_the_host_alias(self) -> None:
        record = self.store.request("staging-1 rm -rf build", RiskLevel.HIGH, "r", "wev-remote")
        self.store.grant(record.id, "ana")
        self.assertFalse(self.store.consume("prod-1 rm -rf build"))
        self.assertFalse(self.store.consume(RM_BUILD))
        self.assertTrue(self.store.consume("staging-1 rm -rf build"))


class ExpiryTests(BindingCase):
    def test_a_grant_expires_after_the_ttl(self) -> None:
        record = self.granted()
        self.assertEqual(record.expires_at, 1000.0 + DEFAULT_TTL_SECONDS)
        self.clock.value += DEFAULT_TTL_SECONDS + 1
        self.assertFalse(self.store.is_granted(RM_BUILD, self.here))
        self.assertEqual(self.store.get(record.id).status, ApprovalStatus.EXPIRED)
        self.assertFalse(self.store.consume(RM_BUILD, self.here))
        self.assertIn("approval.expired", self.events())
        stored = json.loads(self.path.read_text())["approvals"][record.id]
        self.assertEqual(stored["status"], "expired")

    def test_the_ttl_is_configurable_and_an_expired_grant_can_be_asked_again(self) -> None:
        self.store = self.make_store(ttl=10)
        first = self.granted()
        self.clock.value += 11
        again = self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=self.here)
        self.assertEqual((again.status, again.generation), (ApprovalStatus.PENDING, 2))
        self.assertEqual(again.id, first.id)

    def test_a_grant_without_an_expiry_is_not_honored(self) -> None:
        record = self.granted()
        document = json.loads(self.path.read_text())
        document["approvals"][record.id]["expires_at"] = None
        self.path.write_text(json.dumps(document))
        self.assertFalse(self.store.consume(RM_BUILD, self.here))


class DenialTests(BindingCase):
    def denied(self) -> ApprovalRequest:
        record = self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=self.here)
        return self.store.deny(record.id, "ana", "/dev/ttys001")

    def test_a_denial_is_final_for_the_action_in_the_run(self) -> None:
        denied = self.denied()
        again = self.store.request(RM_BUILD, RiskLevel.LOW, "please", "agent-2", cwd=self.here)
        self.assertEqual(again, denied)
        self.assertTrue(self.store.is_denied(RM_BUILD, self.here))
        stored = json.loads(self.path.read_text())["approvals"][denied.id]
        self.assertEqual((stored["status"], stored["reason"]), ("denied", "cleanup"))

    def test_only_an_explicit_reopen_makes_a_fresh_request(self) -> None:
        denied = self.denied()
        fresh = self.store.request(
            RM_BUILD, RiskLevel.HIGH, "ok now", "operator", cwd=self.here, reopen_denied=True
        )
        self.assertEqual((fresh.status, fresh.generation), (ApprovalStatus.PENDING, 2))
        self.assertNotEqual(fresh.binding, denied.binding)
        self.assertIn("approval.reopened", self.events())
        self.assertFalse(self.store.is_granted(RM_BUILD, self.here))
        self.store.grant(fresh.id, "ana")
        self.assertTrue(self.store.consume(RM_BUILD, self.here))

    def test_a_denial_in_one_run_does_not_bind_the_next(self) -> None:
        self.denied()
        self.run = "run-2"
        self.assertFalse(self.store.is_denied(RM_BUILD, self.here))
        again = self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=self.here)
        self.assertEqual(again.status, ApprovalStatus.PENDING)


class TamperEvidenceTests(BindingCase):
    def forge(self, **fields: object) -> str:
        """Write a granted record by hand, as an agent with a file tool could."""
        self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=self.here)
        key = approval_id(RM_BUILD)
        document = json.loads(self.path.read_text())
        document["approvals"][key].update(
            {"status": "granted", "decided_by": "the-owner", "decided_at": 1.0, **fields}
        )
        document["approvals"][key]["expires_at"] = self.clock.value + 500
        self.path.write_text(json.dumps(document))
        return key

    def test_every_decision_is_in_the_audit_log(self) -> None:
        self.granted()
        self.store.consume(RM_BUILD, self.here)
        self.assertEqual(self.events(), ["approval.granted", "approval.consumed"])
        granted = AuditLog(self.audit_path).read()[0]["data"]
        self.assertEqual((granted["decided_by"], granted["decided_tty"]), ("ana", "/dev/ttys001"))
        self.assertEqual(granted["cwd"], self.here)

    def test_a_grant_written_straight_into_the_file_is_not_honored(self) -> None:
        key = self.forge()
        self.assertFalse(self.store.is_granted(RM_BUILD, self.here))
        self.assertFalse(self.store.consume(RM_BUILD, self.here))
        self.assertEqual(self.store.get(key).status, ApprovalStatus.GRANTED)
        self.assertIn("approval.unverified", self.events())
        problems = {(item.id, item.problem) for item in self.store.verify()}
        self.assertIn((key, "grant_not_in_audit"), problems)

    def test_a_real_grant_edited_to_another_directory_is_not_honored(self) -> None:
        record = self.granted()
        other = str(self.base / "repo" / "sub")
        document = json.loads(self.path.read_text())
        document["approvals"][record.id]["cwd"] = other
        self.path.write_text(json.dumps(document))
        self.assertFalse(self.store.consume(RM_BUILD, other))
        problems = {item.problem for item in self.store.verify()}
        self.assertIn("binding_mismatch", problems)

    def test_a_denial_overwritten_in_the_file_is_reported_and_not_honored(self) -> None:
        record = self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=self.here)
        self.store.deny(record.id, "ana")
        document = json.loads(self.path.read_text())
        document["approvals"][record.id].update(
            {"status": "granted", "expires_at": self.clock.value + 500}
        )
        self.path.write_text(json.dumps(document))
        self.assertFalse(self.store.consume(RM_BUILD, self.here))
        problems = {item.problem for item in self.store.verify()}
        self.assertTrue({"denial_overwritten", "grant_not_in_audit"} <= problems)

    def test_verify_is_clean_for_an_untouched_history(self) -> None:
        self.granted()
        self.store.consume(RM_BUILD, self.here)
        other = self.store.request(("rm", "-rf", "x"), RiskLevel.HIGH, "r", "agent")
        self.store.deny(other.id, "ana")
        self.assertEqual(self.store.verify(), ())

    def test_a_grant_event_without_a_record_is_reported(self) -> None:
        record = self.granted()
        self.path.write_text(json.dumps({"schema_version": 2, "approvals": {}}))
        problems = {(item.id, item.problem) for item in self.store.verify()}
        self.assertEqual(problems, {(record.id, "record_missing")})


if __name__ == "__main__":
    unittest.main()
