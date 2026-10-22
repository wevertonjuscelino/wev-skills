"""Scored cases: real situations stored under ``evals/cases`` and pinned by a digest."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n, schema
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import PermissionDenied, StateConflict, ValidationError
from wev_skills.core.ports import Runner
from wev_skills.security.paths import resolve_within

CASES_DIR = Path("evals") / "cases"
GIT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class Case(Serializable):
    id: str
    title: str
    source: str
    ref: str
    agents: tuple[str, ...]
    base_commit: str
    objective: str
    check: tuple[str, ...]
    files: tuple[str, ...]


def _invalid(path: Path, detail: str) -> ValidationError:
    message = i18n.t("evaluation.cases.invalid", file=path.name, detail=detail)
    return ValidationError("invalid_case", message, {"file": str(path)})


def _read(root: Path, path: Path) -> Case:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _invalid(path, str(exc)) from exc
    errors = schema.validate(data, schema.load("case"))
    if errors:
        raise _invalid(path, "; ".join(errors))
    case = Case.from_dict(data)
    if path.stem != case.id:
        raise _invalid(path, i18n.t("evaluation.cases.id_mismatch", id=case.id))
    store = root / CASES_DIR / case.id
    for name in case.files:
        try:
            found = resolve_within(store, name)
        except PermissionDenied as exc:
            raise _invalid(path, i18n.t("evaluation.cases.path_escape", path=name)) from exc
        if not found.is_file():
            raise _invalid(path, i18n.t("evaluation.cases.file_missing", path=name))
    return case


def load_cases(root: Path) -> tuple[Case, ...]:
    """Every ``evals/cases/*.json`` as a Case, sorted by id."""
    folder = root / CASES_DIR
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    return tuple(sorted((_read(root, p) for p in paths), key=lambda c: c.id))


def cases_for(cases: Sequence[Case], agent_id: str) -> tuple[Case, ...]:
    """Cases that apply to ``agent_id``; a case with no ``agents`` applies to every specialist."""
    return tuple(c for c in cases if not c.agents or agent_id in c.agents)


def case_set_digest(root: Path) -> str:
    """sha256 over every regular file under the cases folder, in POSIX path order."""
    base = root / CASES_DIR
    files = (
        sorted((p.relative_to(base).as_posix(), p) for p in base.rglob("*") if p.is_file())
        if base.is_dir()
        else []
    )
    digest = hashlib.sha256()
    for name, path in files:
        digest.update(name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def ensure_committed(runner: Runner, root: Path) -> None:
    """Refuse a case set with uncommitted or untracked changes: the pin must name a commit."""
    argv = ("git", "status", "--porcelain", "--untracked-files=all", "--", CASES_DIR.as_posix())
    result = runner.run(argv, str(root), GIT_TIMEOUT_SECONDS, None)
    if result.exit_code != 0 or result.timed_out:
        raise StateConflict(
            "cases_status_failed",
            i18n.t("evaluation.cases.status_failed"),
            {"exit_code": result.exit_code, "timed_out": result.timed_out},
        )
    out = result.stdout.strip()
    if out:
        raise StateConflict(
            "cases_uncommitted", i18n.t("evaluation.cases.uncommitted"), {"changes": out}
        )
