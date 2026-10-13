"""Compare a recorded run with the real repository before resuming.

The record is a claim, the repository is the fact. Nothing here assumes that a task recorded
as RUNNING finished, or that files a task reported still exist: both are reported so the
orchestrator re-verifies them.
"""

from __future__ import annotations

import ast
import os
from collections.abc import Sequence
from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import TaskStatus
from wev_skills.core.ports import Runner
from wev_skills.state.model import RepoSnapshot, RunState

GIT_TIMEOUT_SECONDS = 15.0
_STATUS_PREFIX_LEN = 3
_RENAME_SEPARATOR = " -> "


@dataclass(frozen=True)
class DriftReport(Serializable):
    drifted: bool
    head_changed: bool = False
    branch_changed: bool = False
    new_dirty_files: tuple[str, ...] = ()
    missing_files: tuple[str, ...] = ()
    stale_running_tasks: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _git(runner: Runner, root: str, *args: str) -> str | None:
    """Output of one git command, or ``None`` when it failed, timed out, or git is missing."""
    result = runner.run(("git", *args), root, GIT_TIMEOUT_SECONDS, None)
    if result.timed_out or result.exit_code != 0:
        return None
    return result.stdout


def _unquote(path: str) -> str:
    """Undo git's C-style quoting of unusual paths; unquoted text is returned unchanged."""
    if len(path) < 2 or not (path.startswith('"') and path.endswith('"')):
        return path
    try:
        raw = ast.literal_eval("b" + path)
    except ValueError, SyntaxError:
        return path[1:-1]
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else path[1:-1]


def _under(path: str, exclude: Sequence[str]) -> bool:
    plain = os.path.normpath(path)
    prefixes = (os.path.normpath(item) for item in exclude if item)
    return any(plain == prefix or plain.startswith(prefix + os.sep) for prefix in prefixes)


def _dirty_files(porcelain: str, exclude: Sequence[str] = ()) -> tuple[str, ...]:
    files: set[str] = set()
    for line in porcelain.splitlines():
        if len(line) <= _STATUS_PREFIX_LEN:
            continue
        code, path = line[:2], line[_STATUS_PREFIX_LEN:]
        if ("R" in code or "C" in code) and _RENAME_SEPARATOR in path:
            path = path.split(_RENAME_SEPARATOR, 1)[1]
        files.add(_unquote(path))
    return tuple(sorted(name for name in files if not _under(name, exclude)))


def snapshot_repo(root: str, runner: Runner, exclude: Sequence[str] = ()) -> RepoSnapshot | None:
    """Real git state at ``root``; ``None`` outside a repository or when git is unavailable.

    A repository without commits has an empty ``head``; a detached HEAD has an empty ``branch``.
    ``exclude`` lists paths relative to the repository (the state directory) whose files are
    never reported as dirty: the engine's own records are not drift.
    """
    top = _git(runner, root, "rev-parse", "--show-toplevel")
    if top is None or not top.strip():
        return None
    head = _git(runner, root, "rev-parse", "HEAD")
    branch = _git(runner, root, "branch", "--show-current")
    status = _git(runner, root, "status", "--porcelain")
    return RepoSnapshot(
        root=top.strip(),
        branch=(branch or "").strip(),
        head=(head or "").strip(),
        dirty_files=_dirty_files(status or "", exclude),
    )


def _claimed_files(state: RunState) -> tuple[str, ...]:
    claimed = {
        path
        for record in state.tasks.values()
        if record.result is not None
        for path in record.result.changed_files
    }
    return tuple(sorted(claimed))


def _split_claims(root: str, claimed: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Return (missing, outside): files gone from ``root`` and paths that leave ``root``."""
    missing: list[str] = []
    outside: list[str] = []
    for path in claimed:
        normalized = os.path.normpath(path)
        if os.path.isabs(path) or normalized == ".." or normalized.startswith(".." + os.sep):
            outside.append(path)
        elif not os.path.lexists(os.path.join(root, normalized)):
            missing.append(path)
    return missing, outside


def check_drift(
    state: RunState, runner: Runner, root: str | None = None, exclude: Sequence[str] = ()
) -> DriftReport:
    """Report every difference between the recorded run and the repository as it is now.

    ``root`` defaults to the recorded repository root. ``missing_files`` lists files that task
    results claim were changed and that no longer exist (a task that deleted a file on purpose
    shows up here too: the report asks for re-verification, it does not judge).
    """
    recorded = state.repo
    base = root if root is not None else (recorded.root if recorded else None)
    stale = tuple(
        sorted(tid for tid, record in state.tasks.items() if record.status == TaskStatus.RUNNING)
    )
    notes: list[str] = []
    if stale:
        notes.append(i18n.t("state.drift.stale_running", tasks=", ".join(stale)))
    if base is None:
        notes.append(i18n.t("state.drift.no_root"))
        return DriftReport(bool(stale), stale_running_tasks=stale, notes=tuple(notes))
    current = snapshot_repo(base, runner, exclude)
    head_changed = branch_changed = unavailable = False
    new_dirty: tuple[str, ...] = ()
    if recorded is None:
        notes.append(i18n.t("state.drift.no_snapshot"))
    elif current is None:
        unavailable = True
        notes.append(i18n.t("state.drift.repo_unavailable", root=base))
    else:
        head_changed = current.head != recorded.head
        branch_changed = current.branch != recorded.branch
        new_dirty = tuple(f for f in current.dirty_files if f not in recorded.dirty_files)
    missing, outside = _split_claims(current.root if current else base, _claimed_files(state))
    if head_changed and recorded and current:
        notes.append(i18n.t("state.drift.head_changed", old=recorded.head, new=current.head))
    if branch_changed and recorded and current:
        notes.append(i18n.t("state.drift.branch_changed", old=recorded.branch, new=current.branch))
    if new_dirty:
        notes.append(i18n.t("state.drift.new_dirty", count=len(new_dirty)))
    if missing:
        notes.append(i18n.t("state.drift.missing_files", count=len(missing)))
    if outside:
        notes.append(i18n.t("state.drift.outside_root", files=", ".join(outside)))
    drifted = bool(head_changed or branch_changed or unavailable or new_dirty or missing or stale)
    return DriftReport(
        drifted, head_changed, branch_changed, new_dirty, tuple(missing), stale, tuple(notes)
    )
