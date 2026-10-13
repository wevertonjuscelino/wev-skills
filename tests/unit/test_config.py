from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from typing import Any

from wev_skills import schema
from wev_skills.config import DEFAULT_CONFIG, Config, deep_merge, load_config
from wev_skills.core.errors import NotFound, ValidationError


class ConfigTests(unittest.TestCase):
    def write(self, data: Any) -> str:
        fd, name = tempfile.mkstemp(suffix=".json")
        self.addCleanup(os.unlink, name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data if isinstance(data, str) else json.dumps(data))
        return name

    def test_defaults_without_file(self) -> None:
        cfg = load_config()
        self.assertEqual(cfg.language, "en")
        self.assertEqual(cfg.state_dir, ".wev")
        self.assertEqual(cfg.decision.provider, "local")
        self.assertEqual(cfg.models.tiers.economy, ("claude-haiku-5-5",))
        self.assertEqual(cfg.models.tiers.standard, ("claude-sonnet-5-5",))
        self.assertEqual(cfg.models.tier("premium"), ("claude-opus-5-5", "claude-sonnet-5-5"))
        self.assertFalse(cfg.permissions.allow_shell)
        self.assertEqual(cfg.remote.hosts, ())

    def test_default_dict_is_valid_against_schema(self) -> None:
        self.assertEqual(schema.validate(DEFAULT_CONFIG, schema.load("config")), [])

    def test_config_round_trips(self) -> None:
        cfg = load_config()
        self.assertEqual(Config.from_dict(cfg.to_dict()), cfg)

    def test_file_values_deep_merge_over_defaults(self) -> None:
        path = self.write({"limits": {"max_attempts": 7}, "decision": {"jev": {"command": "x"}}})
        cfg = load_config(path)
        self.assertEqual(cfg.limits.max_attempts, 7)
        self.assertEqual(cfg.limits.max_parallel, 3)
        self.assertEqual(cfg.decision.jev.command, "x")
        self.assertEqual(cfg.decision.jev.timeout_seconds, 10.0)
        self.assertEqual(cfg.decision.provider, "local")

    def test_overrides_win_over_file_and_lists_replace(self) -> None:
        path = self.write({"limits": {"max_attempts": 7}, "agents": {"directories": ["a", "b"]}})
        cfg = load_config(path, {"limits": {"max_attempts": 9}, "agents": {"directories": ["c"]}})
        self.assertEqual(cfg.limits.max_attempts, 9)
        self.assertEqual(cfg.agents.directories, ("c",))

    def test_remote_hosts_parse_with_defaults(self) -> None:
        cfg = load_config(None, {"remote": {"hosts": [{"alias": "stg", "environment": "staging"}]}})
        self.assertEqual(cfg.remote.hosts[0].alias, "stg")
        self.assertFalse(cfg.remote.hosts[0].allow_mutating)

    def test_inputs_are_not_mutated(self) -> None:
        before_defaults = copy.deepcopy(DEFAULT_CONFIG)
        overrides = {"models": {"tiers": {"economy": ["m1"]}}, "limits": {"max_attempts": 2}}
        overrides_before = copy.deepcopy(overrides)
        cfg = load_config(None, overrides)
        self.assertEqual(cfg.models.tiers.economy, ("m1",))
        self.assertEqual(DEFAULT_CONFIG, before_defaults)
        self.assertEqual(overrides, overrides_before)

    def test_deep_merge_does_not_mutate_or_alias(self) -> None:
        base = {"a": {"b": 1, "l": [1]}}
        over = {"a": {"c": 2, "l": [9]}}
        merged = deep_merge(base, over)
        self.assertEqual(merged, {"a": {"b": 1, "c": 2, "l": [9]}})
        self.assertEqual(base, {"a": {"b": 1, "l": [1]}})
        merged["a"]["l"].append(0)
        self.assertEqual(over["a"]["l"], [9])

    def test_config_is_immutable(self) -> None:
        cfg = load_config()
        with self.assertRaises(AttributeError):
            cfg.language = "pt-BR"  # type: ignore[misc]

    def test_invalid_values_are_rejected(self) -> None:
        bad_docs = [
            {"language": "fr"},
            {"unknown_section": {}},
            {"limits": {"max_attempts": 0}},
            {"limits": {"max_attempts": "3"}},
            {"models": {"tiers": {"economy": []}}},
            {"models": {"tiers": {"gold": ["x"]}}},
            {"decision": {"provider": "magic"}},
            {"permissions": {"allow_shell": "yes"}},
            {"remote": {"hosts": [{"environment": "x"}]}},
            {"context": {"elide_at": 0.9, "summarize_at": 0.5}},
            {"context": {"elide_at": 1.5}},
        ]
        for doc in bad_docs:
            with self.subTest(doc=doc), self.assertRaises(ValidationError) as ctx:
                load_config(self.write(doc))
            self.assertEqual(ctx.exception.code, "invalid_config")
            self.assertTrue(ctx.exception.details["errors"])

    def test_invalid_overrides_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            load_config(None, {"limits": {"max_parallel": -1}})

    def test_missing_and_malformed_files(self) -> None:
        with self.assertRaises(NotFound):
            load_config("/nonexistent/wev.json")
        with self.assertRaises(ValidationError) as ctx:
            load_config(self.write("{not json"))
        self.assertEqual(ctx.exception.code, "invalid_json")
        with self.assertRaises(ValidationError):
            load_config(self.write("[1]"))

    def test_harness_section_has_documented_defaults(self) -> None:
        harness = load_config().harness
        self.assertEqual(
            (harness.planning, harness.executor_tier, harness.tool_profile),
            ("auto", "auto", "structured"),
        )
        self.assertEqual((harness.plan_reminder, harness.plan_reminder_max_chars), (True, 600))
        self.assertEqual(harness.tool_selection, "off")
        self.assertEqual(load_config().agents.default_agent, "senior-engineer")

    def test_harness_section_accepts_each_choice_and_rejects_others(self) -> None:
        good = {
            "planning": "never",
            "executor_tier": "premium",
            "plan_reminder": False,
            "plan_reminder_max_chars": 200,
            "tool_profile": "lean",
            "tool_selection": "provider",
            "baseline_checks": False,
        }
        self.assertEqual(load_config(None, {"harness": good}).harness.to_dict(), good)
        for bad in (
            {"planning": "sometimes"},
            {"executor_tier": "gold"},
            {"tool_profile": "bash"},
            {"tool_selection": "jev"},
            {"plan_reminder": "yes"},
            {"plan_reminder_max_chars": 10},
            {"unknown": 1},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                load_config(None, {"harness": bad})

    def test_unknown_tier_name(self) -> None:
        with self.assertRaises(ValidationError):
            load_config().models.tier("gold")


if __name__ == "__main__":
    unittest.main()
