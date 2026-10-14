"""The shipped git hooks in ``.githooks/``: they are run for real against temporary repositories.

Nothing here touches the repository under test: every repository is created in a temporary
directory, ``make`` is replaced by a fake program, and the fabricated secret is built at runtime.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / ".githooks"
SCANNER = ROOT / "scripts" / "scan_secrets.py"
ZERO_SHA = "0" * 40
FAKE_AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
DOT_ENV = "." + "env"
IDENTITY = ("-c", "user.name=Hook Test", "-c", "user.email=hook-test@example.invalid")
SUBJECT_LIMIT = 72


def clean_env(extra_path: Path | None = None) -> dict[str, str]:
    """An environment that ignores the user's and the system's git configuration."""
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(name, None)
    if extra_path is not None:
        env["PATH"] = f"{extra_path}{os.pathsep}{env['PATH']}"
    return env


def run(
    args: list[str], cwd: Path, env: dict[str, str] | None = None, stdin: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, env=env or clean_env(), input=stdin, capture_output=True, text=True
    )


def init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, env=clean_env(), check=True)


def commit_all(root: Path, message: str = "chore: seed") -> str:
    env = clean_env()
    subprocess.run(["git", "add", "-A"], cwd=root, env=env, check=True)
    subprocess.run(["git", *IDENTITY, "commit", "-q", "-m", message], cwd=root, env=env, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, env=env, check=True, capture_output=True, text=True
    )
    return head.stdout.strip()


class HookFilesTests(unittest.TestCase):
    def test_every_hook_exists_is_executable_and_uses_posix_sh(self) -> None:
        for name in ("commit-msg", "pre-commit", "pre-push"):
            path = HOOKS / name
            self.assertTrue(path.is_file(), name)
            self.assertTrue(path.stat().st_mode & stat.S_IXUSR, f"{name} is not executable")
            self.assertEqual(path.read_text(encoding="utf-8").splitlines()[0], "#!/bin/sh")


class CommitMsgTests(unittest.TestCase):
    def check(self, message: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "COMMIT_EDITMSG"
            path.write_text(message, encoding="utf-8")
            return run([str(HOOKS / "commit-msg"), str(path)], Path(tmp))

    def test_accepts_every_documented_type_with_and_without_scope(self) -> None:
        types = (
            "feat",
            "fix",
            "refactor",
            "docs",
            "test",
            "chore",
            "perf",
            "ci",
            "build",
            "revert",
        )
        for kind in types:
            for subject in (f"{kind}: add the thing", f"{kind}(hooks): add the thing"):
                result = self.check(subject + "\n\nBody text.\n")
                self.assertEqual(result.returncode, 0, (subject, result.stderr))

    def test_accepts_a_subject_of_exactly_the_limit(self) -> None:
        subject = "fix: " + "x" * (SUBJECT_LIMIT - len("fix: "))
        self.assertEqual(len(subject), SUBJECT_LIMIT)
        self.assertEqual(self.check(subject + "\n").returncode, 0)

    def test_allows_merge_and_revert_commits_generated_by_git(self) -> None:
        for subject in ("Merge branch 'topic' into main", 'Revert "feat: add the thing"'):
            self.assertEqual(self.check(subject + "\n").returncode, 0, subject)

    def test_ignores_comment_lines_before_the_subject(self) -> None:
        self.assertEqual(self.check("# a comment\nfix: real subject\n").returncode, 0)

    def test_rejects_bad_subjects_with_a_helpful_message(self) -> None:
        too_long = "fix: " + "x" * (SUBJECT_LIMIT - len("fix: ") + 1)
        bad = {
            "empty": "",
            "only comments": "# nothing here\n",
            "no type": "add the thing",
            "unknown type": "feature: add the thing",
            "upper case type": "Fix: add the thing",
            "missing space": "fix:add the thing",
            "no description": "fix: ",
            "trailing period": "fix: add the thing.",
            "too long": too_long,
            "bad scope": "fix(Bad Scope): add the thing",
        }
        for label, message in bad.items():
            result = self.check(message + "\n")
            self.assertEqual(result.returncode, 1, label)
            self.assertIn("commit-msg:", result.stderr, label)
            self.assertIn("<type>: <description>", result.stderr, label)

    def test_a_missing_message_file_fails(self) -> None:
        result = run([str(HOOKS / "commit-msg")], ROOT)
        self.assertEqual(result.returncode, 1)


class PreCommitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        init_repo(self.root)
        (self.root / "scripts").mkdir()
        shutil.copy(SCANNER, self.root / "scripts" / "scan_secrets.py")

    def stage(self, name: str, data: bytes | str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        subprocess.run(["git", "add", "--", name], cwd=self.root, env=clean_env(), check=True)

    def hook(self) -> subprocess.CompletedProcess[str]:
        return run([str(HOOKS / "pre-commit")], self.root)

    def test_nothing_staged_passes(self) -> None:
        self.assertEqual(self.hook().returncode, 0)

    def test_clean_staged_files_pass(self) -> None:
        self.stage("README.md", "Plain text.\n")
        self.stage(".env.example", "API_URL=\n")
        result = self.hook()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_staged_secret_is_rejected_and_its_value_is_not_printed(self) -> None:
        self.stage("config.txt", f"key = {FAKE_AWS}\n")
        result = self.hook()
        self.assertEqual(result.returncode, 1)
        self.assertIn("aws-access-key-id", result.stdout)
        self.assertNotIn(FAKE_AWS, result.stdout + result.stderr)

    def test_a_secret_in_a_file_that_is_not_staged_is_ignored(self) -> None:
        self.stage("ok.txt", "clean\n")
        (self.root / "later.txt").write_text(FAKE_AWS)
        self.assertEqual(self.hook().returncode, 0)

    def test_private_file_names_are_rejected(self) -> None:
        for name in (
            DOT_ENV,
            DOT_ENV + ".local",
            "deploy/server.pem",
            "id_rsa",
            "id_ed25519",
            "keys/store.p12",
            "credentials.json",
            "gcp/service-account-prod.json",
        ):
            with self.subTest(name=name):
                subprocess.run(
                    ["git", "rm", "-rq", "--cached", "--ignore-unmatch", "."],
                    cwd=self.root,
                    env=clean_env(),
                    check=True,
                )
                self.stage(name, "harmless placeholder\n")
                result = self.hook()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(name, result.stderr)

    def test_a_file_over_one_mebibyte_is_rejected(self) -> None:
        self.stage("big.bin", b"a" * (1024 * 1024 + 1))
        result = self.hook()
        self.assertEqual(result.returncode, 1)
        self.assertIn("larger than 1 MiB", result.stderr)

    def test_a_file_of_exactly_one_mebibyte_passes(self) -> None:
        self.stage("edge.bin", b"a" * (1024 * 1024))
        self.assertEqual(self.hook().returncode, 0)


class PrePushTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "repo"
        self.root.mkdir()
        self.bin = base / "bin"
        self.bin.mkdir()
        self.log = base / "make.log"
        fake = self.bin / "make"
        fake.write_text(
            '#!/bin/sh\necho "$@" >> "$FAKE_MAKE_LOG"\n'
            '[ "$1" = "${FAKE_MAKE_FAIL:-none}" ] && exit 1\nexit 0\n',
            encoding="utf-8",
        )
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        init_repo(self.root)
        (self.root / "tracked.txt").write_text("one\n")
        self.head = commit_all(self.root)

    def hook(self, remote_ref: str, local_sha: str | None = None, fail: str = "none"):  # type: ignore[no-untyped-def]
        env = clean_env(self.bin)
        env["FAKE_MAKE_LOG"] = str(self.log)
        env["FAKE_MAKE_FAIL"] = fail
        line = f"refs/heads/work {local_sha or self.head} {remote_ref} {ZERO_SHA}\n"
        return run([str(HOOKS / "pre-push")], self.root, env=env, stdin=line)

    def make_calls(self) -> list[str]:
        return self.log.read_text().split("\n")[:-1] if self.log.exists() else []

    def test_git_hook_environment_does_not_redirect_fixture_repositories(self) -> None:
        foreign = Path(self.tmp.name) / "foreign.git"
        fake = self.bin / "make"
        fake.write_text(
            "#!/bin/sh\n"
            'git init -q --bare "$FAKE_FOREIGN_REPO" || exit 1\n'
            'echo "$@" >> "$FAKE_MAKE_LOG"\n',
            encoding="utf-8",
        )
        env = clean_env(self.bin)
        env["FAKE_MAKE_LOG"] = str(self.log)
        env["FAKE_FOREIGN_REPO"] = str(foreign)
        for name, value in (
            ("GIT_DIR", self.root / ".git"),
            ("GIT_COMMON_DIR", self.root / ".git"),
            ("GIT_WORK_TREE", self.root),
            ("GIT_INDEX_FILE", self.root / ".git" / "index"),
        ):
            env[name] = str(value)
        line = f"refs/heads/main {self.head} refs/heads/main {ZERO_SHA}\n"
        result = run([str(HOOKS / "pre-push")], self.root, env=env, stdin=line)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((foreign / "HEAD").is_file())
        original = run(["git", "config", "--bool", "core.bare"], self.root)
        self.assertEqual(original.stdout.strip(), "false")
        self.assertEqual(self.make_calls(), ["test", "lint"])

    def test_a_clean_push_runs_test_then_lint(self) -> None:
        result = self.hook("refs/heads/feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.make_calls(), ["test", "lint"])

    def test_a_failing_test_suite_blocks_the_push_and_skips_lint(self) -> None:
        result = self.hook("refs/heads/feature", fail="test")
        self.assertEqual(result.returncode, 1)
        self.assertIn("make test failed", result.stderr)
        self.assertEqual(self.make_calls(), ["test"])

    def test_a_failing_lint_blocks_the_push(self) -> None:
        result = self.hook("refs/heads/feature", fail="lint")
        self.assertEqual(result.returncode, 1)
        self.assertIn("make lint failed", result.stderr)

    def test_push_to_main_with_modified_tracked_files_is_refused_before_make_runs(self) -> None:
        (self.root / "tracked.txt").write_text("two\n")
        result = self.hook("refs/heads/main")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted changes", result.stderr)
        self.assertEqual(self.make_calls(), [])

    def test_push_to_main_ignores_untracked_files(self) -> None:
        (self.root / "scratch.txt").write_text("not tracked\n")
        self.assertEqual(self.hook("refs/heads/main").returncode, 0)

    def test_a_dirty_tree_does_not_block_a_push_to_another_branch(self) -> None:
        (self.root / "tracked.txt").write_text("two\n")
        self.assertEqual(self.hook("refs/heads/feature").returncode, 0)

    def test_deleting_a_remote_branch_skips_the_suite(self) -> None:
        result = self.hook("refs/heads/feature", local_sha=ZERO_SHA)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.make_calls(), [])


if __name__ == "__main__":
    unittest.main()
