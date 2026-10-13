"""Where ``wev agent create`` and ``wev agent export`` may write.

Both commands take a path from the command line and write a file a person, or an agent
acting for one, did not review. They therefore write only inside the repository root, never
into the state directory, ``.git``, ``.claude`` or a protected path, never over a file whose
name differs from the target only by case, and never over a file that is not their own kind.

One exception, for ``agent export`` only: ``<root>/.claude/agents``, where Claude Code looks
for a project's subagents. Nothing else under ``.claude`` opens up (settings, hooks, commands,
skills), neither directory may be a symlink, and only ``<id>.md`` files go there.

The checks are made at call time: a path swapped between the check and the write is not
covered (time-of-check/time-of-use).
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.spec import validate_data
from wev_skills.config import CONFIG_FILE_NAME
from wev_skills.core.errors import PermissionDenied
from wev_skills.security.paths import is_protected

FORBIDDEN_DIRS = frozenset({".git", ".claude"})
"""Never written into, at any depth: git internals and Claude Code settings, hooks, agents."""
SPEC_SUFFIX = ".json"
RESERVED_NAMES = frozenset({CONFIG_FILE_NAME.casefold()})
CLAUDE_DIR = ".claude"
AGENTS_DIR = "agents"
AGENT_FILE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*\.md")
"""The only names ``agent export`` writes in ``.claude/agents``: an agent id plus ``.md``."""


@dataclass(frozen=True)
class OutputScope:
    """The repository root and what inside it stays off limits."""

    root: Path
    state_dir: Path
    protected_paths: tuple[str, ...] = ()


def _fold(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _parts_below(path: Path, base: Path) -> tuple[str, ...] | None:
    """The folded components of ``path`` under ``base``; ``None`` when it is not inside.

    Compared case-insensitively: on a case-insensitive filesystem ``.WEV`` is ``.wev``.
    """
    parts, prefix = tuple(map(_fold, path.parts)), tuple(map(_fold, base.parts))
    return parts[len(prefix) :] if parts[: len(prefix)] == prefix else None


def _refusal(
    lexical: Path, resolved: Path, scope: OutputScope, allow_claude_dir: bool = False
) -> str | None:
    """Why ``resolved`` (spelled ``lexical``) is off limits, or ``None`` when it is not.

    ``allow_claude_dir`` lifts only the ``.claude`` part of the forbidden-directory rule.
    """
    root = scope.root.resolve()
    if resolved != root and root not in resolved.parents:
        return "outside"
    if _parts_below(resolved, scope.state_dir.resolve()) is not None:
        return "state"
    spellings = (_parts_below(resolved, root), _parts_below(lexical, root))
    forbidden = FORBIDDEN_DIRS - {CLAUDE_DIR} if allow_claude_dir else FORBIDDEN_DIRS
    if any(forbidden.intersection(parts or ()) for parts in spellings):
        return "forbidden"
    if is_protected(lexical, root, scope.protected_paths):
        return "protected"
    return None


def confine(target: Path, scope: OutputScope) -> Path:
    """``target`` with symlinks resolved, or ``PermissionDenied`` when it is off limits.

    Off limits: outside ``scope.root``, inside the state directory, inside ``.git`` or
    ``.claude`` at any depth, or protected by ``scope.protected_paths``. Both the path as
    written and the path its symlinks lead to are checked.
    """
    lexical = Path(os.path.abspath(target))
    try:
        resolved = lexical.resolve()
        reason = _refusal(lexical, resolved, scope)
    except OSError, ValueError, RuntimeError:
        resolved, reason = lexical, "outside"
    if reason is None:
        return resolved
    raise _deny(reason, target, scope)


def project_agents_dir(scope: OutputScope) -> Path:
    """``<root>/.claude/agents``: the one place under ``.claude`` that ``agent export`` may use."""
    return scope.root.resolve() / CLAUDE_DIR / AGENTS_DIR


def _names_agents_dir(path: Path, scope: OutputScope) -> bool:
    """True when ``path`` is spelled exactly ``.claude/agents`` (same case) under the root."""
    expected = project_agents_dir(scope)
    return path.parts[-2:] == expected.parts[-2:] and path.parent.parent.resolve() == (
        expected.parent.parent
    )


def _deny(reason: str, path: Path, scope: OutputScope) -> PermissionDenied:
    message = i18n.t(f"agents.error.output_{reason}", path=str(path), root=str(scope.root))
    details = {"path": str(path), "root": str(scope.root), "reason": reason}
    return PermissionDenied("output_refused", message, details)


def _check_agents_dir(scope: OutputScope) -> Path:
    """The project agents directory, or ``PermissionDenied`` when it cannot be used safely.

    Neither ``.claude`` nor ``agents`` may be a symlink or anything but a directory, and no
    sibling may differ from them only by case. A directory that does not exist is fine: the
    exporter creates it.
    """
    target = project_agents_dir(scope)
    reason = _refusal(target, target, scope, allow_claude_dir=True)
    if reason is not None:
        raise _deny(reason, target, scope)
    for part in (target.parent, target):
        if os.path.islink(part):
            raise _deny("symlink", part, scope)
        if os.path.lexists(part) and not part.is_dir():
            raise _deny("notdir", part, scope)
        refuse_case_collision(part)
    return target


def confine_export_dir(target: Path, scope: OutputScope) -> Path:
    """Where ``agent export`` writes: ``confine``, plus exactly ``<root>/.claude/agents``."""
    if _names_agents_dir(Path(os.path.abspath(target)), scope):
        return _check_agents_dir(scope)
    return confine(target, scope)


def confine_export_file(path: Path, scope: OutputScope) -> Path:
    """One exported file: ``confine``, plus ``<id>.md`` directly in ``.claude/agents``."""
    lexical = Path(os.path.abspath(path))
    if _names_agents_dir(lexical.parent, scope) and AGENT_FILE.fullmatch(lexical.name):
        _check_agents_dir(scope)
        return lexical
    return confine(path, scope)


def case_collision(path: Path) -> str | None:
    """The existing entry next to ``path`` whose name differs from it only by case, if any.

    Writing ``claude.md`` beside ``CLAUDE.md`` replaces that file on a case-insensitive
    filesystem and plants a look-alike on a case-sensitive one.
    """
    try:
        names = os.listdir(path.parent)
    except FileNotFoundError:
        return None
    wanted = _fold(path.name)
    return next((n for n in sorted(names) if n != path.name and _fold(n) == wanted), None)


def refuse_case_collision(path: Path) -> None:
    try:
        existing = case_collision(path)
    except OSError as exc:
        message = i18n.t("agents.error.output_unreadable", path=str(path.parent))
        raise PermissionDenied("output_refused", message, {"path": str(path)}) from exc
    if existing is None:
        return
    message = i18n.t("agents.error.case_collision", path=str(path), existing=existing)
    raise PermissionDenied("case_collision", message, {"path": str(path), "existing": existing})


def refuse_non_spec_name(path: Path) -> None:
    """``wev agent create`` writes spec files only: the name must end in ``.json`` and must
    not be the engine's configuration file name, in any directory and any letter case (a
    spec written there would be read as the configuration of the next command)."""
    if path.name.casefold() in RESERVED_NAMES:
        message = i18n.t("agents.error.reserved_name", path=str(path), name=path.name)
        raise PermissionDenied("reserved_name", message, {"path": str(path)})
    if path.suffix == SPEC_SUFFIX:
        return
    message = i18n.t("agents.error.not_json_file", path=str(path))
    raise PermissionDenied("not_json_file", message, {"path": str(path)})


def refuse_foreign_spec_file(path: Path) -> bool:
    """True when ``path`` exists and is an agent spec; False when nothing is there.

    Anything else that exists (another JSON document, a directory, an unreadable file) is
    not ours to replace, with or without ``--force``.
    """
    if not os.path.lexists(path):
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        is_spec = isinstance(data, dict) and not validate_data(data)
    except OSError, ValueError, RecursionError:
        is_spec = False
    if is_spec:
        return True
    message = i18n.t("agents.error.not_agent_spec", path=str(path))
    raise PermissionDenied("not_agent_spec", message, {"path": str(path)})
