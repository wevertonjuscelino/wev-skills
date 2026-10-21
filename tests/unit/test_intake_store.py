"""Intakes survive command boundaries and enforce the same limits on disk."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from wev_skills import cli
from wev_skills.core.brief import build_brief
from wev_skills.core.contracts import Mode
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.intake import model
from wev_skills.intake.store import IntakeStore, load_brief
from wev_skills.state.model import RunState


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = IntakeStore(self.root / ".wev")
        self.intake_id, self.record = self.store.start("Export reports")

    def test_store_is_private_atomic_and_redacts_answers(self) -> None:
        secret = "ghp_" + "a1B2c3D4e5" * 4
        self.store.update(self.intake_id, lambda r: model.set_field(r, "goal", (secret,), "answer"))
        path = self.store.directory / f"{self.intake_id}.json"
        self.assertNotIn(secret, path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.directory.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(self.store.directory.glob("*.tmp")))

    def test_parallel_updates_keep_both_answers(self) -> None:
        def update(field: str) -> None:
            self.store.update(
                self.intake_id, lambda r: model.set_field(r, field, ("confirmed",), "answer")
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(update, ("goal", "scope")))
        self.assertEqual(model.missing(self.store.load(self.intake_id)), ("done", "kind"))

    def test_rounds_survive_a_new_store_instance(self) -> None:
        self.store.update(self.intake_id, lambda r: model.next_round(r, 1)[0])
        again = IntakeStore(self.root / ".wev").load(self.intake_id)
        _, questions = model.next_round(again, 1)
        self.assertTrue(questions.rounds_exhausted)
        self.assertEqual(questions.questions, ())

    def test_unfinished_intake_does_not_supply_a_run_brief(self) -> None:
        with self.assertRaises(ValidationError):
            load_brief(self.root / ".wev", self.intake_id)

    def test_invalid_ids_and_symlink_records_are_refused(self) -> None:
        with self.assertRaises(ValidationError):
            self.store.load("../../outside")
        path = self.store.directory / f"{self.intake_id}.json"
        path.unlink()
        target = self.root / "external.json"
        target.write_text("{}")
        path.symlink_to(target)
        with self.assertRaises(ValidationError):
            self.store.load(self.intake_id)
        self.assertEqual(target.read_text(), "{}")

    def test_symlink_directory_is_refused(self) -> None:
        state = self.root / "alias"
        state.symlink_to(self.root / ".wev", target_is_directory=True)
        with self.assertRaises(ValidationError):
            IntakeStore(state).start("request")

    def test_duplicate_fields_and_invalid_round_counters_are_refused(self) -> None:
        path = self.store.directory / f"{self.intake_id}.json"
        record = model.set_field(self.record, "goal", ("result",), "answer").to_dict()
        variants = [dict(record, rounds_used=-1), dict(record, fields=record["fields"] * 2)]
        for value in variants:
            path.write_text(json.dumps(value))
            with self.assertRaises(ValidationError):
                self.store.load(self.intake_id)

    def test_unknown_update_does_not_create_state(self) -> None:
        store = IntakeStore(self.root / "unknown")
        with self.assertRaises(NotFound):
            store.update(self.intake_id, lambda r: r)
        self.assertFalse((self.root / "unknown").exists())

    def test_noninteger_round_limits_are_refused(self) -> None:
        for value in (True, 1.5, "3", None, 0, 11):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                model.next_round(self.record, value)  # type: ignore[arg-type]


class CommandTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / ".git").mkdir()
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.root)

    def call(self, *args: str) -> tuple[int, dict[str, object]]:
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = cli.main(["--lang", "en", *args])
        return code, json.loads(output.getvalue() or errors.getvalue())

    def test_command_lifecycle_and_finished_immutability(self) -> None:
        code, result = self.call("intake", "start", "--request", "Export reports")
        self.assertEqual(code, 0)
        intake_id = str(result["id"])
        _, asked = self.call("intake", "next", intake_id)
        self.assertEqual(len(asked["round"]["questions"]), 3)
        for field in ("goal", "done", "scope", "kind"):
            value = "feature" if field == "kind" else "confirmed"
            code, _ = self.call("intake", "set", intake_id, "--field", field, "--value", value)
            self.assertEqual(code, 0)
        code, result = self.call("intake", "finish", intake_id)
        self.assertEqual(code, 0)
        self.assertIn("--from-intake", result["run_start_command"])
        code, _ = self.call("intake", "set", intake_id, "--field", "goal", "--value", "other")
        self.assertNotEqual(code, 0)
        code, shown = self.call("intake", "show", intake_id)
        self.assertEqual(shown["brief"], result["brief"])

    def test_run_refuses_an_unfinished_intake_before_creating_run(self) -> None:
        _, result = self.call("intake", "start", "--request", "Export reports")
        code, error = self.call("run", "start", "--from-intake", str(result["id"]))
        self.assertNotEqual(code, 0)
        self.assertEqual(error["error"]["code"], "intake_incomplete")

    def test_run_uses_intake_and_keeps_the_brief_in_the_audit_event(self) -> None:
        _, result = self.call("intake", "start", "--request", "Export reports")
        intake_id = str(result["id"])
        for field in ("goal", "done", "scope", "kind"):
            value = "operations" if field == "kind" else "confirmed"
            self.call("intake", "set", intake_id, "--field", field, "--value", value)
        self.call("intake", "set", intake_id, "--field", "outcome", "--value", "fewer tickets")
        self.call("intake", "finish", intake_id)
        with patch("wev_skills.commands.run.new_orchestrator") as factory:
            engine = factory.return_value[0]
            engine.start.return_value = {"run_id": "test"}
            factory.return_value = (engine, "test")
            code, result = self.call("run", "start", "--from-intake", intake_id)
        self.assertEqual(code, 0)
        self.assertEqual(engine.start.call_args.args[0], "confirmed")
        self.assertTrue(engine.start.call_args.args[2].external_side_effects)
        self.assertEqual(engine.commit.call_args.args[1], "run.intake_attached")
        self.assertEqual(result["intake_brief"]["done"], ["confirmed"])
        initial = RunState("20261013T000000Z-abc123", "confirmed", Mode.AUTO, "at", "at")
        attached = engine.commit.call_args.args[0](initial)
        restored = RunState.from_dict(attached.to_dict())
        self.assertEqual(restored.discovery["intake"]["brief"]["scope"], "confirmed")
        reminder = build_brief(restored, "next", 4000, "en")
        self.assertIn("Scope: confirmed", reminder)
        self.assertIn("Done when: confirmed", reminder)
        self.assertIn("Outcome beyond the goal: fewer tickets", reminder)
