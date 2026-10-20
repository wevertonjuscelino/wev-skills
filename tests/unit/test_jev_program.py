from __future__ import annotations

import contextlib
import dataclasses
import os
import stat
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

from tests.unit._agent_helpers import make
from wev_skills import i18n
from wev_skills.config import BUILTIN, Config, DecisionConfig, JevConfig, PermissionsConfig
from wev_skills.core.contracts import PlanTask, TaskSignals
from wev_skills.core.ports import SubprocessRunner
from wev_skills.decisions import jev_program
from wev_skills.decisions.factory import build_provider
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.jev_program import jev_warnings, resolve_jev_program
from wev_skills.decisions.jev_wire import JevUnavailable
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.tools.registry import ToolRegistry

FAKE_SCRIPT = "#!/bin/sh\nexit 1\n"


def english() -> contextlib.AbstractContextManager[None]:
    """Enter an English language block now; the caller schedules its exit."""
    block = i18n.use_language("en")
    block.__enter__()
    return block


@contextlib.contextmanager
def isolated_keys(env_key: str | None) -> Iterator[None]:
    with tempfile.TemporaryDirectory() as tmp:
        base = {"HOME": tmp, "XDG_CONFIG_HOME": str(Path(tmp) / "cfg")}
        with (
            mock.patch.dict(os.environ, base),
            mock.patch.object(jev_program, "macos_keychain", lambda: None),
        ):
            os.environ.pop("TYPESAFE_API_KEY", None)
            if env_key:
                os.environ["TYPESAFE_API_KEY"] = env_key
            yield


def make_program(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text(FAKE_SCRIPT, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class ResolveJevProgramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(english().__exit__, None, None, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "repo"
        self.safe = self.base / "tools"
        self.root.mkdir()
        self.safe.mkdir()

    def test_bare_name_is_found_on_the_exec_path(self) -> None:
        program = make_program(self.safe, "myjev")
        found = resolve_jev_program("myjev", [str(self.safe)], str(self.root))
        self.assertEqual(found, str(program))

    def test_bare_name_missing_from_the_exec_path_is_unavailable(self) -> None:
        with self.assertRaises(JevUnavailable) as caught:
            resolve_jev_program("myjev", [str(self.safe)], str(self.root))
        self.assertEqual(caught.exception.code, "binary_missing")
        self.assertIn("myjev", caught.exception.message)

    def test_absolute_path_outside_the_root_is_accepted(self) -> None:
        program = make_program(self.safe, "anyname")
        self.assertEqual(resolve_jev_program(str(program), [], str(self.root)), str(program))

    def test_program_inside_the_root_is_refused(self) -> None:
        program = make_program(self.root, "myjev")
        with self.assertRaises(JevUnavailable) as caught:
            resolve_jev_program(str(program), [], str(self.root))
        self.assertEqual(caught.exception.code, "program_in_run_root")

    def test_exec_path_entry_inside_the_root_is_refused(self) -> None:
        make_program(self.root, "myjev")
        with self.assertRaises(JevUnavailable):
            resolve_jev_program("myjev", [str(self.root)], str(self.root))

    def test_relative_exec_path_entries_are_ignored(self) -> None:
        make_program(self.safe, "myjev")
        with self.assertRaises(JevUnavailable):
            resolve_jev_program("myjev", ["tools"], str(self.root))

    def test_a_directory_is_not_a_program(self) -> None:
        folder = self.safe / "jev"
        folder.mkdir()
        with self.assertRaises(JevUnavailable) as caught:
            resolve_jev_program(str(folder), [], str(self.root))
        self.assertEqual(caught.exception.code, "binary_missing")

    def test_a_missing_absolute_path_is_unavailable_and_names_both_fixes(self) -> None:
        with self.assertRaises(JevUnavailable) as caught:
            resolve_jev_program(str(self.safe / "nope"), [], str(self.root))
        self.assertEqual(caught.exception.code, "binary_missing")
        self.assertFixesNamed(caught.exception.message)

    def test_a_file_that_is_not_executable_is_unavailable(self) -> None:
        plain = self.safe / "plain"
        plain.write_text("x", encoding="utf-8")
        plain.chmod(0o644)
        with self.assertRaises(JevUnavailable):
            resolve_jev_program(str(plain), [], str(self.root))

    def test_a_bare_name_not_found_says_so_and_names_both_fixes(self) -> None:
        with self.assertRaises(JevUnavailable) as caught:
            resolve_jev_program("myjev", [str(self.safe)], str(self.root))
        message = caught.exception.message
        self.assertIn("not found on the allowed path", message)
        self.assertFixesNamed(message)

    def assertFixesNamed(self, message: str) -> None:
        self.assertIn("decision.jev.command", message)
        self.assertIn("absolute path", message)
        self.assertIn("permissions.exec_path", message)


class ProviderFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(english().__exit__, None, None, None)

    def test_unresolvable_program_falls_back_to_local_with_a_reason(self) -> None:
        config = dataclasses.replace(
            Config(),
            decision=DecisionConfig(provider="jev", jev=JevConfig(command="no-such-jev")),
            permissions=PermissionsConfig(exec_path=("/usr/bin", "/bin")),
        )
        provider = build_provider(config, SubprocessRunner(), str, root=os.getcwd())
        self.assertIsInstance(provider, JevProvider)
        result = provider.classify_task(TaskSignals(objective="add a feature"))
        self.assertTrue(any("no-such-jev" in reason for reason in result.reasons))
        local = LocalPolicyProvider(config.limits, config.harness)
        expected = local.classify_task(TaskSignals(objective="add a feature"))
        self.assertEqual(result.complexity, expected.complexity)
        reason = result.reasons[0]
        self.assertIn("not found on the allowed path", reason)
        self.assertIn("decision.jev.command", reason)
        self.assertIn("permissions.exec_path", reason)

    def test_tool_selection_records_the_same_reason(self) -> None:
        config = self.jev_config("no-such-jev")
        provider = build_provider(config, SubprocessRunner(), str, root=os.getcwd())
        agent = make(
            "w",
            tools={"allow": ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebFetch"]},
            permissions={"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True},
        )
        task = PlanTask.from_dict({"id": "t", "title": "T", "objective": "Tidy"})
        chosen = provider.select_tools(task, agent, ToolRegistry.default().list(), "standard")
        self.assertIn("not found on the allowed path", chosen.reasons[0])
        self.assertIn("permissions.exec_path", chosen.reasons[0])

    def jev_config(self, command: str, provider: str = "jev") -> Config:
        return dataclasses.replace(
            Config(),
            decision=DecisionConfig(provider=provider, jev=JevConfig(command=command)),
            permissions=PermissionsConfig(exec_path=("/usr/bin", "/bin")),
        )

    def test_warning_when_jev_is_selected_and_does_not_resolve(self) -> None:
        warnings = jev_warnings(self.jev_config("no-such-jev"), os.getcwd())
        self.assertEqual(len(warnings), 1)
        self.assertIn("no-such-jev", warnings[0])
        self.assertIn("permissions.exec_path", warnings[0])

    def test_no_warning_for_the_local_provider_or_a_resolvable_program(self) -> None:
        self.assertEqual(jev_warnings(self.jev_config("no-such-jev", "local"), os.getcwd()), [])
        with tempfile.TemporaryDirectory() as tmp:
            program = make_program(Path(tmp).resolve(), "myjev")
            config = self.jev_config(str(program))
            self.assertEqual(jev_warnings(config, os.getcwd()), [])

    def test_builtin_warns_when_no_key(self) -> None:
        with isolated_keys(None):
            warnings = jev_warnings(self.jev_config(BUILTIN), os.getcwd())
        self.assertEqual(len(warnings), 1)
        self.assertIn("no JEV key was found", warnings[0])

    def test_builtin_no_warning_with_key(self) -> None:
        with isolated_keys("k-value"):
            self.assertEqual(jev_warnings(self.jev_config(BUILTIN), os.getcwd()), [])


if __name__ == "__main__":
    unittest.main()
