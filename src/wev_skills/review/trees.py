"""Git trees that fix the state of a working tree, and the lines a diff between two touches."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import StateConflict
from wev_skills.core.ports import Runner
from wev_skills.evaluation.workspace import run_git

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_NEW_PATH = re.compile(r"^\+\+\+ (?:b/(.*)|/dev/null)$")


def _checked(result: RawCommandResult, step: str) -> str:
    if result.timed_out or result.exit_code != 0:
        error = result.stderr.strip() or step
        message = i18n.t("review.error.tree_failed", step=step, error=error)
        raise StateConflict("review_tree_failed", message, {"step": step})
    return result.stdout


def write_tree(runner: Runner, root: Path) -> str:
    """The tree id of the working tree, untracked and not-ignored files included.

    Built in a temporary index, so no ref and not the real index changes.
    """
    with tempfile.TemporaryDirectory(prefix="wev-index-") as scratch:
        env: Mapping[str, str] = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}

        def git(*args: str) -> str:
            return _checked(run_git(runner, root, *args, env=env), args[0])

        if run_git(runner, root, "rev-parse", "--verify", "-q", "HEAD").exit_code == 0:
            git("read-tree", "HEAD")  # a repository without commits starts from an empty index
        git("add", "-A")
        return git("write-tree").strip()


def diff_trees(runner: Runner, root: Path, old: str, new: str, context: int = 3) -> str:
    """The unified diff from tree ``old`` to tree ``new``; renames show as delete plus add."""
    argv = ("diff", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames")
    return _checked(run_git(runner, root, *argv, f"--unified={context}", old, new), "diff")


def touched_lines(diff: str) -> dict[str, frozenset[int]]:
    """New-side line numbers added or changed per path in a ``--unified=0`` diff.

    Shortcut: a path git quotes (tab, quote, backslash or non-ASCII byte) is not matched
    and is left out; upgrade when review must cover such file names.
    """
    found: dict[str, set[int]] = {}
    path: str | None = None
    for line in diff.splitlines():
        header = _NEW_PATH.match(line)
        if header:
            path = header.group(1)  # None for a deleted file
            continue
        hunk = _HUNK.match(line)
        if hunk and path is not None:
            start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
            if count:
                found.setdefault(path, set()).update(range(start, start + count))
    return {name: frozenset(lines) for name, lines in found.items()}
