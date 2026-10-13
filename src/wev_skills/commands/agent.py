"""``wev agent list|show|validate|create|export``."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code.subagent import export_all
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.output import (
    OutputScope,
    confine,
    confine_export_dir,
    confine_export_file,
    refuse_case_collision,
    refuse_foreign_spec_file,
    refuse_non_spec_name,
)
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import AgentSpec, validate_data
from wev_skills.agents.tool_profile import apply_profile, resolve_profile, tier_of
from wev_skills.commands import Handler, Subparsers
from wev_skills.commands._scope import Scope, resolve_scope
from wev_skills.config import TOOL_PROFILES, ModelsConfig, read_json_object
from wev_skills.core.errors import ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.core.wiring import CATALOG_SUBDIRS, REPO_ROOT, catalog_directories


def _directories(args: argparse.Namespace, scope: Scope) -> list[Path]:
    """The catalog, the configured directories (relative to the root), then ``--dir``."""
    configured = [scope.root / d for d in scope.config.agents.directories]
    extra = [Path(d) for d in (getattr(args, "dir", None) or [])]
    return [*catalog_directories(), *(d for d in configured if d.is_dir()), *extra]


def _factory(args: argparse.Namespace, scope: Scope) -> AgentFactory:
    """Built-in agent ids stay the catalog's unless ``agents.allow_override`` is set."""
    allow_override = scope.config.agents.allow_override
    return AgentFactory(AgentRegistry().discover(_directories(args, scope), allow_override))


def _output_scope(scope: Scope) -> OutputScope:
    protected = tuple(scope.config.permissions.protected_paths)
    return OutputScope(scope.root, scope.state_dir, protected)


def _summary(spec: AgentSpec, lang: str) -> dict[str, Any]:
    view = spec.localized(lang)
    return {
        "id": spec.id,
        "name": view.name,
        "description": view.description,
        "specialties": list(spec.specialties),
        "extends": spec.extends,
        "model": spec.model,
    }


def _warnings(registry: AgentRegistry) -> list[str]:
    """One line per JSON file that was skipped because it is not an agent spec."""
    return [item.reason for item in registry.skipped]


def _list(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    lang = i18n.resolve_language()
    registry = _factory(args, scope).registry
    return {
        "agents": [_summary(s, lang) for s in registry.list()],
        "warnings": _warnings(registry),
        "config_source": scope.source,
    }


def _show(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    factory = _factory(args, scope)
    spec = factory.registry.get(args.id)
    shown = factory.resolve(spec) if args.resolved else spec
    return {**shown.to_dict(), "config_source": scope.source}


def _validate(args: argparse.Namespace) -> dict[str, Any]:
    data = read_json_object(args.path)
    errors = validate_data(data)
    if errors:
        raise ValidationError(
            "invalid_agent_file",
            i18n.t("agents.error.invalid_file", file=args.path, errors="; ".join(errors)),
            {"file": args.path, "errors": errors},
        )
    scope = resolve_scope(args.config)
    _factory(args, scope).resolve(AgentSpec.from_dict(data))
    return {"valid": True, "path": args.path, "id": data["id"], "config_source": scope.source}


def parse_overrides(pairs: Sequence[str]) -> dict[str, Any]:
    """``key=value`` pairs to a nested dict. ``a.b=1`` nests; values parse as JSON, else text."""
    out: dict[str, Any] = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValidationError("bad_set", i18n.t("agents.error.bad_set", pair=pair))
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        node = out
        *parents, leaf = key.split(".")
        for part in parents:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValidationError("bad_set", i18n.t("agents.error.bad_set", pair=pair))
        node[leaf] = value
    return out


def _create(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    factory = _factory(args, scope)
    overrides = {**parse_overrides(args.set or []), "id": args.id}
    data = factory.child_data(args.template, overrides)
    spec = factory.create(args.template, overrides)
    written = None
    if args.out:
        out = _spec_target(Path(args.out), _output_scope(scope), args.force)
        atomic_write_text(out, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        written = str(out)
    return {"agent": spec.to_dict(), "written": written, "config_source": scope.source}


def _spec_target(out: Path, bounds: OutputScope, force: bool) -> Path:
    """Where ``create`` writes: a ``.json`` file inside the root that is new or already a spec.

    Replacing an existing spec still needs ``--force``; no flag replaces anything else.
    """
    target = confine(out, bounds)
    refuse_non_spec_name(target)
    refuse_case_collision(target)
    if refuse_foreign_spec_file(target) and not force:
        raise ValidationError(
            "file_exists", i18n.t("agents.error.file_exists", path=str(out)), {"path": str(out)}
        )
    return target


def _export(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    factory = _factory(args, scope)
    ids = args.id or [s.id for s in factory.registry.list() if s.id not in _template_ids()]
    lang = args.export_lang or i18n.resolve_language()
    config, bounds = scope.config, _output_scope(scope)
    configured = args.tool_profile or config.harness.tool_profile
    specs = [
        _profiled(factory.resolve(factory.registry.get(i)), configured, config.models) for i in ids
    ]
    sources = {i: shown_source(factory.registry.source(i)) for i in ids}
    out_dir = confine_export_dir(Path(args.out), bounds)
    paths = export_all(
        specs, out_dir, lang, sources, check=lambda path: confine_export_file(path, bounds)
    )
    return {
        "exported": [str(p) for p in paths],
        "lang": i18n.resolve_language(lang),
        "tool_profile": configured,
        "warnings": _warnings(factory.registry),
        "config_source": scope.source,
    }


def _profiled(spec: AgentSpec, configured: str, models: ModelsConfig) -> AgentSpec:
    """``spec`` with the tool profile applied; ``auto`` goes by the tier of the agent's model."""
    profile = resolve_profile(configured, tier_of(spec.model, models))
    return replace(spec, tools=apply_profile(spec.tools, spec.permissions, profile))


def shown_source(path: Path | None, bases: Sequence[Path] | None = None) -> str:
    """``path`` relative to the repository, else to the working directory, else absolute.

    The repository comes first so that the shipped agents render the same from any directory.
    """
    if path is None:
        return ""
    resolved = path.resolve()
    for base in bases if bases is not None else (REPO_ROOT, Path.cwd()):
        try:
            return resolved.relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return resolved.as_posix()


def _template_ids() -> set[str]:
    templates = Path(REPO_ROOT, CATALOG_SUBDIRS[0])
    if not templates.is_dir():
        return set()
    return {p.stem for p in templates.glob("*.json")}


def register(subparsers: Subparsers) -> None:
    agent = subparsers.add_parser("agent", help=i18n.t("agents.cmd.help"))
    actions = agent.add_subparsers(dest="agent_command", metavar="<command>", required=True)

    def add(name: str, handler: Handler) -> argparse.ArgumentParser:
        sub = actions.add_parser(name, help=i18n.t(f"agents.cmd.{name}.help"))
        sub.add_argument("--dir", action="append", default=[], help=i18n.t("agents.cmd.dir"))
        sub.set_defaults(handler=handler)
        return sub

    add("list", _list)
    show = add("show", _show)
    show.add_argument("id", help=i18n.t("agents.cmd.id"))
    show.add_argument("--resolved", action="store_true", help=i18n.t("agents.cmd.resolved"))
    validate = add("validate", _validate)
    validate.add_argument("path", help=i18n.t("agents.cmd.path"))
    create = add("create", _create)
    create.add_argument("--template", required=True, help=i18n.t("agents.cmd.template"))
    create.add_argument("--id", required=True, help=i18n.t("agents.cmd.new_id"))
    create.add_argument("--set", action="append", default=[], help=i18n.t("agents.cmd.set"))
    create.add_argument("--out", default=None, help=i18n.t("agents.cmd.out_file"))
    create.add_argument("--force", action="store_true", help=i18n.t("agents.cmd.force"))
    export = add("export", _export)
    export.add_argument("--id", action="append", default=[], help=i18n.t("agents.cmd.export_id"))
    export.add_argument("--out", required=True, help=i18n.t("agents.cmd.out_dir"))
    export.add_argument("--lang", dest="export_lang", default=None, help=i18n.t("agents.cmd.lang"))
    export.add_argument(
        "--tool-profile",
        choices=TOOL_PROFILES,
        default=None,
        help=i18n.t("agents.cmd.tool_profile"),
    )
