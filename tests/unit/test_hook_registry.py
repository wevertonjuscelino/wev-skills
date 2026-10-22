"""The hook lookup fails closed: a run outside the registry, or an unreadable registry, asks."""

from __future__ import annotations

import contextlib
import io
import json
import os
from unittest import mock

from tests.unit.test_hook_trust import ASK, DENY, UNREGISTERED, TrustCase
from tests.unit.test_hooks import NO_RUN, RUN
from wev_skills import cli
from wev_skills.core import active, run_registry
from wev_skills.core.errors import StateConflict
from wev_skills.rea import config as rea_config
from wev_skills.state.store import list_runs

UNREADABLE = "cannot be read"
PROMPT_HOOKS = ("session-context", "prompt-reminder")


class RegistryCase(TrustCase):
    def asked(self, line: str, phrase: str) -> None:
        found = self.bash(line)
        assert found is not None
        self.assertEqual(found["decision"], ASK, found)
        self.assertIn(phrase, found["reason"])

    def assert_no_brief(self) -> None:
        payload = {"cwd": str(self.work), "source": "compact"}
        for name in PROMPT_HOOKS:
            with self.subTest(name=name):
                self.assertEqual(self.hook(name, payload), (0, "", ""))


class LostRegistryTests(RegistryCase):
    def setUp(self) -> None:
        super().setUp()
        self.start(mode="plan")

    def test_a_registered_run_keeps_its_own_verdict(self) -> None:
        found = self.bash("rm -rf build")
        assert found is not None
        self.assertEqual(found["decision"], DENY)
        self.assertIn(f"wev run {RUN} (plan mode)", found["reason"])

    def test_a_tree_run_without_its_registry_entry_asks_for_every_command(self) -> None:
        run_registry.registry_path().unlink()
        for line in ("ls", "git status", "rm -rf build"):
            with self.subTest(line=line):
                self.asked(line, UNREGISTERED)
        self.assert_no_brief()

    def test_an_entry_naming_another_run_does_not_vouch_for_the_active_one(self) -> None:
        active.register_run(self.work, self.work / ".wev", "20990101T000000Z-other0")
        self.asked("ls", UNREGISTERED)
        self.assert_no_brief()

    def test_a_finished_unregistered_run_leaves_the_defaults(self) -> None:
        self.wev("run", "finish")
        run_registry.registry_path().unlink(missing_ok=True)
        self.assertIsNone(self.bash("ls"))
        self.assertEqual(self.without_run("rm -rf build"), ASK)


class UnreadableRegistryTests(RegistryCase):
    def setUp(self) -> None:
        super().setUp()
        path = run_registry.registry_path()
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

    def test_every_command_asks(self) -> None:
        for line in ("ls", "git status", "rm -rf build"):
            with self.subTest(line=line):
                self.asked(line, UNREADABLE)

    def test_a_default_deny_stays_a_deny(self) -> None:
        found = self.bash("cat .git/config")
        assert found is not None
        self.assertEqual(found["decision"], DENY)
        self.assertTrue(found["reason"].startswith(NO_RUN), found["reason"])

    def test_a_wrong_shape_is_unreadable_too(self) -> None:
        run_registry.registry_path().write_text(json.dumps({"runs": "x"}), encoding="utf-8")
        self.asked("ls", UNREADABLE)

    def test_an_absent_registry_is_no_registered_runs(self) -> None:
        run_registry.registry_path().unlink()
        self.assertIsNone(self.bash("ls"))
        self.assertEqual(run_registry.read_registry(), ())

    def test_the_brief_hooks_stay_silent(self) -> None:
        self.assert_no_brief()


class RegistryProtectionTests(RegistryCase):
    def lines(self) -> tuple[str, ...]:
        path = run_registry.registry_path()
        return (f"cat {path}", f"echo x > {path}", f"cp /tmp/forged.json {path}")

    def test_the_registry_is_protected_without_a_run(self) -> None:
        for line in self.lines():
            with self.subTest(line=line):
                self.assertEqual(self.without_run(line), DENY)

    def test_the_registry_is_protected_in_a_run(self) -> None:
        self.start()
        for line in self.lines():
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), DENY)


class ReaConfigProtectionTests(RegistryCase):
    """``rea mode`` is person-only; writing ``rea.json`` through Bash would skip that ask."""

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.work / "cfg")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_rea_config_is_protected(self) -> None:
        path = rea_config.rea_config_path()
        for line in (f'echo \'{{"mode": "direct"}}\' > {path}', f"rm {path}"):
            with self.subTest(line=line):
                self.assertEqual(self.without_run(line), DENY)


class RunStartRegistryTests(RegistryCase):
    def test_run_start_fails_when_the_registry_cannot_be_written(self) -> None:
        for error in (OSError("disk"), StateConflict("lock_timeout", "busy")):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(active, "register_run", side_effect=error),
            ):
                code, _, err = self.run_start()
                self.assertEqual(code, StateConflict.exit_code)
                self.assertEqual(json.loads(err)["error"]["code"], "registry_unwritable")
                self.assertEqual(list_runs(self.work / ".wev"), [])
        self.assertIsNone(active.find_active_run(self.work))

    def test_a_started_run_is_registered_under_its_id(self) -> None:
        self.start()
        entries = run_registry.read_entries()
        self.assertEqual([(entry.root, entry.run_id) for entry in entries], [(str(self.work), RUN)])

    def run_start(self) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--lang", "en", "run", "start", "--objective", "x", "--run-id", RUN])
        return code, out.getvalue(), err.getvalue()
