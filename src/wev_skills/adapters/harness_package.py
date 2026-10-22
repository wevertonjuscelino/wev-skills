"""Build the package files of the skills and agents for Codex, Gemini CLI and OpenCode.

Layouts and field names come from docs/research/harness-{codex,gemini,opencode}.md. A detail
the notes mark unknown is left out and reported by ``skipped_notes``. The hook commands call
``<wev> hook ... --harness X`` with ``wev`` the absolute launcher path, shell-quoted.
"""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code.subagent import FRONTMATTER_FENCE, render_subagent
from wev_skills.adapters.opencode_plugin import render_plugin
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.core.wiring import CATALOG_SUBDIRS, REPO_ROOT, catalog_directories

TARGETS = ("codex", "gemini", "opencode")
PACKAGE_NAME = "wev-skills"
_PLACEHOLDER = "${CLAUDE_PLUGIN_ROOT}"
_QUOTED_WEV = re.compile(r'"\$\{CLAUDE_PLUGIN_ROOT\}/bin/wev"|\$\{CLAUDE_PLUGIN_ROOT\}/bin/wev')
HOOK_TIMEOUT_SECONDS = 10
_SHELL_MATCHER = {"codex": "Bash", "gemini": "run_shell_command"}
_EVENTS = {
    "codex": ("SessionStart", "PreToolUse"),
    "gemini": ("SessionStart", "BeforeTool"),
}


def render_skill_text(text: str, wev_path: Path) -> str:
    """``text`` with the Claude Code plugin root replaced by this clone's absolute paths."""
    quoted = shlex.quote(str(wev_path))
    text = _QUOTED_WEV.sub(lambda _: quoted, text)
    return text.replace(_PLACEHOLDER, shlex.quote(str(wev_path.parent.parent)))


def _version() -> str:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def _hook_command(wev_path: Path, hook: str, harness: str) -> str:
    return f"{shlex.quote(str(wev_path))} hook {hook} --harness {harness}"


def _hook_entry(command: str, harness: str) -> dict[str, Any]:
    timeout = HOOK_TIMEOUT_SECONDS * (1000 if harness == "gemini" else 1)
    return {"type": "command", "command": command, "timeout": timeout}


def _hooks_json(harness: str, wev_path: Path) -> str:
    start, before = _EVENTS[harness]
    session = {"hooks": [_hook_entry(_hook_command(wev_path, "session-context", harness), harness)]}
    guard = {
        "matcher": _SHELL_MATCHER[harness],
        "hooks": [_hook_entry(_hook_command(wev_path, "pre-tool-use", harness), harness)],
    }
    return _json({"hooks": {start: [session], before: [guard]}})


def _description() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return str(tomllib.loads(text)["project"].get("description", PACKAGE_NAME))


def _codex_manifest() -> str:
    return _json({
        "name": PACKAGE_NAME,
        "version": _version(),
        "description": _description(),
        "skills": "./skills/",
        "hooks": "./hooks.json",
    })  # fmt: skip


def _gemini_manifest() -> str:
    return _json({"name": PACKAGE_NAME, "version": _version(), "description": _description()})


def _write(out: Path, relative: str, text: str, written: list[Path]) -> None:
    path = out / relative
    atomic_write_text(path, text)
    written.append(path)


def _write_skills(out: Path, wev_path: Path, written: list[Path]) -> None:
    skills = REPO_ROOT / "skills"
    for source in sorted(p for p in skills.rglob("*") if p.is_file()):
        text = render_skill_text(source.read_text(encoding="utf-8"), wev_path)
        _write(out, f"skills/{source.relative_to(skills).as_posix()}", text, written)


def _agent_specs() -> list[tuple[str, Any]]:
    """Resolved non-template specs with the repository-relative path they came from."""
    registry = AgentRegistry().discover(catalog_directories())
    factory = AgentFactory(registry)
    templates = {p.stem for p in (REPO_ROOT / CATALOG_SUBDIRS[0]).glob("*.json")}
    result = []
    for spec in registry.list():
        source = registry.source(spec.id)
        shown = source.relative_to(REPO_ROOT).as_posix() if source is not None else ""
        if spec.id not in templates:
            result.append((shown, factory.resolve(spec)))
    return sorted(result, key=lambda item: item[1].id)


def _agent_text(rendered: str, extra: list[str], with_name: bool) -> str:
    """Another harness's agent file: its own frontmatter, the exporter's body unchanged."""
    lines = rendered.split("\n")
    end = lines.index(FRONTMATTER_FENCE, 1)
    front = lines[1:end]
    keep = [
        ln
        for ln in front
        if ln.startswith("description: ") or (with_name and ln.startswith("name: "))
    ]
    return "\n".join([FRONTMATTER_FENCE, *keep, *extra, FRONTMATTER_FENCE, *lines[end + 1 :]])


def _write_agents(out: Path, harness: str, written: list[Path]) -> None:
    for shown, spec in _agent_specs():
        rendered = render_subagent(spec, "en", shown)
        extra = ["mode: subagent"] if harness == "opencode" else []
        text = _agent_text(rendered, extra, with_name=harness == "gemini")
        _write(out, f"agents/{spec.id}.md", text, written)


def build_package(target: str, out: Path, wev_path: Path) -> list[Path]:
    """Write the layout of ``target`` under ``out`` and return every file written."""
    if target not in TARGETS:
        message = i18n.t("harness.error.unknown_target", target=target, targets=", ".join(TARGETS))
        raise ValidationError("unknown_harness_target", message)
    if out.exists() and any(out.iterdir()):
        raise StateConflict(
            "export_dir_not_empty",
            i18n.t("harness.error.not_empty", path=str(out)),
            {"path": str(out)},
        )
    written: list[Path] = []
    _write_skills(out, wev_path, written)
    if target == "codex":
        _write(out, ".codex-plugin/plugin.json", _codex_manifest(), written)
        _write(out, "hooks.json", _hooks_json("codex", wev_path), written)
    elif target == "gemini":
        _write(out, "gemini-extension.json", _gemini_manifest(), written)
        _write(out, "hooks/hooks.json", _hooks_json("gemini", wev_path), written)
        _write_agents(out, "gemini", written)
    else:
        _write(out, "plugins/wev-guard.js", render_plugin(wev_path), written)
        _write_agents(out, "opencode", written)
    return written


def skipped_notes(target: str) -> list[str]:
    """What the notes leave unknown for ``target`` and the package therefore omits."""
    keys = {
        "codex": ["codex_agents", "codex_trust"],
        "gemini": ["agent_tools", "gemini_context", "gemini_hooks_shape"],
        "opencode": ["agent_tools"],
    }.get(target, [])
    return [i18n.t(f"harness.skipped.{key}", target=target) for key in keys]
