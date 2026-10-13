from __future__ import annotations

import json
import stat
import tempfile
import threading
import unittest
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import NotFound, PermissionDenied, StateConflict, ValidationError
from wev_skills.governance.approvals import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
    action_hash,
    approval_id,
    normalize_action,
)

RM_BUILD = ("rm", "-rf", "build")
SECRET = "example_" + "Hunter2" * 3


class TickingClock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        self.value += 1.0
        return self.value


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state" / "approvals.json"
        self.clock = TickingClock()
        self.store = ApprovalStore(self.path, self.clock)

    def request(self, action: object = RM_BUILD, **kwargs: object) -> ApprovalRequest:
        risk = RiskLevel.HIGH
        args = (action, risk, "cleanup", "agent-1")
        return self.store.request(*args, **kwargs)  # type: ignore[arg-type]

    def granted(self, action: object = RM_BUILD, **kwargs: object) -> ApprovalRequest:
        return self.store.grant(self.request(action, **kwargs).id, "ana")


class ActionIdentityTests(unittest.TestCase):
    def test_id_is_stable_and_derived_from_the_normalized_action(self) -> None:
        self.assertEqual(approval_id(RM_BUILD), approval_id(list(RM_BUILD)))
        self.assertEqual(approval_id("rm -rf build"), approval_id(RM_BUILD))
        self.assertEqual(approval_id("  rm   -rf  'build' "), approval_id(RM_BUILD))
        self.assertTrue(approval_id(RM_BUILD).startswith("apr-"))
        self.assertEqual(approval_id(RM_BUILD)[4:], action_hash(RM_BUILD)[:16])

    def test_any_different_argument_is_a_different_action(self) -> None:
        variants = (
            ("rm", "-rf", "src"),
            ("rm", "-rf", "build", "src"),
            ("rm", "-rf", "build/"),
            ("rm", "-rf"),
            ("rm", "-fr", "build"),
            ("/bin/rm", "-rf", "build"),
            ("rm", "-rf", "Build"),
            ("rm", "-rf", "build "),
            ("rm", "-rf build"),
            ("rm -rf build",),
            ("rm", "-rf", "", "build"),
            ("sudo", *RM_BUILD),
        )
        ids = {approval_id(variant) for variant in variants}
        self.assertEqual(len(ids), len(variants))
        self.assertNotIn(approval_id(RM_BUILD), ids)

    def test_token_boundaries_cannot_be_forged_with_separators(self) -> None:
        self.assertNotEqual(action_hash(("a", "b")), action_hash(("a b",)))
        self.assertNotEqual(action_hash(("a", "b")), action_hash(('a","b',)))
        self.assertNotEqual(action_hash(("a,b",)), action_hash(("a", "b")))

    def test_empty_or_invalid_actions_are_rejected(self) -> None:
        for action in ("", "   ", (), [""], ["rm", 3]):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                normalize_action(action)  # type: ignore[arg-type]

    def test_unbalanced_string_is_kept_as_one_token(self) -> None:
        self.assertEqual(normalize_action("deploy 'prod"), ("deploy 'prod",))


class RequestTests(StoreCase):
    def test_request_creates_a_pending_record_and_persists_it(self) -> None:
        record = self.request()
        self.assertEqual(record.status, ApprovalStatus.PENDING)
        self.assertEqual((record.action, record.risk), ("rm -rf build", RiskLevel.HIGH))
        self.assertEqual((record.requested_by, record.requested_at), ("agent-1", 101.0))
        self.assertEqual(ApprovalStore(self.path).get(record.id), record)
        document = json.loads(self.path.read_text())
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(list(document["approvals"]), [record.id])

    def test_same_action_is_not_requested_twice_while_pending_or_granted(self) -> None:
        first = self.request()
        again = self.store.request("rm -rf build", RiskLevel.LOW, "other", "agent-2")
        self.assertEqual(again, first)
        self.assertEqual(len(self.store.list()), 1)
        granted = self.store.grant(first.id, "ana")
        self.assertEqual(self.request(), granted)

    def test_a_new_request_after_use_starts_pending_again(self) -> None:
        first = self.granted()
        self.assertTrue(self.store.consume(RM_BUILD))
        second = self.request()
        self.assertEqual((second.id, second.status), (first.id, ApprovalStatus.PENDING))
        self.assertEqual((second.decided_by, second.generation), ("", 2))
        self.assertFalse(self.store.is_granted(RM_BUILD))

    def test_reason_and_requester_are_redacted_before_storage(self) -> None:
        record = self.store.request(
            ("curl", "https://e.example"),
            RiskLevel.MEDIUM,
            f"needs password={SECRET}",
            f"agent token={SECRET}",
        )
        self.assertNotIn(SECRET, self.path.read_text())
        self.assertNotIn(SECRET, json.dumps(record.to_dict()))
        self.assertIn("[REDACTED]", record.reason)

    def test_an_action_that_redaction_would_alter_is_refused_not_filed(self) -> None:
        for action in (
            ("curl", "-H", f"Authorization: Bearer {SECRET}", "https://e.example"),
            ("deploy", "--token=" + SECRET),
            ("deploy", "--password", SECRET),
            ("sh", "-c", 'token="x"; rm -rf sub'),
        ):
            with self.subTest(action=action[:2]), self.assertRaises(PermissionDenied) as caught:
                self.request(action)
            self.assertEqual(caught.exception.code, "secret_in_action")
            self.assertNotIn(SECRET, caught.exception.message)
        self.assertFalse(self.path.exists())

    def test_invalid_risk_is_a_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.request(RM_BUILD, "high", "r", "agent")  # type: ignore[arg-type]


class DecisionTests(StoreCase):
    def test_grant_records_who_and_when(self) -> None:
        record = self.granted()
        self.assertEqual(record.status, ApprovalStatus.GRANTED)
        self.assertEqual((record.decided_by, record.decided_at), ("ana", 102.0))
        self.assertTrue(self.store.is_granted(RM_BUILD))
        self.assertTrue(ApprovalStore(self.path, self.clock).is_granted("rm -rf build"))

    def test_grant_for_one_argv_does_not_cover_another(self) -> None:
        self.granted()
        for other in (
            ("rm", "-rf", "src"),
            ("rm", "-rf", "build", "/"),
            ("rm", "-rf"),
            ("/bin/rm", "-rf", "build"),
            ("rm", "-rf", "build/"),
            "rm -rf  build .",
        ):
            with self.subTest(other=other):
                self.assertFalse(self.store.is_granted(other))
                self.assertFalse(self.store.consume(other))
        self.assertTrue(self.store.is_granted(RM_BUILD))

    def test_single_use_grant_is_consumed_once(self) -> None:
        record = self.granted()
        self.assertTrue(self.store.consume(RM_BUILD))
        self.assertFalse(self.store.consume(RM_BUILD))
        self.assertFalse(self.store.is_granted(RM_BUILD))
        used = self.store.get(record.id)
        self.assertEqual(used.status, ApprovalStatus.CONSUMED)
        self.assertIsNotNone(used.used_at)

    def test_there_is_no_reusable_grant(self) -> None:
        with self.assertRaises(TypeError):
            self.request(reusable=True)
        self.assertNotIn("reusable", ApprovalRequest.__dataclass_fields__)

    def test_concurrent_consumers_share_one_grant_exactly_once(self) -> None:
        self.granted()
        results: list[bool] = []

        def use() -> None:
            results.append(ApprovalStore(self.path, self.clock).consume(RM_BUILD))

        workers = [threading.Thread(target=use) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(sorted(results), [False] * 7 + [True])

    def test_pending_and_denied_are_not_granted(self) -> None:
        record = self.request()
        self.assertFalse(self.store.is_granted(RM_BUILD))
        self.assertFalse(self.store.consume(RM_BUILD))
        denied = self.store.deny(record.id, "ana")
        self.assertEqual((denied.status, denied.decided_by), (ApprovalStatus.DENIED, "ana"))
        self.assertFalse(self.store.is_granted(RM_BUILD))

    def test_deny_revokes_an_unused_grant(self) -> None:
        record = self.granted()
        self.store.deny(record.id, "bia")
        self.assertFalse(self.store.consume(RM_BUILD))

    def test_decisions_only_apply_to_the_right_states(self) -> None:
        record = self.granted()
        with self.assertRaises(StateConflict):
            self.store.grant(record.id, "bia")
        self.store.deny(record.id, "ana")
        for decide in (self.store.grant, self.store.deny):
            with self.subTest(decide=decide.__name__), self.assertRaises(StateConflict):
                decide(record.id, "ana")
        self.assertEqual(self.store.get(record.id).status, ApprovalStatus.DENIED)

    def test_names_are_not_compared_and_the_user_and_terminal_are_recorded(self) -> None:
        record = self.request()
        granted = self.store.grant(record.id, "agent-1", "/dev/ttys009")
        self.assertEqual(granted.status, ApprovalStatus.GRANTED)
        self.assertEqual((granted.decided_by, granted.decided_tty), ("agent-1", "/dev/ttys009"))
        self.assertEqual(granted.decided_at, 102.0)

    def test_decider_is_required(self) -> None:
        record = self.request()
        for decide in (self.store.grant, self.store.deny):
            for name in ("", "   "):
                with self.subTest(decide=decide.__name__), self.assertRaises(ValidationError):
                    decide(record.id, name)

    def test_unknown_id_is_not_found_with_a_localized_message(self) -> None:
        for call in (
            self.store.get,
            lambda i: self.store.grant(i, "ana"),
            lambda i: self.store.deny(i, "ana"),
        ):
            with self.assertRaises(NotFound):
                call("apr-missing")
        with i18n.use_language("pt-BR"), self.assertRaises(NotFound) as caught:
            self.store.get("apr-missing")
        self.assertIn("Não existe", caught.exception.message)


class ListingAndStorageTests(StoreCase):
    def test_list_is_ordered_and_filters_by_status(self) -> None:
        first = self.request(("a",))
        second = self.granted(("b",))
        third = self.request(("c",))
        self.assertEqual([r.id for r in self.store.list()], [first.id, second.id, third.id])
        pending = self.store.list(ApprovalStatus.PENDING)
        self.assertEqual([r.id for r in pending], [first.id, third.id])
        self.assertEqual([r.id for r in self.store.list(ApprovalStatus.GRANTED)], [second.id])
        self.assertEqual(self.store.list(ApprovalStatus.CONSUMED), ())

    def test_missing_file_means_no_approvals(self) -> None:
        self.assertEqual(self.store.list(), ())
        self.assertFalse(self.store.is_granted(RM_BUILD))
        self.assertFalse(self.store.consume(RM_BUILD))
        self.assertFalse(self.path.exists())

    def test_file_is_private_and_written_atomically(self) -> None:
        self.request()
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_corrupt_file_fails_closed(self) -> None:
        self.request()
        for content in ("{not json", "[]", '{"approvals": []}', '{"approvals": {"x": {"id": 1}}}'):
            self.path.write_text(content)
            for call in (
                lambda: self.store.is_granted(RM_BUILD),
                lambda: self.store.consume(RM_BUILD),
                self.store.list,
                self.request,
            ):
                with self.subTest(content=content), self.assertRaises(ValidationError):
                    call()

    def test_a_forged_status_does_not_survive_strict_decoding(self) -> None:
        record = self.request()
        document = json.loads(self.path.read_text())
        document["approvals"][record.id]["status"] = "approved"
        self.path.write_text(json.dumps(document))
        with self.assertRaises(ValidationError):
            self.store.is_granted(RM_BUILD)


if __name__ == "__main__":
    unittest.main()
