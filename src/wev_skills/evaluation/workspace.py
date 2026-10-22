"""A throwaway git worktree at a case's base commit, and the check that judges it."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import NotFound, StateConflict
from wev_skills.core.ports import Runner
from wev_skills.evaluation.cases import CASES_DIR, GIT_TIMEOUT_SECONDS, Case


def _git(runner: Runner, root: Path, *args: str) -> RawCommandResult:
    return runner.run(("git", *args), str(root), GIT_TIMEOUT_SECONDS, None)


@contextmanager
def case_workspace(runner: Runner, root: Path, case: Case, scratch: Path) -> Iterator[Path]:
    """Check out ``case.base_commit`` detached under ``scratch``; always remove it on exit."""
    found = _git(runner, root, "cat-file", "-e", f"{case.base_commit}^{{commit}}")
    if found.exit_code != 0:
        message = i18n.t("evaluation.workspace.base_missing", id=case.id, commit=case.base_commit)
        raise NotFound("case_base_missing", message, {"id": case.id})
    path = scratch / f"{case.id}-{uuid.uuid4().hex[:8]}"
    scratch.mkdir(parents=True, exist_ok=True)
    added = _git(runner, root, "worktree", "add", "--detach", str(path), case.base_commit)
    if added.exit_code != 0:
        message = i18n.t("evaluation.workspace.add_failed", id=case.id, error=added.stderr.strip())
        raise StateConflict("case_workspace_failed", message, {"id": case.id})
    try:
        yield path
    finally:
        _git(runner, root, "worktree", "remove", "--force", str(path))
        shutil.rmtree(path, ignore_errors=True)  # remove can fail on a dead worktree


def run_check(
    runner: Runner, case: Case, root: Path, workspace: Path, timeout: float
) -> RawCommandResult:
    """Copy the case's stored files into ``workspace`` and run its check there."""
    store = root / CASES_DIR / case.id
    for name in case.files:
        target = workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(store / name, target)
    return runner.run(case.check, str(workspace), timeout, None)


def passed(result: RawCommandResult) -> bool:
    return result.exit_code == 0 and not result.timed_out
