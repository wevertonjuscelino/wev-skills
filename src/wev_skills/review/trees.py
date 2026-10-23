"""Git trees that fix the state of a working tree, and the lines a diff between two touches."""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import StateConflict
from wev_skills.core.ports import Runner
from wev_skills.evaluation.workspace import run_git

CHUNK = 100  # paths per git call, to stay under the argument size limit
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

    Built in a temporary index, so no ref and not the real index changes. Files are hashed
    as they are (``--no-filters``): no clean filter or attribute rule of the repository runs.
    """
    with tempfile.TemporaryDirectory(prefix="wev-index-") as scratch:
        env: Mapping[str, str] = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}

        def git(*args: str) -> str:
            return _checked(run_git(runner, top, *args, env=env), args[0])

        top = Path(
            _checked(run_git(runner, root, "rev-parse", "--show-toplevel"), "rev-parse").strip()
        )
        if run_git(runner, top, "rev-parse", "--verify", "-q", "HEAD").exit_code == 0:
            git("read-tree", "HEAD")  # a repository without commits starts from an empty index
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        present, gone = _split_present(top, sorted({name for name in names if name}), Path(scratch))
        for chunk in _chunks(present):
            shas = git("hash-object", "-w", "--no-filters", "--", *(src for _, _, src in chunk))
            entries = zip(chunk, shas.split(), strict=True)
            args = [a for (name, mode, _), sha in entries for a in ("--cacheinfo", mode, sha, name)]
            git("update-index", "--add", "--replace", *args)
        for stale in _chunks(gone):
            git("update-index", "--force-remove", "--", *stale)
        return git("write-tree").strip()


def _chunks[T](items: list[T]) -> Iterator[list[T]]:
    for start in range(0, len(items), CHUNK):
        yield items[start : start + CHUNK]


def _split_present(
    top: Path, names: list[str], scratch: Path
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Files to put in the index as (name, mode, file to hash), and names that no longer exist.

    A symlink is hashed through a copy of its target text; directories (submodules, nested
    repositories) keep whatever the index already says.
    """
    present: list[tuple[str, str, str]] = []
    gone: list[str] = []
    for number, name in enumerate(names):
        path = top / name
        if path.is_symlink():
            link = scratch / f"link-{number}"
            link.write_bytes(os.fsencode(os.readlink(path)))
            present.append((name, "120000", str(link)))
        elif path.is_file():
            executable = os.access(path, os.X_OK)
            present.append((name, "100755" if executable else "100644", str(path)))
        elif not path.exists():
            gone.append(name)
    return present, gone


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
    previous = ""
    for line in diff.splitlines():
        header = _NEW_PATH.match(line) if previous.startswith("--- ") else None
        previous = line
        if header:
            path = (header.group(1) or "").rstrip("\t") or None  # git ends a spaced path with a tab
            continue
        hunk = _HUNK.match(line)
        if hunk and path is not None:
            start, count = int(hunk.group(1)), int(hunk.group(2) or 1)
            if count:
                found.setdefault(path, set()).update(range(start, start + count))
    return {name: frozenset(lines) for name, lines in found.items()}
