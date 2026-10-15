"""Tests for scripts/versioning.py against throwaway git repositories in temp directories."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "versioning.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("versioning", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["versioning"] = module
    spec.loader.exec_module(module)
    return module


versioning = _load()


def clean_env() -> dict[str, str]:
    """An environment that ignores the user's and the system's git configuration."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    return env


class Repo:
    """A temporary repository with a few helpers to build history."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.counter = 0
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Version Test")
        self.git("config", "user.email", "version-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "tag.gpgsign", "false")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=self.root, env=clean_env(), capture_output=True, text=True
        )
        if result.returncode != 0:
            raise AssertionError(f"git {args} failed: {result.stderr}")
        return result.stdout.strip()

    def commit(self, subject: str = "chore: change") -> str:
        self.counter += 1
        (self.root / f"file{self.counter}.txt").write_text(f"{self.counter}\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"{subject} {self.counter}")
        return self.git("rev-parse", "HEAD")

    def merge_mr(self, count: int, into: str = "dev", name: str = "feature") -> None:
        """Merge a branch with ``count`` commits into ``into`` with a merge commit."""
        self.git("switch", "-q", "-c", name, into)
        for _ in range(count):
            self.commit("feat: work")
        self.git("switch", "-q", into)
        self.git(
            "merge", "-q", "--no-ff", "-m", f"Merge pull request #{self.counter} from {name}", name
        )
        self.git("branch", "-q", "-D", name)

    def release(self) -> None:
        """Merge dev into main (merge commit), add a release commit, tag it, fast-forward dev."""
        major = versioning.next_release(self.root, "main").major
        self.git("switch", "-q", "main")
        self.git("merge", "-q", "--no-ff", "-m", "Merge pull request #99 from owner/dev", "dev")
        self.commit("chore(release): bump")
        self.git("tag", "-a", f"v{major}.0.0", "-m", f"v{major}.0.0")
        self.git("switch", "-q", "dev")
        self.git("merge", "-q", "--ff-only", "main")

    def version(self, ref: str = "HEAD") -> str:
        return str(versioning.compute(self.root, ref))


class VersioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Repo(Path(self._tmp.name))

    def seed_dev(self) -> None:
        self.repo.commit("chore: seed")
        self.repo.git("tag", "-a", "v1.0.0", "-m", "v1.0.0")
        self.repo.git("switch", "-q", "-c", "dev")

    def test_no_tag_counts_from_whole_history(self) -> None:
        self.repo.commit()
        self.repo.commit()
        self.assertEqual("0.1.2", self.repo.version())

    def test_no_tag_next_release_is_one(self) -> None:
        self.repo.commit()
        self.assertEqual("1.0.0", str(versioning.next_release(self.repo.root)))

    def test_tag_only_is_the_release_itself(self) -> None:
        self.seed_dev()
        self.assertEqual("1.0.0", self.repo.version())

    def test_one_mr_with_three_commits(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(3)
        self.assertEqual("1.1.3", self.repo.version())

    def test_second_mr_resets_the_patch(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(3)
        self.repo.merge_mr(2)
        self.assertEqual("1.2.2", self.repo.version())

    def test_feature_branch_in_progress_is_what_dev_becomes(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(3)
        self.repo.merge_mr(2)
        self.repo.git("switch", "-q", "-c", "feature", "dev")
        for _ in range(4):
            self.repo.commit("feat: more")
        self.assertEqual("1.3.4", self.repo.version())
        self.repo.git("switch", "-q", "dev")
        self.repo.git(
            "merge", "-q", "--no-ff", "-m", "Merge pull request #7 from feature", "feature"
        )
        self.assertEqual("1.3.4", self.repo.version())

    def test_direct_commit_on_dev_after_a_merge_counts_as_k(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(2)
        self.repo.commit("fix: direct")
        self.assertEqual("1.2.1", self.repo.version())

    def test_merge_counts_only_the_branch_own_commits(self) -> None:
        self.seed_dev()
        self.repo.git("switch", "-q", "-c", "feature", "dev")
        self.repo.commit()
        self.repo.git("switch", "-q", "dev")
        self.repo.commit("chore: dev moved")
        self.repo.git("switch", "-q", "feature")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge dev into feature", "dev")
        self.repo.commit()
        self.repo.git("switch", "-q", "dev")
        self.repo.git(
            "merge", "-q", "--no-ff", "-m", "Merge pull request #5 from feature", "feature"
        )
        # Only the branch's own commits count: the commit dev gained meanwhile and the merge of dev
        # into the branch do not.
        self.assertEqual("1.1.2", self.repo.version())

    def test_next_release_increments_the_major_of_the_latest_tag(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(2)
        self.assertEqual("2.0.0", str(versioning.next_release(self.repo.root)))

    def test_non_version_tags_are_ignored(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(1)
        for name in ("v9", "v9.9", "v10.0.0-rc1", "vnext", "release-5.0.0"):
            self.repo.git("tag", name)
        self.assertEqual("1.1.1", self.repo.version())
        self.assertEqual("2.0.0", str(versioning.next_release(self.repo.root)))

    def test_highest_tag_wins(self) -> None:
        self.seed_dev()
        self.repo.commit()
        self.repo.git("tag", "-a", "v2.0.0", "-m", "v2.0.0")
        self.assertEqual("2.0.0", self.repo.version())

    def test_release_then_fast_forward_adds_no_merges(self) -> None:
        self.seed_dev()
        self.repo.merge_mr(3)
        self.repo.release()
        self.assertEqual("2.0.0", self.repo.version("dev"))
        self.assertEqual(self.repo.git("rev-parse", "dev"), self.repo.git("rev-parse", "main"))
        self.repo.merge_mr(2)
        self.assertEqual("2.1.2", self.repo.version("dev"))
        self.repo.release()
        self.assertEqual("3.0.0", self.repo.version("dev"))

    def test_unknown_ref_raises(self) -> None:
        self.repo.commit()
        with self.assertRaises(versioning.VersioningError):
            versioning.compute(self.repo.root, "no-such-ref")


class CliTests(unittest.TestCase):
    def run_cli(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(root), *args],
            env=clean_env(),
            capture_output=True,
            text=True,
        )

    def test_prints_version_and_next_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(Path(tmp))
            repo.commit()
            repo.git("tag", "-a", "v4.0.0", "-m", "v4.0.0")
            repo.git("switch", "-q", "-c", "dev")
            repo.merge_mr(2)
            self.assertEqual("4.1.2\n", self.run_cli(repo.root).stdout)
            self.assertEqual("4.1.2\n", self.run_cli(repo.root, "--ref", "dev").stdout)
            self.assertEqual("5.0.0\n", self.run_cli(repo.root, "--next-release").stdout)

    def test_bad_ref_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Repo(Path(tmp))
            repo.commit()
            result = self.run_cli(repo.root, "--ref", "nope")
            self.assertEqual(1, result.returncode)
            self.assertIn("versioning:", result.stderr)


if __name__ == "__main__":
    unittest.main()
