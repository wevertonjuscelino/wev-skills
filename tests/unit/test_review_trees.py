import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import cli, i18n
from wev_skills.core.errors import StateConflict
from wev_skills.core.ports import SubprocessRunner
from wev_skills.review.trees import diff_trees, touched_lines, touched_or_cut_lines, write_tree
from wev_skills.state.model import RunState

DIFF = """diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,0 +3,2 @@
+x
+y
@@ -9 +10,0 @@
-gone
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -5 +10 @@
-old
+new
diff --git a/d.py b/d.py
--- a/d.py
+++ b/d.py
@@ -4,2 +3,0 @@
-cut
-cut
diff --git a/c.py b/c.py
deleted file mode 100644
--- a/c.py
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
"""


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


class RepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("ignored.txt\nstate/\n")
        (self.root / "a.txt").write_text("1\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "one")
        self.runner = SubprocessRunner()


class TreesTest(RepoCase):
    def test_write_tree_includes_untracked_and_leaves_index_alone(self) -> None:
        (self.root / "new.txt").write_text("n\n")
        before = git(self.root, "status", "--porcelain")
        tree = write_tree(self.runner, self.root)
        self.assertIn("new.txt", git(self.root, "ls-tree", "-r", "--name-only", tree))
        self.assertEqual(git(self.root, "status", "--porcelain"), before)
        self.assertEqual(git(self.root, "diff", "--cached", "--name-only"), "")

    def test_write_tree_skips_ignored_files(self) -> None:
        (self.root / "ignored.txt").write_text("i\n")
        (self.root / "state").mkdir()
        (self.root / "state" / "run.json").write_text("{}")
        names = git(self.root, "ls-tree", "-r", "--name-only", write_tree(self.runner, self.root))
        self.assertNotIn("ignored.txt", names)
        self.assertNotIn("state/run.json", names)

    def test_write_tree_works_in_a_repository_without_commits(self) -> None:
        empty = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, empty, True)
        git(empty, "init", "-q")
        (empty / "f.txt").write_text("f\n")
        tree = write_tree(self.runner, empty)
        self.assertEqual(git(empty, "ls-tree", "-r", "--name-only", tree), "f.txt")

    def test_write_tree_outside_a_repository_is_a_state_conflict(self) -> None:
        plain = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, plain, True)
        with self.assertRaises(StateConflict) as caught:
            write_tree(self.runner, plain)
        self.assertEqual(caught.exception.code, "review_tree_failed")

    def test_diff_trees_shows_only_changes_between_the_trees(self) -> None:
        old = write_tree(self.runner, self.root)
        (self.root / "a.txt").write_text("1\n2\n")
        diff = diff_trees(self.runner, self.root, old, write_tree(self.runner, self.root), 0)
        self.assertEqual(touched_lines(diff), {"a.txt": frozenset({2})})

    def test_round_trip_with_a_spaced_path_and_a_deleted_file(self) -> None:
        (self.root / "a b.py").write_text("1\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "two")
        old = write_tree(self.runner, self.root)
        (self.root / "a b.py").write_text("1\n2\n")
        (self.root / "a.txt").unlink()
        diff = diff_trees(self.runner, self.root, old, write_tree(self.runner, self.root), 0)
        self.assertEqual(touched_lines(diff), {"a b.py": frozenset({2})})

    def test_content_lines_that_look_like_headers_stay_credited_to_the_file(self) -> None:
        text = (
            "diff --git a/x b/x\n--- a/x\n+++ b/x\n"
            "@@ -3,2 +3,2 @@\n--- a/y\n-old\n+++ b/evil\n+new\n"
            "@@ -9,0 +10 @@\n+z\n"
        )
        self.assertEqual(touched_lines(text), {"x": frozenset({3, 4, 10})})

    def test_line_separators_inside_file_content_do_not_split_diff_lines(self) -> None:
        for sep in ("\x0c", "\r", "\x85", "\u2028"):
            text = (
                "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -0,0 +1,4 @@\n"
                f"+a{sep}+b{sep}+c\n+{sep}diff --git a/evil b/evil\n"
                f"+{sep}+++ b/evil\n+{sep}@@ -0,0 +1,50 @@\n"
            )
            self.assertEqual(touched_lines(text), {"x": frozenset({1, 2, 3, 4})}, repr(sep))

    def test_a_body_line_beyond_the_counts_is_a_malformed_diff(self) -> None:
        head = "diff --git a/x b/x\n--- a/x\n+++ b/x\n"
        for body in (
            "@@ -0,0 +1 @@\n+a\n+b\n",
            "@@ -1 +1 @@\n-a\n-b\n+c\n",
            "@@ -0,0 +1,2 @@\n+a\n",
            "@@ -0,0 +1,2 @@\n+a\n-b\n+c\n",
        ):
            with self.assertRaises(StateConflict) as caught:
                touched_lines(head + body)
            self.assertEqual(caught.exception.code, "review_tree_failed")

    def test_many_files_are_hashed_in_few_git_calls(self) -> None:
        for number in range(300):
            (self.root / f"{'n' * 200}-{number}.txt").write_text(f"{number}\n")
        calls: list[tuple[str, ...]] = []

        class Counting(SubprocessRunner):
            def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
                calls.append(tuple(argv))
                return super().run(argv, cwd, timeout, env)

        tree = write_tree(Counting(), self.root)
        self.assertEqual(
            len(git(self.root, "ls-tree", "-r", "--name-only", tree).splitlines()), 302
        )
        self.assertLess(len(calls), 12)

    def test_write_tree_runs_no_attribute_driven_filter(self) -> None:
        marker = self.root.parent / f"{self.root.name}-marker"
        self.addCleanup(marker.unlink, True)
        (self.root / ".gitattributes").write_text("* filter=evil\n")
        (self.root / "info").write_text("x\n")
        git(self.root, "config", "filter.evil.clean", f"touch {marker}; cat")
        (self.root / "raw.txt").write_text("raw\r\nbytes\n")
        tree = write_tree(self.runner, self.root)
        self.assertFalse(marker.exists())
        blob = git(self.root, "rev-parse", f"{tree}:raw.txt")
        shown = subprocess.run(
            ("git", "cat-file", "blob", blob), cwd=self.root, capture_output=True, check=True
        )
        self.assertEqual(shown.stdout, b"raw\r\nbytes\n")

    def test_tree_equals_what_git_add_would_write(self) -> None:
        (self.root / "run.sh").write_text("#!/bin/sh\n")
        (self.root / "run.sh").chmod(0o755)
        (self.root / "link").symlink_to("a.txt")
        (self.root / "sub" / "deep").mkdir(parents=True)
        (self.root / "sub" / "deep" / "f.txt").write_text("f\n")
        git(self.root, "add", "link")
        (self.root / "a.txt").unlink()
        sub = self.root / "sub"
        tree = write_tree(self.runner, sub)  # a subdirectory of the repository
        index = self.root.parent / f"{self.root.name}-ref-index"
        self.addCleanup(index.unlink, True)
        env = {**os.environ, "GIT_INDEX_FILE": str(index)}
        for args in (("read-tree", "HEAD"), ("add", "-A")):
            subprocess.run(("git", *args), cwd=self.root, env=env, check=True)
        expected = subprocess.run(
            ("git", "write-tree"), cwd=self.root, env=env, capture_output=True, text=True
        ).stdout.strip()
        self.assertEqual(tree, expected)

    def test_info_attributes_do_not_run_filters_either(self) -> None:
        marker = self.root.parent / f"{self.root.name}-marker2"
        self.addCleanup(marker.unlink, True)
        (self.root / ".git" / "info" / "attributes").write_text("* filter=evil\n")
        git(self.root, "config", "filter.evil.clean", f"touch {marker}; cat")
        write_tree(self.runner, self.root)
        self.assertFalse(marker.exists())

    def test_touched_lines_reads_hunks(self) -> None:
        self.assertEqual(touched_lines(DIFF), {"a.py": frozenset({3, 4}), "b.py": frozenset({10})})

    def test_a_cut_touches_the_lines_around_it_only_in_the_cut_variant(self) -> None:
        self.assertEqual(touched_or_cut_lines(DIFF)["d.py"], frozenset({3, 4}))
        self.assertEqual(touched_or_cut_lines(DIFF)["a.py"], touched_lines(DIFF)["a.py"] | {10, 11})
        self.assertNotIn("d.py", touched_lines(DIFF))

    def test_a_pure_deletion_touches_no_line(self) -> None:
        self.assertNotIn("c.py", touched_lines(DIFF))
        self.assertNotIn("d.py", touched_lines(DIFF))


class RunBaseTest(RepoCase):
    def run_cli(self, *argv: str) -> int:
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            i18n.use_language("en"),
        ):
            return cli.main(["--config", "wev.json", *argv])

    def state(self) -> RunState:
        path = self.root / "state" / "runs" / "r1" / "state.json"
        return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def start(self, review: bool = True) -> None:
        config: dict[str, object] = {"state_dir": "state"}
        if review:
            config["review"] = {"depth": "quick", "agent": "r"}
        (self.root / "wev.json").write_text(json.dumps(config))
        previous = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, previous)
        start = ("run", "start", "--objective", "Do it", "--files", "1", "--run-id", "r1")
        self.assertEqual(self.run_cli(*start), 0)

    def test_run_start_records_base_and_resume_keeps_it(self) -> None:
        self.start()
        base = self.state().base
        self.assertTrue(base)
        (self.root / "a.txt").write_text("changed\n")
        self.assertEqual(self.run_cli("run", "resume"), 0)
        self.assertEqual(self.state().base, base)

    def test_uncommitted_change_at_start_is_in_base(self) -> None:
        (self.root / "a.txt").write_text("dirty\n")
        self.start()
        now = write_tree(self.runner, self.root)
        self.assertEqual(diff_trees(self.runner, self.root, self.state().base, now), "")

    def test_run_start_outside_a_repository_leaves_base_empty(self) -> None:
        shutil.rmtree(self.root / ".git")
        self.start()
        self.assertEqual(self.state().base, "")

    def test_a_failed_base_in_a_repository_is_recorded_as_a_decision(self) -> None:
        failing = StateConflict("review_tree_failed", "boom")
        with mock.patch("wev_skills.core.run_start.write_tree", side_effect=failing):
            self.start()
        state = self.state()
        self.assertEqual(state.base, "")
        with i18n.use_language("en"):
            expected = i18n.t("review.decision.base_missing")
        self.assertIn(expected, [d.decision for d in state.decisions])

    def test_with_review_off_base_stays_empty_and_no_decision_is_recorded(self) -> None:
        self.start(review=False)
        state = self.state()
        self.assertEqual(state.base, "")
        with i18n.use_language("en"):
            missing = i18n.t("review.decision.base_missing")
        self.assertNotIn(missing, [d.decision for d in state.decisions])

    def test_state_without_base_loads(self) -> None:
        self.start()
        data = self.state().to_dict()
        del data["base"]
        self.assertEqual(RunState.from_dict(data).base, "")
