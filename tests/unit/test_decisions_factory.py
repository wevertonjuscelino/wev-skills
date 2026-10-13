from __future__ import annotations

import dataclasses
import unittest

from wev_skills.config import Config, DecisionConfig, JevConfig
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner
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


if __name__ == "__main__":
    unittest.main()
