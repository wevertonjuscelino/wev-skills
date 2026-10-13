"""No argv secret reaches the state directory, whichever way an execution ends.

Regression for the second independent pass: ``exec.denied`` and ``exec.approval_requested``
recorded the raw argv, so ``rm -rf build --password <secret>`` left the secret in the audit
log. Every file under the state directory is searched for canaries after allowed, denied,
approval-required and guard-refused executions.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.test_cli_flow import CliFlowCase

CANARY = "CANARY" + "x7Qp2Lm9Zr4Tt"
"""No shape of its own: only the surrounding command (``--password``) reveals it."""
EVENT_TYPES = (
    "exec.ran",
    "exec.denied",
    "exec.approval_requested",
    "guard.tripped",
    "task.checked",
)
"""Audit events the first scenario must produce; the documents list these as covered,
together with ``approval.requested`` and ``task.recorded`` from the last scenario."""


class RefusedRedactionTests(CliFlowCase):
    def canary(self, tag: str) -> str:
        return f"{CANARY}{tag}"

    def leaks(self) -> list[str]:
        """``file: line`` for every stored line that holds a canary."""
        found = []
        for path in sorted((self.work / ".wev").rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            found += [f"{path.name}: {line[:160]}" for line in text.splitlines() if CANARY in line]
        return found

    def audit_types(self) -> list[str]:
        lines = (self.work / ".wev" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
        return [json.loads(line)["type"] for line in lines]

    def trip_guard(self) -> None:
        for _ in range(5):
            self.wev("exec", "--", "false")

    def test_no_canary_is_stored_after_any_kind_of_execution(self) -> None:
        (self.work / "build").mkdir()
        self.begin()
        outcomes = {
            "allowed": self.wev("exec", "--", "ls", "--password", self.canary("A")),
            "allowed_url": self.wev(
                "exec", "--", "ls", f"https://bob:{self.canary('B')}@example.invalid/x"
            ),
            "denied_secret": self.wev(
                "exec", "--", "rm", "-rf", "build", "--password", self.canary("C")
            ),
            "denied_url": self.wev(
                "exec", "--", "git", "push", f"https://bob:{self.canary('D')}@example.invalid/x.git"
            ),
            "denied_protected": self.wev(
                "exec", "--", "cat", ".git/config", "--token", self.canary("E")
            ),
            "denied_shell": self.wev("exec", "--", "ls", "--password", self.canary("F"), ";"),
            "approval": self.wev("exec", "--", "rm", "-rf", "build"),
        }
        codes = {name: code for name, (code, _, _) in outcomes.items()}
        self.assertEqual(codes["denied_secret"], 3, outcomes["denied_secret"])
        self.assertEqual(codes["denied_url"], 3)
        self.assertEqual(codes["denied_protected"], 3)
        self.assertEqual(codes["approval"], 4)
        for name, (_, out, err) in outcomes.items():
            with self.subTest(printed=name):
                self.assertNotIn(CANARY, json.dumps([out, err]))
        self.wev("task", "check", "task-1")
        self.trip_guard()
        code, _, err = self.wev("exec", "--", "ls", "--password", self.canary("G"))
        self.assertEqual((code, err["code"]), (6, "guard_tripped"))
        self.assertNotIn(CANARY, json.dumps(err))
        for wanted in EVENT_TYPES:
            self.assertIn(wanted, self.audit_types())
        self.assertEqual(self.leaks(), [])

    def test_an_approval_request_with_a_secret_is_refused_and_not_stored(self) -> None:
        self.begin()
        request = ("approval", "request", "--risk", "low", "--reason", "x", "--")
        code, _, err = self.wev(*request, "rm", "-rf", "build", "--password", self.canary("H"))
        self.assertEqual((code, err["code"]), (3, "secret_in_action"))
        self.assertNotIn(CANARY, json.dumps(err))
        self.assertEqual(self.leaks(), [])

    def test_a_reason_and_a_summary_with_a_secret_are_masked(self) -> None:
        self.begin()
        secret = f"password={self.canary('I')}"
        self.wev("approval", "request", "--risk", "low", "--reason", secret, "--", "rm", "-rf", "x")
        self.wev("task", "record", "task-1", "--status", "failed", "--summary", secret)
        for wanted in ("approval.requested", "task.recorded"):
            self.assertIn(wanted, self.audit_types())
        self.assertEqual(self.leaks(), [])


class StateDirLocation(CliFlowCase):
    def test_the_canary_search_reads_real_files(self) -> None:
        self.begin()
        self.wev("exec", "--", "ls")
        files = [p for p in Path(self.work / ".wev").rglob("*") if p.is_file()]
        self.assertTrue(any(p.name == "audit.jsonl" for p in files))
        self.assertTrue(any(p.name == "state.json" for p in files))
