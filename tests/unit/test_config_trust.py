"""Configuration trust rules: what a config file may name as a program or a directory."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills.config import Config, resolve_config
from wev_skills.core.errors import ValidationError


class ConfigTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "repo"
        self.root.mkdir()

    def _resolve(self, document: dict[str, object]) -> Config:
        path = self.root.parent / "given.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return resolve_config(str(path), self.root).config

    def _jev(self, command: str) -> dict[str, object]:
        return {"decision": {"provider": "jev", "jev": {"command": command}}}

    def test_new_defaults(self) -> None:
        config = Config()
        self.assertEqual(config.permissions.approval_ttl_seconds, 900.0)
        self.assertIn("/usr/bin", config.permissions.exec_path)
        self.assertFalse(config.agents.allow_override)
        self.assertEqual(config.limits.task_timeout_seconds, 3600.0)

    def test_jev_command_accepts_a_bare_name_and_an_absolute_path_outside_the_root(self) -> None:
        self.assertEqual(self._resolve(self._jev("jev")).decision.jev.command, "jev")
        outside = str(self.root.parent / "tools" / "jev")
        self.assertEqual(self._resolve(self._jev(outside)).decision.jev.command, outside)

    def test_jev_command_rejects_a_relative_path(self) -> None:
        for command in ("./jev", "tools/jev", "../jev"):
            with self.subTest(command=command), self.assertRaises(ValidationError) as caught:
                self._resolve(self._jev(command))
            self.assertEqual(caught.exception.code, "invalid_config")

    def test_jev_command_rejects_a_path_inside_the_root(self) -> None:
        with self.assertRaises(ValidationError):
            self._resolve(self._jev(str(self.root / "bin" / "jev")))

    def test_jev_command_rejects_a_shell_or_interpreter(self) -> None:
        for command in ("sh", "bash", "python3", "env", "node"):
            with self.subTest(command=command), self.assertRaises(ValidationError):
                self._resolve(self._jev(command))

    def test_jev_command_rejects_arguments(self) -> None:
        with self.assertRaises(ValidationError):
            self._resolve(self._jev("jev --flag"))

    def test_agent_directory_inside_the_root_is_accepted(self) -> None:
        config = self._resolve({"agents": {"directories": ["my-agents"]}})
        self.assertEqual(config.agents.directories, ("my-agents",))

    def test_agent_directory_outside_the_root_is_rejected(self) -> None:
        outside = str(self.root.parent / "evil")
        for entry in (outside, "../evil"):
            with self.subTest(entry=entry), self.assertRaises(ValidationError):
                self._resolve({"agents": {"directories": [entry]}})

    def test_agent_directory_in_the_user_config_home_is_accepted(self) -> None:
        home = self.root.parent / "xdg"
        previous = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = str(home)
        self.addCleanup(
            lambda: (
                os.environ.pop("XDG_CONFIG_HOME", None)
                if previous is None
                else os.environ.__setitem__("XDG_CONFIG_HOME", previous)
            )
        )
        entry = str(home / "wev-skills" / "agents")
        config = self._resolve({"agents": {"directories": [entry]}})
        self.assertEqual(config.agents.directories, (entry,))

    def test_agent_directory_symlink_out_of_the_root_is_rejected(self) -> None:
        target = self.root.parent / "elsewhere"
        target.mkdir()
        (self.root / "link").symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValidationError):
            self._resolve({"agents": {"directories": ["link"]}})


if __name__ == "__main__":
    unittest.main()
