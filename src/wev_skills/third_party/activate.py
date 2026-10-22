"""Link the active agent-skills into the skill directories of the harnesses.

Each link ``<root>/<name>`` points at ``<home>/agent-skills/current/skills/<name>``, so an
update needs no relinking. Every link made is recorded in ``<home>/manifest.json``, and only
links listed there are ever replaced or removed. The manifest is data: a path it lists must be
a link name directly under one of the roots, and a listed link that no longer points where
wev made it point is the person's: it is refused and kept, never replaced or removed.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.harness_install import Manifest, read_manifest, write_manifest
from wev_skills.core.errors import StateConflict, ValidationError

TARGET = "agent-skills"
NAME_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


def default_roots() -> list[Path]:
    """Claude Code, and the root Codex, OpenCode and Gemini share."""
    return [Path.home() / ".claude" / "skills", Path.home() / ".agents" / "skills"]


def _confined(roots: Sequence[Path]) -> Callable[[object], bool]:
    def check(name: object) -> bool:
        if not isinstance(name, str) or not os.path.isabs(name):
            return False
        link = Path(os.path.normpath(name))
        return str(link) == name and link.parent in roots and bool(NAME_RE.fullmatch(link.name))

    return check


def _read(home: Path, roots: Sequence[Path]) -> Manifest | None:
    return read_manifest(home, TARGET, _confined(roots), ())


def _skill_names(skills: Path) -> list[str]:
    if not skills.is_dir():
        raise StateConflict("not_installed", i18n.t("skills.error.not_installed", name=TARGET))
    names = sorted(e.name for e in skills.iterdir() if e.is_dir() and (e / "SKILL.md").is_file())
    for name in names:
        if not NAME_RE.fullmatch(name):
            raise ValidationError(
                "bad_skill_name", i18n.t("skills.error.bad_skill_name", name=name[:64])
            )
    return names


def _wanted(skills: Path, names: list[str], roots: Sequence[Path]) -> dict[Path, Path]:
    return {root / name: skills / name for root in roots if root.is_dir() for name in names}


def _ours(link: Path, skills: Path) -> bool:
    """``link`` is still the symlink wev made: to ``skills/<its name>``."""
    return link.is_symlink() and Path(os.readlink(link)) == skills / link.name


def _refuse_foreign(wanted: dict[Path, Path], owned: set[str], skills: Path) -> None:
    for link in wanted:
        if os.path.lexists(link) and (str(link) not in owned or not _ours(link, skills)):
            raise StateConflict("foreign_entry", i18n.t("skills.error.foreign", path=str(link)))


def activate(home: Path, roots: Sequence[Path]) -> Manifest:
    """Make the links; a re-run refreshes them and drops those of skills that are gone."""
    skills = home / TARGET / "current" / "skills"
    wanted = _wanted(skills, _skill_names(skills), roots)
    previous = _read(home, roots)
    owned = set(previous.files) if previous else set()
    _refuse_foreign(wanted, owned, skills)
    for stale in owned - {str(link) for link in wanted}:
        if _ours(Path(stale), skills):
            Path(stale).unlink()
    for link, target in wanted.items():
        if not os.path.lexists(link):
            os.symlink(target, link)
    manifest = Manifest(TARGET, tuple(sorted(str(link) for link in wanted)), ())
    write_manifest(home, manifest)
    return manifest


def deactivate(home: Path, roots: Sequence[Path]) -> tuple[str, ...]:
    """Remove the links of the manifest, and only those that still point where wev made them."""
    manifest = _read(home, roots)
    if manifest is None:
        return ()
    skills = home / TARGET / "current" / "skills"
    removed = []
    for name in manifest.files:
        if _ours(Path(name), skills):
            Path(name).unlink()
            removed.append(name)
    (home / "manifest.json").unlink(missing_ok=True)
    return tuple(removed)
