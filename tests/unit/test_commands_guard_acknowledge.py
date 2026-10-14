"""``wev guard acknowledge``: the human-only way out of a STOP or ASK_HUMAN verdict."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fixtures.operator_prompt import TEST_TERMINAL, ScriptedPrompt, at_terminal, no_terminal
from wev_skills import cli, i18n
from wev_skills.commands import _human
from wev_skills.core.ports import SystemClock
from wev_skills.guards.events import budget_event
from wev_skills.state.model import with_guard_event
from wev_skills.state.store import StateStore, run_dir

RUN = "r1"
REASON = "budget raised by the owner"


class FakeStdin(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__("")
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class AcknowledgeCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        (self.work / "wev.json").write_text(json.dumps({"state_dir": "state"}), encoding="utf-8")
        (self.work / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        code, _, err = self.run_cli(
            "run", "start", "--objective", "Do it", "--files", "1", "--run-id", RUN
        )
        self.assertEqual(code, 0, err)

    def run_cli(self, *argv: str, tty: bool = False) -> tuple[int, Any, Any]:
        out, err = io.StringIO(), io.StringIO()
        operator = at_terminal() if tty else no_terminal()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", FakeStdin(tty)),
            i18n.use_language("en"),
            operator,
        ):
            code = cli.main(["--config", "wev.json", *argv])
        stdout = json.loads(out.getvalue()) if out.getvalue().strip() else None
        stderr = json.loads(err.getvalue())["error"] if err.getvalue().strip() else None
        return code, stdout, stderr

    def trip(self) -> None:
        """Overrun the budget, which asks for a human (ASK_HUMAN)."""
        self.run_cli("task", "next")
        # Trip the task budget (100) without exhausting the whole-run budget (400).
        # The latter is intentionally not clearable by a human acknowledgement.
        event = budget_event("task-1", 1.0, 101.0).to_dict()
        store = StateStore(run_dir(self.work / "state", RUN), SystemClock())
        store.update(lambda state: with_guard_event(state, event))
        self.assertEqual(self.run_cli("guard", "check")[1]["action"], "ask_human")

    def audit(self) -> list[dict[str, Any]]:
        path = self.work / "state" / "audit.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def acknowledge(self, *extra: str, tty: bool = True) -> tuple[int, Any, Any]:
        return self.run_cli(
            "guard", "acknowledge", "--run", RUN, "--reason", REASON, *extra, tty=tty
        )


class AcknowledgeTests(AcknowledgeCase):
    def test_a_tripped_guard_keeps_refusing_until_acknowledged(self) -> None:
        self.trip()
        code, _, err = self.run_cli("task", "next")
        self.assertEqual((code, err["code"]), (6, "guard_tripped"))
        self.assertEqual(self.run_cli("guard", "check")[0], 6)

    def test_acknowledging_from_a_terminal_clears_the_trip(self) -> None:
        self.trip()
        code, out, err = self.acknowledge()
        self.assertEqual((code, err), (0, None))
        self.assertEqual(out["scope"], "run")
        self.assertIn(f"terminal:{TEST_TERMINAL}", out["confirmation"])
        self.assertEqual(out["operator"], _human.operator_name())
        self.assertEqual(out["previous"]["action"], "ask_human")
        self.assertEqual(self.run_cli("guard", "check")[1]["action"], "continue")
        self.assertEqual(self.run_cli("task", "next")[0], 0)

    def test_there_is_no_flag_that_replaces_the_terminal(self) -> None:
        self.trip()
        for extra in (("--i-am-human",), ("--by", "ana")):
            with self.subTest(extra=extra):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(
                        ["guard", "acknowledge", "--run", RUN, "--reason", REASON, *extra]
                    )
                self.assertEqual(code, 2)
        self.assertEqual(self.run_cli("guard", "check")[0], 6)

    def test_a_wrong_confirmation_word_is_refused_and_audited(self) -> None:
        self.trip()
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            i18n.use_language("en"),
            at_terminal(ScriptedPrompt(answer="yes")),
        ):
            code = cli.main(
                ["--config", "wev.json", "guard", "acknowledge", "--run", RUN, "--reason", REASON]
            )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(err.getvalue())["error"]["code"], "confirmation_mismatch")
        self.assertEqual(self.audit()[-1]["type"], "guard.acknowledge_refused")
        self.assertEqual(self.run_cli("guard", "check")[0], 6)

    def test_without_a_terminal_or_the_flag_it_is_refused_and_audited(self) -> None:
        self.trip()
        code, out, err = self.acknowledge(tty=False)
        self.assertEqual((code, out, err["code"]), (3, None, "human_required"))
        self.assertIn("ask the human operator", err["message"])
        self.assertIn(f"wev guard acknowledge --run {RUN}", err["message"])
        self.assertNotIn("--i-am-human", json.dumps(err))
        for lang in ("en", "pt-BR"):
            self.assertNotIn("--i-am-human", i18n.t("guard.acknowledge.help", lang))
        self.assertEqual(self.audit()[-1]["type"], "guard.acknowledge_refused")
        self.assertEqual(self.run_cli("guard", "check")[0], 6)

    def test_a_decision_is_recorded_in_the_run(self) -> None:
        self.trip()
        self.acknowledge()
        state = StateStore(run_dir(self.work / "state", RUN), SystemClock()).load()
        last = state.decisions[-1]
        self.assertEqual(last.source, "guard-acknowledge")
        self.assertIn(REASON, last.reasons)

    def test_a_task_scope_must_name_a_known_task(self) -> None:
        self.trip()
        code, _, err = self.acknowledge("--task", "other")
        self.assertEqual((code, err["code"]), (7, "unknown_task"))
        code, out, _ = self.acknowledge("--task", "task-1")
        self.assertEqual((code, out["scope"], out["task_id"]), (0, "task", "task-1"))
        self.assertEqual(self.run_cli("guard", "check")[1]["action"], "continue")

    def test_the_guard_counts_again_from_the_reset(self) -> None:
        self.trip()
        self.acknowledge()
        event = budget_event("task-1", 2.0, 101.0).to_dict()
        store = StateStore(run_dir(self.work / "state", RUN), SystemClock())
        store.update(lambda state: with_guard_event(state, event))
        self.assertEqual(self.run_cli("guard", "check")[1]["action"], "ask_human")

    def test_nothing_to_acknowledge_when_the_guard_is_clear(self) -> None:
        code, _, err = self.acknowledge()
        self.assertEqual((code, err["code"]), (2, "guard_not_tripped"))

    def test_a_reason_is_required_and_not_blank(self) -> None:
        self.trip()
        missing = io.StringIO()
        with contextlib.redirect_stderr(missing):
            code = cli.main(["--config", "wev.json", "guard", "acknowledge", "--run", RUN])
        self.assertEqual(code, 2)
        self.assertIn("--reason", missing.getvalue())
        code, _, err = self.run_cli(
            "guard", "acknowledge", "--run", RUN, "--reason", "  ", tty=True
        )
        self.assertEqual((code, err["code"]), (2, "reason_required"))

    def test_help_says_an_agent_must_never_run_it_for_itself(self) -> None:
        for lang, phrase in (
            ("en", "Human operator only"),
            ("pt-BR", "Somente o operador humano"),
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["--lang", lang, "guard", "acknowledge", "--help"])
            self.assertEqual(code, 0)
            text = " ".join(out.getvalue().split())
            self.assertIn(phrase, text)
            self.assertNotIn("--i-am-human", text)


if __name__ == "__main__":
    unittest.main()
