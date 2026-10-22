"""The user-level ``wev.config.json`` sits below the repository file and above the defaults."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from tests.unit._agent_helpers import RepoCase, run
from wev_skills.config import config_digest, resolve_config, user_config_path


class UserTierTests(RepoCase):
    def setUp(self) -> None:
        super().setUp()
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        home = Path(self._home.name).resolve()
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "x")})
        patch.start()
        self.addCleanup(patch.stop)
        self.user = user_config_path()
        self.user.parent.mkdir(parents=True)

    def write_user(self, doc: object) -> Path:
        self.user.write_text(json.dumps(doc), encoding="utf-8")
        return self.user

    def test_user_file_alone_sets_values_and_names_itself(self) -> None:
        self.write_user({"decision": {"provider": "jev"}, "language": "pt-BR"})
        resolved = resolve_config(None, self.tmp)
        self.assertEqual(resolved.config.decision.provider, "jev")
        self.assertEqual(resolved.config.language, "pt-BR")
        self.assertEqual(resolved.source, str(self.user))
        self.assertEqual(resolved.sources, (str(self.user),))

    def test_repository_file_overrides_one_key_and_keeps_the_others(self) -> None:
        self.write_user({"decision": {"provider": "jev"}, "limits": {"max_attempts": 5}})
        repo = self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        resolved = resolve_config(None, self.tmp)
        self.assertEqual(resolved.config.limits.max_attempts, 7)
        self.assertEqual(resolved.config.decision.provider, "jev")
        self.assertEqual(resolved.source, f"{self.user} + {repo}")

    def test_explicit_config_ignores_both(self) -> None:
        self.write_user({"limits": {"max_attempts": 5}})
        self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        other = self.write("other.json", {"limits": {"max_attempts": 9}})
        resolved = resolve_config(str(other), self.tmp)
        self.assertEqual(resolved.config.limits.max_attempts, 9)
        self.assertEqual(resolved.sources, (str(other),))

    def test_a_symlinked_user_file_is_ignored(self) -> None:
        real = self.user.parent / "real.json"
        real.write_text(json.dumps({"limits": {"max_attempts": 5}}), encoding="utf-8")
        self.user.symlink_to(real)
        resolved = resolve_config(None, self.tmp)
        self.assertEqual((resolved.source, resolved.config.limits.max_attempts), ("defaults", 3))

    def test_a_directory_at_the_user_path_is_ignored(self) -> None:
        self.user.mkdir()
        self.assertEqual(resolve_config(None, self.tmp).source, "defaults")

    def test_invalid_user_json_names_the_user_path(self) -> None:
        self.user.write_text("{not json", encoding="utf-8")
        code, _, err = run("config", "show")
        self.assertEqual(code, 2)
        self.assertIn(str(self.user), err)

    def test_an_invalid_user_value_is_invalid_config_naming_the_user_path(self) -> None:
        self.write_user({"limits": {"max_attempts": "many"}})
        code, _, err = run("config", "show")
        self.assertEqual(code, 2)
        self.assertIn("invalid_config", err)
        self.assertIn(str(self.user), err)

    def test_config_show_lists_both_sources_in_order(self) -> None:
        self.write_user({"limits": {"max_attempts": 5}})
        repo = self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        _, out, _ = run("config", "show")
        self.assertEqual(out["config_sources"], [str(self.user), str(repo)])
        self.assertEqual(out["config_source"], f"{self.user} + {repo}")
        self.assertEqual(out["limits"]["max_attempts"], 7)

    def test_config_show_without_files_lists_no_sources(self) -> None:
        _, out, _ = run("config", "show")
        self.assertEqual((out["config_source"], out["config_sources"]), ("defaults", []))

    def test_trust_rules_apply_to_the_merged_result(self) -> None:
        outside = Path(self._home.name) / "elsewhere"
        self.write_user({"agents": {"directories": [str(outside)]}})
        code, _, err = run("config", "show")
        self.assertEqual(code, 2)
        self.assertIn("invalid_config", err)
        self.assertIn("/agents/directories/0", err)

    def test_a_user_agents_directory_inside_the_user_home_is_trusted(self) -> None:
        self.write_user({"agents": {"directories": [str(self.user.parent / "agents")]}})
        self.assertEqual(run("config", "show")[0], 0)

    def test_run_start_pins_the_merged_digest(self) -> None:
        (self.tmp / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        self.write_user({"limits": {"max_attempts": 5}, "intake": {"max_rounds": 2}})
        self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        code, _, err = run("run", "start", "--objective", "Do it", "--files", "1")
        self.assertEqual(code, 0, err)
        pinned = run("run", "status")[1]["config"]["digest"]
        merged = resolve_config(None, self.tmp).config
        self.assertEqual((merged.limits.max_attempts, merged.intake.max_rounds), (7, 2))
        self.assertEqual(pinned, config_digest(merged))
