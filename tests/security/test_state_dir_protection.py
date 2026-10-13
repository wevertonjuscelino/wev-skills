"""A command run through the engine must not be able to forge its own approval."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from wev_skills.config import Config, PermissionsConfig, load_config, protect_state_dir
from wev_skills.core import wiring
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel
from wev_skills.core.errors import PermissionDenied
from wev_skills.core.ports import SubprocessRunner

FORGED = {"schema_version": 1, "approvals": {}}


class StateDirProtectionTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def outcome(self, config: Config, *argv: str, cwd: Path | None = None) -> PermissionOutcome:
        policy = wiring.build_policy(config, self.root)
        where = str(cwd or self.root)
        return policy.check_command(argv, where, Mode.EXECUTE, RiskLevel.LOW).outcome

    def test_loaded_config_always_protects_the_state_directory(self) -> None:
        self.assertIn(".wev", load_config().permissions.protected_paths)
        custom = load_config(
            None, {"state_dir": "var/state", "permissions": {"protected_paths": []}}
        )
        self.assertIn("var/state", custom.permissions.protected_paths)
        self.assertIn(os.path.abspath("var/state"), custom.permissions.protected_paths)

    def test_protection_is_idempotent_and_does_not_mutate(self) -> None:
        config = Config(permissions=PermissionsConfig(protected_paths=()))
        once = protect_state_dir(config, self.root)
        self.assertEqual(config.permissions.protected_paths, ())
        self.assertIs(protect_state_dir(once, self.root), once)

    def test_commands_targeting_the_state_directory_are_denied(self) -> None:
        config = Config()
        targets = (
            ".wev/approvals.json",
            "./.wev/audit.jsonl",
            ".wev",
            str(self.root / ".wev" / "approvals.json"),
            "--output=.wev/approvals.json",
            "sub/../.wev/runs/r/state.json",
        )
        for target in targets:
            with self.subTest(target=target):
                self.assertIs(
                    self.outcome(config, "cp", "forged.json", target), PermissionOutcome.DENY
                )
        self.assertIs(self.outcome(config, "cat", ".wev/approvals.json"), PermissionOutcome.DENY)
        self.assertIs(self.outcome(config, "cp", "a.json", "b.json"), PermissionOutcome.ALLOW)

    def test_an_emptied_protected_list_still_protects_the_state_directory(self) -> None:
        for state_dir in ("custom-state", "nested/state", str(self.root / "abs-state")):
            config = Config(state_dir=state_dir, permissions=PermissionsConfig(protected_paths=()))
            target = str(Path(state_dir) / "approvals.json")
            with self.subTest(state_dir=state_dir):
                self.assertIs(self.outcome(config, "tee", target), PermissionOutcome.DENY)

    def test_a_subdirectory_or_a_symlink_does_not_get_around_it(self) -> None:
        config = Config(state_dir="nested/state", permissions=PermissionsConfig(protected_paths=()))
        (self.root / "nested" / "state").mkdir(parents=True)
        (self.root / "sub").mkdir()
        (self.root / "alias").symlink_to(self.root / "nested" / "state")
        self.assertIs(
            self.outcome(config, "tee", "../nested/state/approvals.json", cwd=self.root / "sub"),
            PermissionOutcome.DENY,
        )
        self.assertIs(self.outcome(config, "tee", "alias/approvals.json"), PermissionOutcome.DENY)

    def test_the_executor_refuses_before_anything_runs_and_no_approval_appears(self) -> None:
        config = Config()
        executor = wiring.build_executor(config, self.root, self.root / "logs", SubprocessRunner())
        (self.root / "forged.json").write_text(json.dumps(FORGED), encoding="utf-8")
        with self.assertRaises(PermissionDenied):
            executor.run(
                ("cp", "forged.json", ".wev/approvals.json"),
                str(self.root),
                Mode.EXECUTE,
                RiskLevel.LOW,
            )
        self.assertFalse((self.root / ".wev" / "approvals.json").exists())
        self.assertEqual(wiring.build_approval_store(config, self.root).list(), ())


if __name__ == "__main__":
    unittest.main()
