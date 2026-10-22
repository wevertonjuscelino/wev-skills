"""Configuration added for intake, project specialists, lessons and the run budget."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wev_skills import schema
from wev_skills.config import DEFAULT_CONFIG, Config, parse_config, resolve_config
from wev_skills.core.errors import BudgetExhausted, ValidationError, WevError


class NewDefaultsTests(unittest.TestCase):
    def test_defaults_of_every_new_key(self) -> None:
        config = Config()
        self.assertEqual(config.intake.max_rounds, 3)
        self.assertEqual(config.agents.project_dir, "wev-specialists")
        self.assertEqual(config.specialists.max_per_project, 5)
        self.assertEqual(config.specialists.max_lessons_rendered, 12)
        self.assertEqual(config.specialists.max_lessons, 30)
        self.assertEqual(config.specialists.stale_after_runs, 20)
        self.assertEqual(config.specialists.score_samples, 3)
        self.assertEqual(config.specialists.score_max_runs, 60)
        self.assertEqual(config.specialists.score_max_new_lessons, 3)
        self.assertEqual(config.specialists.score_timeout_seconds, 900.0)
        self.assertFalse(config.specialists.score_on_finish)
        self.assertEqual(config.limits.run_budget_units, 400.0)
        self.assertEqual(config.limits.run_max_attempts_total, 12)

    def test_the_defaults_pass_the_schema(self) -> None:
        self.assertEqual(schema.validate(DEFAULT_CONFIG, schema.load("config")), [])

    def test_values_below_the_minimum_are_refused(self) -> None:
        bad = (
            {"intake": {"max_rounds": 0}},
            {"intake": {"max_rounds": 11}},
            {"specialists": {"max_per_project": 0}},
            {"specialists": {"max_lessons": 0}},
            {"specialists": {"max_lessons_rendered": 0}},
            {"specialists": {"stale_after_runs": 0}},
            {"limits": {"run_budget_units": 0}},
            {"limits": {"run_max_attempts_total": 0}},
            {"specialists": {"unknown": 1}},
            {"specialists": {"score_samples": 0}},
            {"specialists": {"score_samples": 11}},
            {"specialists": {"score_max_runs": 0}},
            {"specialists": {"score_max_runs": 1001}},
            {"specialists": {"score_max_new_lessons": -1}},
            {"specialists": {"score_max_new_lessons": 11}},
            {"specialists": {"score_timeout_seconds": 0}},
            {"specialists": {"score_timeout_seconds": 3600.5}},
            {"specialists": {"score_on_finish": "yes"}},
        )
        for overrides in bad:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                parse_config(None, overrides)

    def test_a_state_pinned_before_these_keys_still_loads(self) -> None:
        old = {k: v for k, v in DEFAULT_CONFIG.items() if k not in ("intake", "specialists")}
        self.assertEqual(Config.from_dict(old).intake.max_rounds, 3)

    def test_the_score_bounds_are_accepted_at_their_edges(self) -> None:
        edges = {
            "score_samples": (1, 10),
            "score_max_runs": (1, 1000),
            "score_max_new_lessons": (0, 10),
            "score_timeout_seconds": (0.1, 3600.0),
        }
        for key, values in edges.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    config = parse_config(None, {"specialists": {key: value}})
                    self.assertEqual(getattr(config.specialists, key), value)

    def test_a_state_pinned_without_score_keys_gets_their_defaults(self) -> None:
        old = json.loads(json.dumps(DEFAULT_CONFIG))
        for key in ("score_samples", "score_max_runs", "score_max_new_lessons"):
            old["specialists"].pop(key, None)
        old["specialists"].pop("score_timeout_seconds", None)
        old["specialists"].pop("score_on_finish", None)
        self.assertEqual(Config.from_dict(old).specialists, Config().specialists)


class ProjectDirTrustTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "repo"
        self.root.mkdir()

    def _resolve(self, project_dir: str) -> Config:
        path = self.root.parent / "given.json"
        path.write_text(json.dumps({"agents": {"project_dir": project_dir}}), encoding="utf-8")
        return resolve_config(str(path), self.root).config

    def test_a_directory_inside_the_root_is_accepted(self) -> None:
        self.assertEqual(self._resolve("team/specialists").agents.project_dir, "team/specialists")

    def test_a_directory_outside_the_root_is_refused(self) -> None:
        for entry in ("../elsewhere", str(self.root.parent / "elsewhere"), "."):
            with self.subTest(entry=entry), self.assertRaises(ValidationError):
                self._resolve(entry)

    def test_the_claude_and_git_directories_are_refused(self) -> None:
        for entry in (".claude/agents", ".git/specs", ".wev"):
            with self.subTest(entry=entry), self.assertRaises(ValidationError):
                self._resolve(entry)


class BudgetExhaustedTests(unittest.TestCase):
    def test_it_is_a_wev_error_with_its_own_exit_code(self) -> None:
        error = BudgetExhausted("budget_exhausted", "no budget left")
        self.assertIsInstance(error, WevError)
        self.assertEqual(error.exit_code, 9)
        codes = {cls.exit_code for cls in WevError.__subclasses__() if cls is not BudgetExhausted}
        self.assertNotIn(9, codes)


if __name__ == "__main__":
    unittest.main()
