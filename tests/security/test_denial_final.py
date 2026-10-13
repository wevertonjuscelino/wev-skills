"""A denial is final for the action in the run, wherever and however it is asked again.

Regression for the second independent pass: after a human denied ``rm -rf build``, asking
again with another ``--cwd``, risk, reason, quoting or whitespace produced a fresh pending
request. The denial follows the normalized argv and the run, not the directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fixtures.operator_prompt import at_terminal, no_terminal
from tests.security.test_approval_binding import RM_BUILD, BindingCase
from wev_skills import cli, i18n
from wev_skills.core.contracts import RiskLevel
from wev_skills.governance.approvals import ApprovalRequest, ApprovalStatus, denial_key


class DenialIdentityTests(unittest.TestCase):
    def test_quoting_and_whitespace_do_not_change_the_denied_action(self) -> None:
        wanted = denial_key(RM_BUILD)
        for spelling in (
            "rm -rf build",
            "rm   -rf\t'build'",
            ("rm -rf build",),
            (" rm", "-rf ", "build"),
            ("rm", "", "-rf", "build", " "),
            ("rm -rf", "build"),
        ):
            with self.subTest(spelling=spelling):
                self.assertEqual(denial_key(spelling), wanted)

    def test_another_argument_is_another_action(self) -> None:
        self.assertNotEqual(denial_key(("rm", "-rf", "dist")), denial_key(RM_BUILD))
        self.assertNotEqual(denial_key(("host-b", *RM_BUILD)), denial_key(("host-a", *RM_BUILD)))


class DenialScopeTests(BindingCase):
    def denied(self) -> ApprovalRequest:
        record = self.store.request(RM_BUILD, RiskLevel.HIGH, "cleanup", "agent", cwd=self.here)
        return self.store.deny(record.id, "ana", "/dev/ttys001")

    def stored_statuses(self) -> list[str]:
        document = json.loads(self.path.read_text())["approvals"]
        return sorted(item["status"] for item in document.values())

    def test_another_directory_does_not_make_a_fresh_request(self) -> None:
        denied = self.denied()
        again = self.store.request(RM_BUILD, RiskLevel.LOW, "x", "agent", cwd="/tmp")
        self.assertEqual(again, denied)
        self.assertEqual(self.stored_statuses(), ["denied"])
        self.assertTrue(self.store.is_denied(RM_BUILD, "/tmp"))
        self.assertTrue(self.store.is_denied(RM_BUILD, ""))

    def test_another_spelling_does_not_make_a_fresh_request(self) -> None:
        denied = self.denied()
        for spelling in (("rm -rf build",), (" rm", "-rf", "build "), ("rm", "-rf", "build", "")):
            with self.subTest(spelling=spelling):
                again = self.store.request(spelling, RiskLevel.LOW, "x", "agent", cwd=self.here)
                self.assertEqual(again, denied)
                self.assertTrue(self.store.is_denied(spelling, self.here))
        self.assertEqual(self.stored_statuses(), ["denied"])

    def test_another_action_is_still_asked(self) -> None:
        self.denied()
        other = self.store.request(("rm", "-rf", "dist"), RiskLevel.LOW, "x", "agent", cwd="/tmp")
        self.assertEqual(other.status, ApprovalStatus.PENDING)

    def test_a_remote_denial_is_per_host(self) -> None:
        on_a = self.store.request(("host-a", "uptime"), RiskLevel.HIGH, "r", "agent")
        self.store.deny(on_a.id, "ana")
        self.assertTrue(self.store.is_denied(("host-a", "uptime")))
        self.assertFalse(self.store.is_denied(("host-b", "uptime")))

    def test_a_reopen_from_another_directory_clears_the_denial(self) -> None:
        self.denied()
        fresh = self.store.request(
            ("rm -rf build",), RiskLevel.HIGH, "ok", "operator", cwd="/tmp", reopen_denied=True
        )
        self.assertEqual(fresh.status, ApprovalStatus.PENDING)
        self.assertFalse(self.store.is_denied(RM_BUILD, self.here))
        self.assertIn("approval.reopened", self.events())
        self.assertNotIn("denied", self.stored_statuses())
        self.assertEqual(self.store.verify(), ())

    def test_the_grant_stays_bound_to_its_directory(self) -> None:
        self.granted()
        self.assertFalse(self.store.consume(RM_BUILD, "/tmp"))
        self.assertTrue(self.store.consume(RM_BUILD, self.here))


class DenialCliTests(unittest.TestCase):
    """The reproduction through the real CLI, from a caller without a terminal."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"
        self.config = Path(tmp.name) / "config.json"
        self.config.write_text(json.dumps({"state_dir": str(self.state)}))

    def run_cli(self, *argv: str) -> tuple[int, Any]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", io.StringIO("")),
            i18n.use_language("en"),
        ):
            code = cli.main(["--config", str(self.config), *argv])
        return code, json.loads(out.getvalue()) if out.getvalue() else None

    def request(self, *extra: str, argv: tuple[str, ...] = RM_BUILD) -> dict[str, Any]:
        base = ("approval", "request", "--risk", "low", "--reason", "x")
        with no_terminal():
            code, out = self.run_cli(*base, *extra, "--", *argv)
        self.assertEqual(code, 0)
        result: dict[str, Any] = out
        return result

    def test_a_denied_command_is_not_refiled_from_another_directory(self) -> None:
        first = self.request()
        with at_terminal():
            code, out = self.run_cli("approval", "deny", first["id"])
        self.assertEqual((code, out["status"]), (0, "denied"))
        for extra in (("--cwd", "/tmp"), ("--cwd", "/"), ()):
            with self.subTest(extra=extra):
                again = self.request(*extra)
                self.assertEqual((again["status"], again["generation"]), ("denied", 1))
        quoted = self.request("--cwd", "/tmp", argv=("rm -rf build",))
        self.assertEqual(quoted["status"], "denied")
        code, listing = self.run_cli("approval", "list")
        self.assertEqual([item["status"] for item in listing["approvals"]], ["denied"])
        code, out = self.run_cli("check-command", "--", *RM_BUILD)
        self.assertEqual((code, out["decision"]["outcome"]), (3, "deny"))


if __name__ == "__main__":
    unittest.main()
