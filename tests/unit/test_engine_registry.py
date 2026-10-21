"""The engine applies policy only for a run the per-user registry lists; ``run adopt`` adds one."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
from typing import Any

from tests.fixtures.operator_prompt import ScriptedPrompt, at_terminal, no_terminal
from tests.unit.test_hook_trust import FORGED, TrustCase
from tests.unit.test_hooks import RUN
from wev_skills import cli
from wev_skills.core import active, run_registry
from wev_skills.governance.audit import AuditLog
from wev_skills.state.model import Phase
from wev_skills.state.store import StateStore, run_dir

UNREGISTERED_EXIT = 5
HUMAN_EXIT = 3
ADOPT_STEP = "wev run adopt"
POLICY_COMMANDS = (
    ("exec", "--", "ls"),
    ("task", "start", "t1"),
    ("plan", "set", "--file", "plan.json"),
    ("run", "report"),
    ("run", "finish"),
    ("run", "resume"),
    ("guard", "check"),
    ("check-command", "--", "ls"),
    ("approval", "request", "--risk", "low", "--reason", "r", "--", "rm", "x"),
    ("remote", "preflight", "--host", "h"),
    ("specialists", "list"),
    ("specialists", "accept", "p", "l"),
    ("remote", "start", "--host", "h", "--task", "t", "--", "ls"),
    ("remote", "status", "--host", "h", "--task", "t"),
    ("remote", "capture", "--host", "h", "--task", "t"),
    ("remote", "stop", "--host", "h", "--task", "t"),
    ("agent", "create", "--template", "base", "--id", "z1", "--out", "a.json"),
    ("agent", "export", "--out", "agents"),
    ("approval", "grant", "apr-0123456789abcdef"),
    ("approval", "deny", "apr-0123456789abcdef"),
    ("guard", "acknowledge", "--reason", "x", "--run", FORGED),
    ("task", "reopen", "t1", "--reason", "x"),
    ("jev", "ask", "--questions", "q.json", "--state", "x"),
    ("jev", "batch", "--questions", "q.json", "--items", "i.jsonl", "--out", "r.jsonl"),
)
READS_WITHOUT_FIELD = (
    ("state", "list"),
    ("approval", "list"),
    ("approval", "verify"),
    ("agent", "list"),
    ("config", "show"),
    ("remote", "hosts"),
    ("jev", "status"),
)
QUESTIONS = {"q": {"type": "noul", "instructions": "Is it ok?"}}
ITEM = {"id": "a", "state": "x"}
READ_COMMANDS = (("run", "status"), ("run", "brief"), ("plan", "show"), ("state", "show"))


class EngineRegistryCase(TrustCase):
    def call(self, *argv: str) -> tuple[int, Any, Any]:
        """``(exit code, stdout JSON or text, stderr JSON or text)`` of an in-process ``wev``."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--lang", "en", *argv])
        error = _parsed(err.getvalue())
        if isinstance(error, dict):
            error = error.get("error", error)
        return code, _parsed(out.getvalue()), error

    def assert_refused(self, *argv: str, run_id: str = FORGED) -> None:
        code, _, err = self.call(*argv)
        self.assertEqual(code, UNREGISTERED_EXIT, err)
        self.assertEqual(err["code"], active.UNREGISTERED, err)
        self.assertIn(ADOPT_STEP, err["details"]["next_step"])
        self.assertEqual(err["details"]["run_id"], run_id)


def _parsed(text: str) -> Any:
    stripped = text.strip()
    return json.loads(stripped) if stripped.startswith("{") else stripped


class ForgedRunTests(EngineRegistryCase):
    def setUp(self) -> None:
        super().setUp()
        self.forge()
        (self.work / "q.json").write_text(json.dumps(QUESTIONS), encoding="utf-8")
        (self.work / "i.jsonl").write_text(json.dumps(ITEM) + "\n", encoding="utf-8")

    def test_commands_that_apply_policy_refuse_an_unregistered_run(self) -> None:
        for argv in POLICY_COMMANDS:
            with self.subTest(argv=argv):
                self.assert_refused(*argv)

    def test_an_explicit_run_option_does_not_bypass_the_registry(self) -> None:
        self.assert_refused("exec", "--run", FORGED, "--", "ls")

    def test_reads_still_work_and_say_the_run_is_not_registered(self) -> None:
        for argv in (*READ_COMMANDS, *READS_WITHOUT_FIELD):
            with self.subTest(argv=argv):
                code, _, err = self.call(*argv)
                self.assertEqual(code, 0, err)
        for argv in (("run", "status"), ("state", "show")):
            with self.subTest(argv=argv):
                self.assertIs(self.call(*argv)[1]["registered"], False)
        self.assertIs(self.call("state", "list")[1]["active_registered"], False)

    def test_an_entry_naming_another_run_does_not_vouch_for_it(self) -> None:
        active.register_run(self.work, self.work / ".wev", "20990101T000000Z-other0")
        self.assert_refused("exec", "--", "ls")

    def test_an_unreadable_registry_refuses_too(self) -> None:
        path = run_registry.registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assert_refused("exec", "--", "ls")


class AdoptTests(EngineRegistryCase):
    def setUp(self) -> None:
        super().setUp()
        self.forge()

    def test_adopt_needs_a_person_at_a_terminal(self) -> None:
        with no_terminal():
            code, _, err = self.call("run", "adopt")
        self.assertEqual((code, err["code"]), (HUMAN_EXIT, "human_required"))
        self.assertEqual(run_registry.read_entries(), ())
        self.assert_refused("exec", "--", "ls")

    def test_a_wrong_word_adopts_nothing(self) -> None:
        with at_terminal(ScriptedPrompt(answer="nope")):
            code, _, err = self.call("run", "adopt")
        self.assertEqual((code, err["code"]), (HUMAN_EXIT, "confirmation_mismatch"))
        self.assertEqual(run_registry.read_entries(), ())

    def test_an_adopted_run_is_registered_and_used(self) -> None:
        prompt = ScriptedPrompt()
        with at_terminal(prompt):
            code, out, err = self.call("run", "adopt")
        self.assertEqual(code, 0, err)
        self.assertEqual((out["run_id"], out["registered"]), (FORGED, True))
        self.assertIn(FORGED, prompt.shown[0])
        self.assertIn("allowed_commands", prompt.shown[0])
        self.assertEqual([entry.run_id for entry in run_registry.read_entries()], [FORGED])
        self.assertIs(self.call("run", "status")[1]["registered"], True)
        code, _, err = self.call("exec", "--", "ls")
        self.assertNotEqual(code, UNREGISTERED_EXIT, err)
        self.assertEqual(err["code"], "approval_required", "the adopted loose policy applies")
        events = [event["type"] for event in AuditLog(self.work / ".wev" / "audit.jsonl").read()]
        self.assertIn("run.adopted", events)


class RegisteredRunTests(EngineRegistryCase):
    def test_a_started_run_needs_no_adoption(self) -> None:
        self.start()
        self.assertIs(self.call("run", "status")[1]["registered"], True)
        code, _, err = self.call("exec", "--", "ls")
        self.assertEqual(code, 0, err)

    def test_adopting_a_registered_run_changes_nothing(self) -> None:
        self.start()
        with at_terminal():
            code, out, err = self.call("run", "adopt")
        self.assertEqual(code, 0, err)
        self.assertEqual((out["run_id"], out["registered"]), (RUN, True))

    def test_a_finished_run_can_still_be_reported(self) -> None:
        self.start()
        self.wev("run", "finish")
        code, _, err = self.call("run", "report", "--run", RUN)
        self.assertEqual(code, 0, err)


class FinishedForgedRunTests(EngineRegistryCase):
    """The phase comes from the run's own file, so a forged run marked done is refused
    before anything else happens."""

    def setUp(self) -> None:
        super().setUp()
        state_dir = self.forge()
        store = StateStore(run_dir(state_dir, FORGED))
        store.update(lambda state: dataclasses.replace(state, phase=Phase.DONE))

    def test_commands_that_change_or_run_refuse_it_first(self) -> None:
        for argv in (
            ("exec", "--run", FORGED, "--", "ls"),
            ("task", "start", "t1", "--run", FORGED),
            ("task", "check", "t1", "--run", FORGED),
            ("task", "reopen", "t1", "--reason", "x", "--run", FORGED),
            ("plan", "set", "--file", "plan.json", "--run", FORGED),
            ("guard", "acknowledge", "--reason", "x", "--run", FORGED),
            ("run", "resume", "--run", FORGED),
        ):
            with self.subTest(argv=argv), at_terminal():
                code, _, err = self.call(*argv)
                self.assertEqual(err["code"], "run_finished", err)
                self.assertNotEqual(code, 0)

    def test_a_finished_run_can_still_be_read(self) -> None:
        for argv in (("run", "report", "--run", FORGED), ("run", "status", "--run", FORGED)):
            with self.subTest(argv=argv):
                self.assertEqual(self.call(*argv)[0], 0)


class AdoptPromptTests(EngineRegistryCase):
    def test_the_prompt_shows_no_terminal_control_or_extra_lines(self) -> None:
        state_dir = self.forge()
        store = StateStore(run_dir(state_dir, FORGED))
        evil = "ok\x1b]0;title\x07\x1b[2J\r\n  run       other\x9b"
        store.update(lambda state: dataclasses.replace(state, objective=evil))
        prompt = ScriptedPrompt(answer="no")
        with at_terminal(prompt):
            self.call("run", "adopt")
        shown = prompt.shown[0]
        for char in ("\x1b", "\x07", "\r", "\x9b"):
            self.assertNotIn(char, shown)
        self.assertEqual(sum(line.strip().startswith("run ") for line in shown.splitlines()), 1)
