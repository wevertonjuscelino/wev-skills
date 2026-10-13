"""``core.active``: which run is active for a directory, and the configuration it pinned."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.config import Config, config_digest, parse_config
from wev_skills.core import active, run_registry
from wev_skills.core.contracts import (
    Classification,
    Complexity,
    Mode,
    Plan,
    PlanTask,
    RiskLevel,
    TaskStatus,
)
from wev_skills.core.errors import ValidationError
from wev_skills.state import model
from wev_skills.state.model import Phase
from wev_skills.state.store import STATE_FILE, StateStore, run_dir


def tree_listing(base: Path) -> list[str]:
    return sorted(str(path.relative_to(base)) for path in base.rglob("*"))


class ActiveCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home = self.tmp / "state-home"
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def make_run(
        self,
        root: Path,
        run_id: str = "run-1",
        mode: Mode = Mode.EXECUTE,
        state_dir: str = ".wev",
        config: Config | None = None,
    ) -> StateStore:
        store = StateStore(run_dir(root / state_dir, run_id))
        pinned = config if config is not None else Config()
        store.create("objective", mode, run_id, pinned.to_dict(), config_digest(pinned), "test")
        return store

    def finish(self, store: StateStore) -> None:
        store.update(lambda state: model.with_phase(state, Phase.DONE))


class FindActiveRunTests(ActiveCase):
    def test_none_without_a_state_directory_and_nothing_is_created(self) -> None:
        before = tree_listing(self.tmp)
        self.assertIsNone(active.find_active_run(self.repo))
        self.assertEqual(tree_listing(self.tmp), before)

    def test_finds_the_run_from_a_subdirectory_with_its_pinned_values(self) -> None:
        pinned = parse_config(None, {"limits": {"max_attempts": 9}})
        self.make_run(self.repo, mode=Mode.PLAN, config=pinned)
        nested = self.repo / "src" / "pkg"
        nested.mkdir(parents=True)
        found = active.find_active_run(nested)
        assert found is not None
        self.assertEqual((found.root, found.state_dir), (self.repo, self.repo / ".wev"))
        self.assertEqual(
            (found.run_id, found.mode, found.phase), ("run-1", Mode.PLAN, Phase.REQUEST)
        )
        self.assertEqual(found.config.limits.max_attempts, 9)
        self.assertIsNone(found.state_error)

    def test_lookup_never_creates_files(self) -> None:
        self.make_run(self.repo)
        before = tree_listing(self.tmp)
        active.find_active_run(self.repo)
        self.assertEqual(tree_listing(self.tmp), before)

    def test_a_finished_run_is_not_active(self) -> None:
        self.finish(self.make_run(self.repo))
        self.assertIsNone(active.find_active_run(self.repo))

    def test_outermost_ancestor_wins_so_a_nested_repository_cannot_hide_a_run(self) -> None:
        self.make_run(self.repo, "outer", Mode.PLAN)
        nested = self.repo / "vendor" / "inner"
        (nested / ".git").mkdir(parents=True)
        self.make_run(nested, "inner", Mode.EXECUTE)
        found = active.find_active_run(nested)
        assert found is not None
        self.assertEqual((found.run_id, found.root, found.mode), ("outer", self.repo, Mode.PLAN))

    def test_risk_is_the_highest_of_the_run_and_its_running_tasks(self) -> None:
        store = self.make_run(self.repo)
        low = Classification(Complexity.SIMPLE, RiskLevel.LOW, 0.0, False, (), "t")
        plan = Plan("o", (PlanTask("a", "a", "a", risk=RiskLevel.HIGH),))

        def prepare(state: model.RunState) -> model.RunState:
            return model.with_plan(model.with_classification(state, low), plan)

        store.update(prepare)
        found = active.find_active_run(self.repo)
        assert found is not None
        self.assertIs(found.risk, RiskLevel.LOW)
        store.update(lambda state: model.with_task_status(state, "a", TaskStatus.RUNNING, "t"))
        found = active.find_active_run(self.repo)
        assert found is not None
        self.assertIs(found.risk, RiskLevel.HIGH)

    def test_corrupt_state_returns_the_most_restrictive_run_instead_of_raising(self) -> None:
        store = self.make_run(self.repo)
        (store.run_dir / STATE_FILE).write_text("{ not json", encoding="utf-8")
        found = active.find_active_run(self.repo)
        assert found is not None
        self.assertEqual((found.mode, found.risk, found.phase), (Mode.PLAN, RiskLevel.HIGH, None))
        self.assertEqual(found.run_id, "run-1")
        self.assertTrue(found.state_error)

    def test_a_readable_active_run_is_preferred_over_an_unreadable_old_one(self) -> None:
        old = self.make_run(self.repo, "old")
        (old.run_dir / STATE_FILE).write_text("[]", encoding="utf-8")
        self.make_run(self.repo, "new")
        found = active.find_active_run(self.repo)
        assert found is not None
        self.assertEqual((found.run_id, found.state_error), ("new", None))

    def test_state_directory_named_in_the_root_config_file_is_found(self) -> None:
        (self.repo / "wev.config.json").write_text(
            json.dumps({"state_dir": ".state/wev"}), encoding="utf-8"
        )
        self.make_run(self.repo, state_dir=".state/wev")
        found = active.find_active_run(self.repo)
        assert found is not None
        self.assertEqual(found.state_dir, self.repo / ".state" / "wev")


class RegistryTests(ActiveCase):
    def test_registry_lives_under_the_user_state_home(self) -> None:
        expected = self.home / "wev-skills" / "active-runs.json"
        self.assertEqual(run_registry.registry_path(), expected)
        with mock.patch.dict(os.environ, {"HOME": str(self.tmp)}):
            os.environ.pop("XDG_STATE_HOME")
            fallback = self.tmp / ".local" / "state" / "wev-skills" / "active-runs.json"
            self.assertEqual(run_registry.registry_path(), fallback)

    def test_a_registered_run_is_found_through_paths_outside_the_working_directory(self) -> None:
        self.make_run(self.repo)
        active.register_run(self.repo, self.repo / ".wev", "run-1")
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        self.assertIsNone(active.find_active_run(elsewhere))
        found = active.find_active_run(elsewhere, [self.repo / "src" / "app.py"])
        assert found is not None
        self.assertEqual((found.run_id, found.root), ("run-1", self.repo))

    def test_registered_state_directory_outside_the_default_name_is_found(self) -> None:
        self.make_run(self.repo, state_dir=".custom-state")
        active.register_run(self.repo, self.repo / ".custom-state", "run-1")
        found = active.find_active_run(self.repo)
        assert found is not None
        self.assertEqual(found.state_dir, self.repo / ".custom-state")

    def test_stale_entries_are_ignored_and_pruned_on_the_next_write(self) -> None:
        first = self.make_run(self.repo)
        active.register_run(self.repo, self.repo / ".wev", "run-1")
        self.finish(first)
        self.assertIsNone(active.find_active_run(self.tmp, [self.repo / "x"]))
        other = self.tmp / "other"
        other.mkdir()
        self.make_run(other, "run-2")
        active.register_run(other, other / ".wev", "run-2")
        entries = run_registry.read_entries()
        self.assertEqual([entry.run_id for entry in entries], ["run-2"])

    def test_unregister_removes_the_entry(self) -> None:
        self.make_run(self.repo)
        active.register_run(self.repo, self.repo / ".wev", "run-1")
        active.unregister_run(self.repo / ".wev", "run-1")
        self.assertEqual(run_registry.read_entries(), ())

    def test_a_corrupt_registry_reads_as_empty_and_is_replaced_on_write(self) -> None:
        path = run_registry.registry_path()
        path.parent.mkdir(parents=True)
        path.write_text("{ nope", encoding="utf-8")
        self.assertEqual(run_registry.read_entries(), ())
        self.make_run(self.repo)
        active.register_run(self.repo, self.repo / ".wev", "run-1")
        self.assertEqual(len(run_registry.read_entries()), 1)


class PinnedConfigTests(ActiveCase):
    def test_pinned_config_is_the_snapshot_and_defaults_for_an_old_state(self) -> None:
        pinned = parse_config(None, {"harness": {"baseline_checks": False}})
        store = self.make_run(self.repo, config=pinned)
        self.assertEqual(active.pinned_config(store.load()), pinned)
        legacy = StateStore(run_dir(self.repo / ".wev", "legacy"))
        legacy.create("objective", Mode.EXECUTE, "legacy")
        self.assertEqual(active.pinned_config(legacy.load()), Config())

    def test_mode_and_pinned_config_can_never_change_after_the_run_starts(self) -> None:
        store = self.make_run(self.repo)
        from dataclasses import replace

        with self.assertRaises(ValidationError) as caught:
            store.update(lambda state: replace(state, mode=Mode.PLAN))
        self.assertEqual(caught.exception.code, "immutable_field")
        with self.assertRaises(ValidationError):
            store.update(lambda state: replace(state, config={"language": "pt-BR"}))
        with self.assertRaises(ValidationError):
            store.update(lambda state: replace(state, config_digest="other"))


if __name__ == "__main__":
    unittest.main()
