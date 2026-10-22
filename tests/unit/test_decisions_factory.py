from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures.fake_jev_server import fake_jev
from wev_skills import i18n
from wev_skills.config import Config, DecisionConfig, JevConfig
from wev_skills.core.contracts import TaskSignals
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.decisions import jev_http
from wev_skills.decisions.factory import build_provider
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.local import LocalPolicyProvider


def config(provider: str) -> Config:
    decision = DecisionConfig(
        provider=provider, jev=JevConfig(command="myjev", timeout_seconds=7.0)
    )
    return dataclasses.replace(Config(), decision=decision)


class FactoryTests(unittest.TestCase):
    def test_local(self) -> None:
        p = build_provider(config("local"), SubprocessRunner(), str)
        self.assertIsInstance(p, LocalPolicyProvider)

    def test_jev_uses_config(self) -> None:
        p = build_provider(config("jev"), SubprocessRunner(), str)
        self.assertIsInstance(p, JevProvider)
        self.assertEqual(p.provider_id, "jev")
        self.assertEqual(p._command, ("myjev",))  # type: ignore[attr-defined]
        self.assertEqual(p._timeout, 7.0)  # type: ignore[attr-defined]

    def test_unknown_provider(self) -> None:
        with self.assertRaises(ValidationError):
            build_provider(config("nope"), SubprocessRunner(), str)


ANSWERS = {
    "complexity": {"type": "score", "score": 0, "confidence": 0.9},
    "risk": {"type": "choice", "choice": "low", "confidence": 0.9},
    "parallelizable": {"type": "noul", "noul": 0.1},
}


class BuiltinDefaultTests(unittest.TestCase):
    def setUp(self) -> None:
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = {"HOME": tmp.name, "XDG_CONFIG_HOME": str(Path(tmp.name) / "cfg")}
        env = mock.patch.dict(os.environ, base)
        env.start()
        self.addCleanup(env.stop)
        for name in ("JEV_API_URL", "TYPESAFE_API_KEY"):
            os.environ.pop(name, None)
        keychain = mock.patch.object(jev_http, "macos_keychain", lambda: None)
        keychain.start()
        self.addCleanup(keychain.stop)

    def provider(self) -> JevProvider:
        decision = DecisionConfig(provider="jev")
        built = build_provider(
            dataclasses.replace(Config(), decision=decision), SubprocessRunner(), str
        )
        assert isinstance(built, JevProvider)
        return built

    def test_builtin_is_default_and_uses_http(self) -> None:
        body = json.dumps({"answers": ANSWERS}).encode()
        with fake_jev([(200, body, 0)]) as server:
            os.environ["JEV_API_URL"] = server.url
            result = self.provider().classify_task(TaskSignals(objective="add a feature"))
            seen = len(server.requests)
        self.assertEqual(seen, 1)
        self.assertEqual(result.source, "jev")
        self.assertFalse(any("unavailable" in reason for reason in result.reasons))

    def test_builtin_without_key_falls_back_locally(self) -> None:
        result = self.provider().classify_task(TaskSignals(objective="add a feature"))
        self.assertEqual(result.source, "local-policy")
        self.assertIn("no JEV key was found", result.reasons[0])

    def test_a_key_added_after_a_failed_call_is_picked_up(self) -> None:
        provider = self.provider()
        first = provider.classify_task(TaskSignals(objective="add a feature"))
        self.assertEqual(first.source, "local-policy")
        body = json.dumps({"answers": ANSWERS}).encode()
        with fake_jev([(200, body, 0)]) as server:
            os.environ["JEV_API_URL"] = server.url
            second = provider.classify_task(TaskSignals(objective="add a feature"))
        self.assertEqual(second.source, "jev")


if __name__ == "__main__":
    unittest.main()
