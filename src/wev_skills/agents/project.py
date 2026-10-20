"""Project specialist lifecycle, confined to the configured project directory."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code.subagent import export_all
from wev_skills.agents import learning
from wev_skills.agents.experience import ACTIVE, PROPOSED, RETIRED, STALE, Lesson
from wev_skills.agents.output import OutputScope, confine, confine_export_dir, confine_export_file
from wev_skills.agents.registry import load_file
from wev_skills.agents.spec import AgentSpec, LocalText
from wev_skills.config import Config
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError
from wev_skills.core.fsutil import atomic_write_text, locked
from wev_skills.core.wiring import build_agents, state_dir
from wev_skills.state.store import StateStore, list_runs, run_dir


def bounds(root: Path, config: Config) -> OutputScope:
    return OutputScope(root, state_dir(config, root), config.permissions.protected_paths)


def directory(root: Path, config: Config) -> Path:
    path = root.resolve() / config.agents.project_dir
    _refuse_links(path, root.resolve())
    return confine(path, bounds(root, config))


def list_specs(root: Path, config: Config) -> list[AgentSpec]:
    base = directory(root, config)
    found = []
    for path in sorted(base.glob("*.json")):
        _refuse_links(path, root.resolve())
        spec = load_file(confine(path, bounds(root, config)))
        if spec.id != path.stem:
            raise ValidationError(
                "specialist_id_mismatch", i18n.t("agents.specialists.id_mismatch")
            )
        found.append(spec)
    return found


def _target(root: Path, config: Config, agent_id: str) -> Path:
    # Validate the id before it becomes a path component.
    AgentSpec.from_dict(
        {"schema_version": 1, "id": agent_id, "name": agent_id, "description": agent_id}
    )
    path = directory(root, config) / f"{agent_id}.json"
    _refuse_links(path, root.resolve())
    return confine(path, bounds(root, config))


def _write(root: Path, config: Config, spec: AgentSpec) -> Path:
    path = _target(root, config, spec.id)
    AgentSpec.from_dict(spec.to_dict())
    atomic_write_text(path, json.dumps(spec.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return path


def create(
    root: Path, config: Config, agent_id: str, template: str, specialties: tuple[str, ...]
) -> AgentSpec:
    """Clone a resolved role without adding authority; never replace an existing specialist."""
    target = _target(root, config, agent_id)
    with locked(state_dir(config, root) / "specialists", config.limits.lock_timeout_seconds):
        catalog = build_agents(config, root)
        if target.exists() or agent_id in catalog.registry:
            raise ValidationError("specialist_exists", i18n.t("agents.specialists.exists"))
        if len(list_specs(root, config)) >= config.specialists.max_per_project:
            raise ValidationError("specialist_limit", i18n.t("agents.specialists.limit"))
        parent = catalog.resolved(template)
        name = LocalText(agent_id)
        spec = replace(
            parent,
            id=agent_id,
            name=name,
            specialties=specialties or parent.specialties,
            experience=(),
        )
        _write(root, config, spec)
    return spec


def _load(root: Path, config: Config, agent_id: str) -> AgentSpec:
    spec = load_file(_target(root, config, agent_id))
    if spec.id != agent_id:
        raise ValidationError("specialist_id_mismatch", i18n.t("agents.specialists.id_mismatch"))
    return spec


def learn(root: Path, config: Config, agent_id: str) -> AgentSpec:
    """Recalculate observations from stored runs and update only the experience field."""
    with locked(state_dir(config, root) / "specialists", config.limits.lock_timeout_seconds):
        spec = _load(root, config, agent_id)
        states = [
            StateStore(run_dir(state_dir(config, root), run_id)).load()
            for run_id in list_runs(state_dir(config, root))
        ]
        states = [
            state
            for state in states
            if state.repo is not None and Path(state.repo.root).resolve() == root.resolve()
        ]
        derived = learning.derive(states, agent_id, config.specialists.stale_after_runs)
        lessons = learning.reconcile(spec.experience, derived, config.specialists.max_lessons)
        updated = replace(spec, experience=lessons)
        _write(root, config, updated)
    return updated


def _find(spec: AgentSpec, lesson_id: str) -> Lesson:
    for lesson in spec.experience:
        if lesson.id == lesson_id:
            return lesson
    message = i18n.t("agents.specialists.lesson_not_found", lesson=lesson_id, specialist=spec.id)
    raise NotFound("lesson_not_found", message, {"lesson": lesson_id})


def find_lesson(root: Path, config: Config, agent_id: str, lesson_id: str) -> Lesson:
    return _find(_load(root, config, agent_id), lesson_id)


def _decide(
    root: Path,
    config: Config,
    ids: tuple[str, str],
    allowed: tuple[str, ...],
    decided: tuple[str, str],
) -> AgentSpec:
    """Set ``decided`` (status, operator) on one lesson, under the lock, when its current
    status is in ``allowed``."""
    agent_id, lesson_id = ids
    with locked(state_dir(config, root) / "specialists", config.limits.lock_timeout_seconds):
        spec = _load(root, config, agent_id)
        current = _find(spec, lesson_id)
        if current.status not in allowed:
            message = i18n.t(
                "agents.specialists.wrong_status", lesson=lesson_id, status=current.status
            )
            raise ValidationError("lesson_status", message, {"lesson": lesson_id})
        status, operator = decided
        changed = replace(current, status=status, accepted_by=operator)
        lessons = tuple(changed if item.id == lesson_id else item for item in spec.experience)
        updated = replace(spec, experience=lessons)
        _write(root, config, updated)
    return updated


def accept_lesson(
    root: Path, config: Config, agent_id: str, lesson_id: str, operator: str
) -> AgentSpec:
    """A proposed lesson becomes active, recorded as accepted by ``operator``."""
    return _decide(root, config, (agent_id, lesson_id), (PROPOSED,), (ACTIVE, operator))


def retire_lesson(
    root: Path, config: Config, agent_id: str, lesson_id: str, operator: str
) -> AgentSpec:
    """Any lesson not yet retired is retired, by ``operator``; relearning keeps it retired."""
    allowed = (ACTIVE, STALE, PROPOSED)
    return _decide(root, config, (agent_id, lesson_id), allowed, (RETIRED, operator))


def export(root: Path, config: Config, lang: str | None = None) -> list[Path]:
    """Export only project specialists into the host's project agent directory."""
    scope = bounds(root, config)
    target = confine_export_dir(root / ".claude" / "agents", scope)
    specs = list_specs(root, config)
    sources = {spec.id: f"{config.agents.project_dir}/{spec.id}.json" for spec in specs}
    return export_all(
        specs,
        target,
        i18n.resolve_language(lang),
        sources,
        check=lambda path: confine_export_file(path, scope),
        max_lessons=config.specialists.max_lessons_rendered,
    )


def summary(spec: AgentSpec) -> dict[str, Any]:
    return {
        "id": spec.id,
        "specialties": list(spec.specialties),
        "lessons": len(spec.experience),
        "experience": [item.to_dict() for item in spec.experience],
    }


def _refuse_links(path: Path, root: Path) -> None:
    if any(item.is_symlink() for item in (path, *path.parents) if item != root):
        raise PermissionDenied("specialist_symlink", i18n.t("agents.specialists.symlink"))
