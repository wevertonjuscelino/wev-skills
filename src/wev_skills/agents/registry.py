"""Immutable agent registry loaded from directories of ``*.json`` spec files."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from wev_skills import i18n
from wev_skills.agents.spec import AgentSpec, validate_data
from wev_skills.config import read_json_object
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError

SPEC_MARKERS = ("schema_version", "id")
"""A JSON object carrying either key claims to be a spec and must then be a valid one."""
BUILTIN_SUBDIRS = ("agent-specs/templates", "agent-specs/examples")
"""The catalog shipped next to this checkout; mirrors ``core.wiring.CATALOG_SUBDIRS``."""
_CHECKOUT_ROOT = Path(__file__).resolve().parents[3]


def builtin_directories() -> tuple[Path, ...]:
    """The resolved directories of the built-in catalog (they may not exist when installed)."""
    return tuple((_CHECKOUT_ROOT / sub).resolve() for sub in BUILTIN_SUBDIRS)


def is_builtin_source(path: Path | None) -> bool:
    """True when the spec file ``path`` sits directly in a built-in catalog directory.

    Decided by the real location of the directory it was found in, so neither a relative
    spelling nor a symlinked directory changes the answer.
    """
    return path is not None and path.parent.resolve() in builtin_directories()


@dataclass(frozen=True)
class SkippedFile:
    """A ``*.json`` file in a spec directory that is not an agent spec, and why it was skipped."""

    path: Path
    reason: str


@dataclass(frozen=True)
class DirectoryLoad:
    specs: Mapping[str, AgentSpec]
    sources: Mapping[str, Path]
    skipped: tuple[SkippedFile, ...] = ()


class AgentRegistry:
    """Id to spec lookup. Every mutation-like method returns a new registry."""

    def __init__(
        self,
        specs: Iterable[AgentSpec] = (),
        sources: Mapping[str, Path] | None = None,
        skipped: Iterable[SkippedFile] = (),
    ) -> None:
        self._specs: Mapping[str, AgentSpec] = MappingProxyType({s.id: s for s in specs})
        known = {k: v for k, v in (sources or {}).items() if k in self._specs}
        self._sources: Mapping[str, Path] = MappingProxyType(known)
        self.skipped: tuple[SkippedFile, ...] = tuple(skipped)

    def register(self, spec: AgentSpec) -> AgentRegistry:
        """A new registry with ``spec`` added, replacing any spec with the same id.

        A spec registered this way has no source file, even when it replaces one that had.
        """
        sources = {k: v for k, v in self._sources.items() if k != spec.id}
        return AgentRegistry([*self._specs.values(), spec], sources, self.skipped)

    def discover(
        self, directories: Iterable[str | Path], allow_override: bool = False
    ) -> AgentRegistry:
        """A new registry plus every spec found in ``directories``; later ones override earlier.

        An id of the built-in catalog belongs to the catalog: a spec from any other
        directory that reuses it is rejected, in either order, unless ``allow_override``.
        JSON files that do not claim to be a spec are skipped and listed in ``skipped``.
        """
        merged, sources, skipped = dict(self._specs), dict(self._sources), list(self.skipped)
        for directory in directories:
            loaded = scan_directory(Path(directory))
            if not allow_override:
                _refuse_builtin_shadow(sources, loaded.sources)
            merged.update(loaded.specs)
            sources.update(loaded.sources)
            skipped.extend(loaded.skipped)
        return AgentRegistry(merged.values(), sources, skipped)

    def source(self, agent_id: str) -> Path | None:
        """The file ``agent_id`` was loaded from, or ``None`` for an in-memory spec."""
        return self._sources.get(agent_id)

    def get(self, agent_id: str) -> AgentSpec:
        try:
            return self._specs[agent_id]
        except KeyError as exc:
            raise NotFound(
                "agent_not_found",
                i18n.t("agents.error.not_found", id=agent_id),
                {"id": agent_id},
            ) from exc

    def list(self) -> list[AgentSpec]:
        return [self._specs[key] for key in sorted(self._specs)]

    def __contains__(self, agent_id: object) -> bool:
        return agent_id in self._specs

    def __len__(self) -> int:
        return len(self._specs)


def _refuse_builtin_shadow(known: Mapping[str, Path], incoming: Mapping[str, Path]) -> None:
    """Raise when an id is defined both by the built-in catalog and by another directory."""
    for agent_id, path in incoming.items():
        previous = known.get(agent_id)
        if previous is None or is_builtin_source(previous) == is_builtin_source(path):
            continue
        builtin, other = (previous, path) if is_builtin_source(previous) else (path, previous)
        raise ValidationError(
            "builtin_agent_shadowed",
            i18n.t("agents.error.builtin_shadow", id=agent_id, file=str(other)),
            {"id": agent_id, "file": str(other), "builtin": str(builtin)},
        )


def load_directory(directory: Path) -> dict[str, AgentSpec]:
    """The specs of ``scan_directory`` by id."""
    return dict(scan_directory(directory).specs)


def _not_a_spec(path: Path) -> str | None:
    """Why ``path`` makes no claim to be a spec (``None`` when it does, or is not JSON at all).

    Unparseable files are left to ``load_file``, which fails: a broken spec must not vanish.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return i18n.t("agents.warning.not_object", file=str(path))
    if not any(marker in data for marker in SPEC_MARKERS):
        return i18n.t("agents.warning.not_spec", file=str(path))
    return None


def scan_directory(directory: Path) -> DirectoryLoad:
    """Load and validate every spec ``*.json`` directly inside ``directory`` (not recursive)."""
    if not directory.is_dir():
        raise NotFound(
            "directory_not_found",
            i18n.t("agents.error.dir_not_found", directory=str(directory)),
            {"directory": str(directory)},
        )
    root = directory.resolve()
    found: dict[str, tuple[AgentSpec, Path]] = {}
    skipped: list[SkippedFile] = []
    for path in sorted(directory.glob("*.json")):
        _refuse_escaping_link(path, root)
        reason = _not_a_spec(path)
        if reason is not None:
            skipped.append(SkippedFile(path, reason))
            continue
        spec = load_file(path)
        if spec.id in found:
            raise ValidationError(
                "duplicate_agent_id",
                i18n.t(
                    "agents.error.duplicate_id",
                    id=spec.id,
                    first=found[spec.id][1].name,
                    second=path.name,
                    directory=str(directory),
                ),
                {"id": spec.id, "files": [str(found[spec.id][1]), str(path)]},
            )
        found[spec.id] = (spec, path)
    specs = {agent_id: pair[0] for agent_id, pair in found.items()}
    sources = {agent_id: pair[1] for agent_id, pair in found.items()}
    return DirectoryLoad(specs, sources, tuple(skipped))


def load_file(path: Path) -> AgentSpec:
    """Parse and validate one spec file; errors name the file and the JSON-pointer paths."""
    data = read_json_object(str(path))
    errors = validate_data(data)
    if errors:
        raise ValidationError(
            "invalid_agent_file",
            i18n.t("agents.error.invalid_file", file=str(path), errors="; ".join(errors)),
            {"file": str(path), "errors": errors},
        )
    return AgentSpec.from_dict(data)


def _refuse_escaping_link(path: Path, root: Path) -> None:
    if not path.is_symlink():
        return
    target = path.resolve()
    if not target.is_relative_to(root):
        raise PermissionDenied(
            "symlink_escape",
            i18n.t("agents.error.symlink_escape", file=str(path), target=str(target)),
            {"file": str(path), "target": str(target)},
        )
