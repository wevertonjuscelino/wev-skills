"""A throwaway git worktree at a case's base commit, and the check that judges it."""

from __future__ import annotations

import os
import shutil
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from wev_skills import i18n
from wev_skills.core.contracts import Mode, RawCommandResult, RiskLevel
from wev_skills.core.errors import NotFound, StateConflict, ValidationError
from wev_skills.core.ports import Runner
from wev_skills.evaluation.cases import CASES_DIR, GIT_TIMEOUT_SECONDS, Case
from wev_skills.security.paths import resolve_within
from wev_skills.security.permissions import PermissionPolicy

CHECK_ENV_KEYS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
EXIT_NOT_STARTED = 127  # SubprocessRunner's code for a command that could not start


# An agent ran in the workspace and may have planted git configuration: no repository config
# command, hook or system/global file may take part in these calls.
GIT_HARDENING = ("-c", "core.fsmonitor=", "-c", "core.hooksPath=/dev/null")
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}


def run_git(
    runner: Runner, root: Path, *args: str, env: Mapping[str, str] | None = None
) -> RawCommandResult:
    """One hardened git call; ``env`` is merged over the minimal environment."""
    base = {key: os.environ[key] for key in ("PATH", "HOME") if key in os.environ} | GIT_ENV
    merged = base | dict(env or {})
    argv = ("git", *GIT_HARDENING, *args)
    return runner.run(argv, str(root), GIT_TIMEOUT_SECONDS, merged)


SKIP_GIT_ATTR = "wev_skip_git"


def skip_git_cleanup(exc: BaseException) -> None:
    """Mark ``exc`` so ``case_workspace`` removes the directory without any git call."""
    setattr(exc, SKIP_GIT_ATTR, True)


class GitTampered(StateConflict):
    """The shared git directory changed while an agent ran; nothing may use git until reviewed."""

    wev_skip_git = True


@contextmanager
def case_workspace(
    runner: Runner, root: Path, case: Case, scratch: Path, commit: str | None = None
) -> Iterator[Path]:
    """Check out ``commit`` (default ``case.base_commit``) detached under ``scratch``;
    always remove it on exit."""
    commit = commit or case.base_commit
    found = run_git(runner, root, "cat-file", "-e", f"{commit}^{{commit}}")
    if found.exit_code != 0:
        message = i18n.t("evaluation.workspace.base_missing", id=case.id, commit=commit)
        raise NotFound("case_base_missing", message, {"id": case.id})
    path = scratch / f"{case.id}-{uuid.uuid4().hex[:8]}"
    scratch.mkdir(parents=True, exist_ok=True)
    added = run_git(runner, root, "worktree", "add", "--detach", str(path), commit)
    if added.exit_code != 0:
        message = i18n.t("evaluation.workspace.add_failed", id=case.id, error=added.stderr.strip())
        raise StateConflict("case_workspace_failed", message, {"id": case.id})
    tampered = False
    try:
        yield path
    except BaseException as exc:
        tampered = bool(getattr(exc, SKIP_GIT_ATTR, False))
        raise
    finally:
        if not tampered:  # once the agent ran, only a verified clean exit may call git
            run_git(runner, root, "worktree", "remove", "--force", str(path))
        shutil.rmtree(path, ignore_errors=True)  # remove can fail on a dead worktree


def _refuse_symlinks(workspace: Path, name: str, case: Case) -> Path:
    """The destination of ``name`` inside ``workspace``; no existing component may be a symlink."""
    probe = workspace
    for part in Path(name).parts:
        probe = probe / part
        if probe.is_symlink():
            message = i18n.t("evaluation.workspace.symlink", id=case.id, path=name)
            raise ValidationError("case_workspace_symlink", message, {"id": case.id})
    return resolve_within(workspace, name)


def run_check(
    runner: Runner,
    policy: PermissionPolicy,
    case: Case,
    root: Path,
    workspace: Path,
    timeout: float,
) -> RawCommandResult:
    """Gate the check, copy the case's stored files into ``workspace`` and run it there."""
    policy.enforce_command(case.check, str(workspace), Mode.EXECUTE, RiskLevel.LOW, consume=False)
    store = root / CASES_DIR / case.id
    for name in case.files:
        target = _refuse_symlinks(workspace, name, case)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(store / name, target)
    env = {key: os.environ[key] for key in CHECK_ENV_KEYS if key in os.environ}
    return runner.run(case.check, str(workspace), timeout, env)


def not_started(result: RawCommandResult) -> bool:
    """The check never ran to a verdict: it timed out or could not be started."""
    return result.timed_out or result.exit_code == EXIT_NOT_STARTED


def passed(result: RawCommandResult) -> bool:
    return result.exit_code == 0 and not result.timed_out
