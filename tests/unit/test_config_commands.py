"""``wev config show`` and ``wev config validate`` resolve configuration like every command."""

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.unit._agent_helpers import RepoCase, run


class ConfigShowTests(RepoCase):
    def start_run(self) -> None:
        (self.tmp / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        code, _, err = run("run", "start", "--objective", "Do it", "--files", "1")
        self.assertEqual(code, 0, err)

    def test_defaults_name_their_source(self) -> None:
        code, out, _ = run("config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(out["config_source"], "defaults")
        self.assertEqual(out["limits"]["max_attempts"], 3)

    def test_the_repository_config_file_is_read_without_config_flag(self) -> None:
        path = self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        code, out, _ = run("config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(out["limits"]["max_attempts"], 7)
        self.assertEqual(out["config_source"], str(path))

    def test_the_repository_config_file_is_found_from_a_subdirectory(self) -> None:
        self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        (self.tmp / "sub").mkdir()
        os.chdir(self.tmp / "sub")
        self.assertEqual(run("config", "show")[1]["limits"]["max_attempts"], 7)

    def test_config_flag_beats_the_repository_file(self) -> None:
        self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        other = self.write("other.json", {"limits": {"max_attempts": 9}})
        _, out, _ = run("--config", str(other), "config", "show")
        self.assertEqual(out["limits"]["max_attempts"], 9)
        self.assertEqual(out["config_source"], str(other))

    def test_an_active_run_shows_its_pinned_configuration_and_says_so(self) -> None:
        self.write("wev.config.json", {"limits": {"max_attempts": 7}})
        self.start_run()
        self.write("wev.config.json", {"limits": {"max_attempts": 2}})
        code, out, _ = run("config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(out["limits"]["max_attempts"], 7)
        self.assertTrue(out["config_source"].startswith("run:"))
        self.assertEqual(out["pinned_by_run"], out["config_source"].removeprefix("run:"))

    def test_a_different_config_flag_is_refused_during_a_run(self) -> None:
        self.start_run()
        other = self.write("other.json", {"limits": {"max_attempts": 9}})
        code, _, err = run("--config", str(other), "config", "show")
        self.assertEqual(code, 2)
        self.assertIn("config_pinned", err)

    def test_no_pin_note_without_a_run(self) -> None:
        self.assertNotIn("pinned_by_run", run("config", "show")[1])


class ConfigValidateTests(RepoCase):
    def test_validate_names_the_source_it_checked(self) -> None:
        path = self.write("c.json", {"limits": {"max_attempts": 4}})
        code, out, _ = run("config", "validate", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(out["valid"], True)
        self.assertEqual(out["config_source"], str(Path(path).resolve()))
        self.assertEqual(out["warnings"], [])

    def test_validate_applies_the_repository_trust_rules(self) -> None:
        inside = self.tmp / "tools" / "jev"
        inside.parent.mkdir()
        inside.write_text("#!/bin/sh\n", encoding="utf-8")
        path = self.write("c.json", {"decision": {"jev": {"command": str(inside)}}})
        code, _, err = run("config", "validate", str(path))
        self.assertEqual(code, 2)
        self.assertIn("invalid_config", err)
        self.assertIn(json.dumps("must not point inside the repository")[1:-1], err)


class JevWarningTests(RepoCase):
    def jev_file(self, command: str, provider: str = "jev") -> Path:
        decision = {"provider": provider, "jev": {"command": command}}
        return self.write("wev.config.json", {"decision": decision})

    def test_validate_warns_when_jev_is_selected_and_cannot_be_found(self) -> None:
        path = self.jev_file("/nonexistent/dir/jev")
        code, out, _ = run("--lang", "en", "config", "validate", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("permissions.exec_path", out["warnings"][0])
        self.assertIn("decision.jev.command", out["warnings"][0])

    def test_show_warns_in_the_same_case(self) -> None:
        self.jev_file("no-such-jev")
        _, out, _ = run("--lang", "en", "config", "show")
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("no-such-jev", out["warnings"][0])

    def test_no_warning_when_the_local_provider_is_selected(self) -> None:
        self.jev_file("no-such-jev", provider="local")
        self.assertEqual(run("config", "show")[1]["warnings"], [])
