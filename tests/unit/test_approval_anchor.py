from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.unit._orchestrator_helpers import OrchestratorCase
from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import ApprovalRequired
from wev_skills.governance.approval_anchor import Anchor, needs_anchor
from wev_skills.governance.approvals import ApprovalRequest, ApprovalStatus, ApprovalStore
from wev_skills.governance.audit import AuditLog

PUSH = ("git", "push", "origin", "dev")
RM_BUILD = ("rm", "-r", "build")


class TickingClock:
    def __init__(self) -> None:
        self.value = 100.0

    def now(self) -> float:
        self.value += 1.0
        return self.value


class MovableAnchor:
    """A repository whose ``HEAD`` and tree the test moves by hand."""

    def __init__(self) -> None:
        self.head = "c1"
        self.tree = "t1"
        self.reads = 0

    def __call__(self) -> Anchor:
        self.reads += 1
        return Anchor(head=self.head, tree=self.tree)


class AnchoredGrantTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = MovableAnchor()
        path = Path(tmp.name) / "state" / "approvals.json"
        self.path = path
        self.audit = AuditLog(path.with_name("audit.jsonl"))
        self.store = ApprovalStore(path, TickingClock(), audit=self.audit, anchor=self.repo)

    def granted(self, action: tuple[str, ...]) -> ApprovalRequest:
        record = self.store.request(action, RiskLevel.HIGH, "ship", "agent-1")
        return self.store.grant(record.id, "ana")

    def test_push_grant_records_head_and_tree(self) -> None:
        record = self.granted(PUSH)
        self.assertEqual((record.head, record.tree), ("c1", "t1"))
        self.assertTrue(self.store.is_granted(PUSH))
        self.assertFalse(self.store.is_stale(PUSH))
        self.repo.reads = 0
        self.assertTrue(self.store.consume(PUSH))
        self.assertEqual(self.repo.reads, 1)  # git runs once under the lock, not per check

    def test_push_grant_goes_stale_on_new_commit(self) -> None:
        self.granted(PUSH)
        self.repo.head = "c2"
        self.assertFalse(self.store.is_granted(PUSH))
        self.assertTrue(self.store.is_stale(PUSH))
        self.assertFalse(self.store.consume(PUSH))
        kinds = [event["type"] for event in self.audit.read()]
        self.assertNotIn("approval.unverified", kinds)  # stale is not tampering

    def test_push_grant_goes_stale_on_tree_change(self) -> None:
        self.granted(PUSH)
        self.repo.tree = "t2"
        self.assertFalse(self.store.is_granted(PUSH))
        self.assertTrue(self.store.is_stale(PUSH))

    def test_a_stale_grant_waits_for_a_fresh_grant(self) -> None:
        first = self.granted(PUSH)
        self.repo.tree = "t2"
        again = self.store.request(PUSH, RiskLevel.HIGH, "ship", "agent-1")
        self.assertEqual((again.id, again.status), (first.id, ApprovalStatus.PENDING))
        regranted = self.store.grant(again.id, "ana")
        self.assertEqual((regranted.head, regranted.tree), ("c1", "t2"))
        self.assertFalse(self.store.is_stale(PUSH))
        self.assertTrue(self.store.consume(PUSH))

    def blank_anchor(self, record: ApprovalRequest) -> None:
        """Rewrite the stored grant with ``head`` and ``tree`` emptied, as a hand edit would."""
        document = json.loads(self.path.read_text(encoding="utf-8"))
        document["approvals"][record.id].update(head="", tree="")
        self.path.write_text(json.dumps(document), encoding="utf-8")

    def test_a_blanked_anchor_is_not_usable_and_verify_reports_it(self) -> None:
        self.blank_anchor(self.granted(PUSH))
        self.assertFalse(self.store.is_granted(PUSH))
        self.assertTrue(self.store.is_stale(PUSH))
        self.assertIn("grant_not_in_audit", [found.problem for found in self.store.verify()])

    def test_an_external_effect_grant_without_an_anchor_fails_closed(self) -> None:
        path = self.path.with_name("other.json")
        bare = ApprovalStore(path, TickingClock(), audit=AuditLog(path.with_name("a.jsonl")))
        record = bare.request(PUSH, RiskLevel.HIGH, "ship", "agent-1")
        self.assertEqual(bare.grant(record.id, "ana").tree, "")
        self.assertFalse(bare.is_granted(PUSH))
        self.assertFalse(bare.consume(PUSH))

    def test_ordinary_grant_ignores_the_tree(self) -> None:
        record = self.granted(RM_BUILD)
        self.assertEqual((record.head, record.tree), ("", ""))
        self.repo.head, self.repo.tree = "c2", "t2"
        self.assertTrue(self.store.is_granted(RM_BUILD))
        self.assertFalse(self.store.is_stale(RM_BUILD))

    def test_publish_entries_are_anchored(self) -> None:
        for argv in (("gh", "pr", "merge", "1"), ("npm", "publish"), PUSH):
            with self.subTest(argv=argv):
                self.assertTrue(needs_anchor(argv))
        for argv in (("make", "test"), RM_BUILD, ("", "x")):
            with self.subTest(argv=argv):
                self.assertFalse(needs_anchor(argv))


class StaleGrantReasonTests(OrchestratorCase):
    def test_exec_after_an_edit_names_the_stale_grant(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start()
        self.run_task()
        push = ("git", "push", "origin", "main")
        with self.assertRaises(ApprovalRequired) as first:
            self.orch().exec_command(push)
        self.assertNotIn("stale_grant", first.exception.details)
        self.grant(first.exception.details["approval_id"])
        self.runner.edit("after the grant")
        with self.assertRaises(ApprovalRequired) as stale:
            self.orch().exec_command(push)
        self.assertTrue(stale.exception.details["stale_grant"])
        self.assertIn("changed since it was given", stale.exception.message)
        self.assertNotIn(push, self.runner.calls)
        self.grant(stale.exception.details["approval_id"])
        self.assertEqual(self.orch().exec_command(push)[1], 0)


if __name__ == "__main__":
    unittest.main()
