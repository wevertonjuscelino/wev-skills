"""The hooks trust only runs in the per-user registry, and the Bash pre-check never fails silent."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from tests.unit.test_hooks import NO_RUN, HookCase
from wev_skills.adapters.claude_code import bash_guard, hooks
from wev_skills.config import Config, config_digest
from wev_skills.core import active, run_registry
from wev_skills.core.contracts import Mode
from wev_skills.state.store import StateStore, run_dir

FORGED = "20990101T000000Z-forged"
LOOSE = {"permissions": {"protected_paths": [], "allowed_commands": ["rm", "git", "cat"]}}
ASK, DENY = "ask", "deny"
UNREGISTERED = "not in your run registry"


class TrustCase(HookCase):
    """A repository with an isolated, empty per-user registry."""

    def setUp(self) -> None:
        super().setUp()
        home = self.work.parent / "state-home"
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def forge(self, state_dir: str = ".wev") -> Path:
        """A run with a loose pinned configuration, written straight into the tree."""
        loose = Config.from_dict(LOOSE)
        store = StateStore(run_dir(self.work / state_dir, FORGED))
        store.create("forged", Mode.EXECUTE, FORGED, loose.to_dict(), config_digest(loose), "t")
        return self.work / state_dir


class ForgedRunTests(TrustCase):
    def test_a_run_shipped_in_the_tree_is_not_trusted(self) -> None:
        self.forge()
        self.assertEqual(run_registry.read_entries(), ())
        found = self.bash("cat .git/config")
        assert found is not None
        self.assertEqual(found["decision"], DENY)
        self.assertTrue(found["reason"].startswith(NO_RUN), found["reason"])
        for line in ("ls", "rm -rf build"):
            with self.subTest(line=line):
                asked = self.bash(line)
                assert asked is not None
                self.assertEqual(asked["decision"], ASK)
                self.assertIn(UNREGISTERED, asked["reason"])

    def test_the_same_run_once_registered_is_trusted(self) -> None:
        state_dir = self.forge()
        active.register_run(self.work, state_dir, FORGED)
        self.assertIsNone(self.decision("cat .git/config"))

    def test_a_run_registered_for_another_state_directory_does_not_vouch_for_it(self) -> None:
        self.forge()
        other = self.forge("elsewhere-state")
        active.register_run(self.work, other, FORGED)
        (other / "runs").rename(other / "gone")
        self.assertEqual(self.without_run("cat .git/config"), DENY)

    def test_a_repository_state_dir_setting_cannot_point_at_a_forged_run(self) -> None:
        self.forge("custom-state")
        config = {**LOOSE, "state_dir": "custom-state"}
        (self.work / "wev.config.json").write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(self.without_run("cat .git/config"), DENY)

    def test_a_forged_run_reached_through_a_path_is_ignored(self) -> None:
        self.forge()
        elsewhere = self.work.parent / "elsewhere"
        elsewhere.mkdir()
        found = self.bash(f"rm -rf {self.work}/src", elsewhere)
        assert found is not None
        self.assertTrue(found["reason"].startswith(NO_RUN), found["reason"])

    def test_the_brief_hooks_ignore_a_forged_run(self) -> None:
        self.forge()
        payload = {"cwd": str(self.work), "source": "compact"}
        for name in ("session-context", "prompt-reminder"):
            with self.subTest(name=name):
                self.assertEqual(self.hook(name, payload), (0, "", ""))

    def test_unreadable_input_asks_with_only_a_forged_run(self) -> None:
        self.forge()
        code, out, _ = self.hook("pre-tool-use", '{"cwd": "' + str(self.work) + '", "tool')
        specific = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((code, specific["permissionDecision"]), (0, ASK))
        self.assertIn(UNREGISTERED, specific["permissionDecisionReason"])

    def test_engine_commands_keep_their_tree_lookup(self) -> None:
        state_dir = self.forge()
        found = active.find_active_run(self.work)
        assert found is not None
        self.assertEqual((found.state_dir, found.run_id), (state_dir, FORGED))


class HookErrorTests(TrustCase):
    def answer(self) -> tuple[dict[str, str], str]:
        payload = {"cwd": str(self.work), "tool_name": "Bash", "tool_input": {"command": "ls"}}
        code, out, err = self.hook("pre-tool-use", payload)
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1, out)
        return json.loads(out)["hookSpecificOutput"], err

    def assert_internal_error_ask(self) -> None:
        specific, err = self.answer()
        self.assertEqual(specific["permissionDecision"], ASK)
        self.assertIn("RuntimeError", specific["permissionDecisionReason"])
        self.assertNotIn("secret-detail", specific["permissionDecisionReason"])
        note = "wev hook pre-tool-use: the engine could not act (RuntimeError).\n"
        self.assertEqual(err, note)

    def test_an_error_in_the_run_lookup_asks(self) -> None:
        boom = RuntimeError("secret-detail")
        with mock.patch.object(hooks, "find_hook_run", side_effect=boom):
            self.assert_internal_error_ask()

    def test_an_error_while_splitting_the_command_asks(self) -> None:
        boom = RuntimeError("secret-detail")
        with mock.patch.object(bash_guard, "split_bounded", side_effect=boom):
            self.assert_internal_error_ask()

    def test_an_error_while_building_the_answer_falls_back_to_a_fixed_ask(self) -> None:
        boom = RuntimeError("secret-detail")
        with (
            mock.patch.object(hooks, "find_hook_run", side_effect=boom),
            mock.patch.object(hooks, "_output", side_effect=boom),
        ):
            specific, err = self.answer()
        self.assertEqual(specific["permissionDecision"], ASK)
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertNotIn("secret-detail", json.dumps(specific) + err)

    def test_a_note_that_cannot_be_written_still_leaves_the_ask(self) -> None:
        boom = RuntimeError("secret-detail")
        with (
            mock.patch.object(hooks, "find_hook_run", side_effect=boom),
            mock.patch.object(hooks, "failure_note", side_effect=boom),
        ):
            specific, err = self.answer()
        self.assertEqual((specific["permissionDecision"], err), (ASK, ""))

    def test_the_brief_hooks_stay_silent_on_an_error(self) -> None:
        boom = RuntimeError("secret-detail")
        payload = {"cwd": str(self.work), "source": "compact"}
        with mock.patch.object(hooks, "find_hook_run", side_effect=boom):
            for name in ("session-context", "prompt-reminder"):
                with self.subTest(name=name):
                    code, out, err = self.hook(name, payload)
                    self.assertEqual((code, out), (0, ""))
                    self.assertNotIn("secret-detail", err)
