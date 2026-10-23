from __future__ import annotations

import unittest
from unittest import mock

from wev_skills.config import LimitsConfig
from wev_skills.core.contracts import Verdict
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.local import LocalPolicyProvider

THREE = [Verdict(True, 0.9, ("a",)), Verdict(True, 0.7, ("b",)), Verdict(False, 0.2, ("c",))]


class ResolveQuorumTests(unittest.TestCase):
    def setUp(self) -> None:
        self.p = LocalPolicyProvider(LimitsConfig())

    def test_default_stays_unanimous(self) -> None:
        self.assertFalse(self.p.resolve_conflict(THREE).accepted)

    def test_two_of_three_accepts(self) -> None:
        v = self.p.resolve_conflict(THREE, quorum=2)
        self.assertTrue(v.accepted)
        self.assertEqual(v.score, 0.2)
        self.assertEqual(v.reasons, ("a", "b", "c"))

    def test_one_of_three_rejects_at_quorum_two(self) -> None:
        votes = [Verdict(True, 0.9), Verdict(False, 0.1), Verdict(False, 0.1)]
        self.assertFalse(self.p.resolve_conflict(votes, quorum=2).accepted)

    def test_bad_quorum_refused(self) -> None:
        for quorum in (0, -1, 4):
            with self.assertRaises(ValidationError) as ctx:
                self.p.resolve_conflict(THREE, quorum=quorum)
            self.assertEqual(ctx.exception.code, "bad_quorum")

    def test_jev_delegates_quorum(self) -> None:
        jev = JevProvider(SubprocessRunner(), self.p, redactor=lambda text: text)
        self.assertTrue(jev.resolve_conflict(THREE, quorum=2).accepted)
        with mock.patch.object(self.p, "resolve_conflict") as local:
            jev.resolve_conflict(THREE, 2)
        local.assert_called_once_with(THREE, 2)


if __name__ == "__main__":
    unittest.main()
