"""What a run changed between its base and now, read from git, for the finish gate."""

from __future__ import annotations

from pathlib import Path

from wev_skills.core.ports import Runner
from wev_skills.evaluation.workspace import run_git
from wev_skills.review.trees import _checked


def changed_paths(runner: Runner, root: Path, base: str, now: str) -> frozenset[str]:
    """Every path that differs between trees ``base`` and ``now``, deletions and mode
    changes included (a line diff records neither). NUL-separated, so names are exact."""
    argv = ("diff", "--name-only", "--no-renames", "--no-ext-diff", "--no-textconv", "-z")
    out = _checked(run_git(runner, root, *argv, base, now), "diff --name-only")
    return frozenset(name for name in out.split("\0") if name)


def file_at(runner: Runner, root: Path, rev: str, path: str) -> str | None:
    """The text of ``path`` in tree ``rev``, or None when it does not exist there."""
    result = run_git(runner, root, "show", f"{rev}:{path}")
    return None if result.timed_out or result.exit_code != 0 else result.stdout
