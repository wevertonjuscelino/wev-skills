"""Render resolved agent specs as Claude Code subagent Markdown files.

Only frontmatter fields listed in the official Claude Code documentation are emitted:
``name``, ``description``, ``tools``, ``disallowedTools``, ``model``, ``skills``, ``maxTurns``.
Everything else goes into the body, which is the subagent's system prompt.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.output import refuse_case_collision
from wev_skills.agents.spec import MAX_BUDGET_UNITS, AgentSpec, LocalizedAgent, number_in_range
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.core.fsutil import atomic_write_text

TIER_TO_CLAUDE_MODEL = {"economy": "haiku", "standard": "sonnet", "premium": "opus"}
GENERATED_MARKER = "[//]: # (wev:generated-subagent)"
"""Fixed, never localized: how ``export_all`` recognizes a file it may replace.

A Markdown link reference definition, which renders as nothing. It is not an HTML comment
on purpose: the body keeps exactly one comment terminator, the one of the generated line.
"""
FRONTMATTER_FENCE = "---"
_COMMENT_UNSAFE = re.compile(r"-->|[\x00-\x1f\x7f]")
_SAFE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_YAML_LINE_BREAKS = {
    char: f"\\u{ord(char):04x}" for char in ("\u0085", "\u2028", "\u2029", "\u007f", "\ufeff")
}


def yaml_quote(value: str) -> str:
    """A YAML double-quoted scalar on a single line (JSON escaping is a YAML subset)."""
    text = json.dumps(value, ensure_ascii=False)
    for char, escaped in _YAML_LINE_BREAKS.items():
        text = text.replace(char, escaped)
    return text


def claude_model(model: str | None) -> str | None:
    if model is None:
        return None
    mapped = TIER_TO_CLAUDE_MODEL.get(model)
    if mapped is not None:
        return mapped
    if not _SAFE_MODEL.fullmatch(model):
        raise ValidationError("unsafe_model", i18n.t("agents.error.unsafe_model", model=model))
    return model


def _frontmatter(spec: AgentSpec, view: LocalizedAgent) -> list[str]:
    lines = [f"name: {yaml_quote(spec.id)}", f"description: {yaml_quote(view.description)}"]
    tools = spec.tools
    if tools is not None and tools.allow:
        lines.append(f"tools: {yaml_quote(', '.join(tools.allow))}")
    if tools is not None and tools.deny:
        lines.append(f"disallowedTools: {yaml_quote(', '.join(tools.deny))}")
    model = claude_model(spec.model)
    if model is not None:
        lines.append(f"model: {yaml_quote(model)}")
    if spec.skills:
        lines.append("skills:")
        lines.extend(f"  - {yaml_quote(skill)}" for skill in spec.skills)
    if spec.budget is not None and spec.budget.max_units is not None:
        lines.append(f"maxTurns: {_max_turns(spec.budget.max_units)}")
    return lines


def _max_turns(units: float) -> int:
    """The budget as a turn count; a spec built without validation may carry ``inf``."""
    if not number_in_range(units, MAX_BUDGET_UNITS):
        message = i18n.t("agents.error.invalid_budget", value=repr(units), maximum=MAX_BUDGET_UNITS)
        raise ValidationError("invalid_budget", message, {"max_units": repr(units)})
    return max(1, math.ceil(units))


def _bullets(items: Iterable[str]) -> list[str]:
    return [f"- {item.strip().replace(chr(10), chr(10) + '  ')}" for item in items]


def _section(heading: str, body: list[str]) -> list[str]:
    return [f"## {heading}", "", *body, ""] if body else []


def _limits(spec: AgentSpec, lang: str) -> list[str]:

    def t(key: str, **params: object) -> str:
        return i18n.t(key, lang, **params)

    perms = spec.permissions
    rows: list[str] = []
    if perms is not None:
        modes = ", ".join(m.value for m in perms.modes or ())
        rows += [
            t("agents.export.modes", value=modes),
            t("agents.export.max_risk", value=perms.max_risk.value if perms.max_risk else ""),
            t("agents.export.may_mutate", value=_yes_no(perms.may_mutate, lang)),
            t("agents.export.may_remote", value=_yes_no(perms.may_use_remote, lang)),
        ]
    if spec.timeout_seconds is not None:
        rows.append(t("agents.export.timeout", value=f"{spec.timeout_seconds:g}"))
    if spec.max_attempts is not None:
        rows.append(t("agents.export.attempts", value=spec.max_attempts))
    return _bullets(rows)


def _yes_no(flag: bool | None, lang: str) -> str:
    return i18n.t("agents.export.yes" if flag else "agents.export.no", lang)


def _escalation(spec: AgentSpec, lang: str) -> list[str]:
    esc = spec.escalation
    if esc is None or esc.on_failure is None:
        return []
    rows = [i18n.t("agents.export.on_failure", lang, value=esc.on_failure.value)]
    if esc.to:
        rows.append(i18n.t("agents.export.escalate_to", lang, value=esc.to))
    return _bullets(rows)


def _generated_line(source: str, lang: str) -> str:
    """The comment naming the spec file this agent was rendered from, when it is known.

    ``source`` is a path, so it is data: anything that could end the comment is dropped.
    """
    shown = _COMMENT_UNSAFE.sub("", source).strip()
    if not shown:
        return f"<!-- {i18n.t('agents.export.generated_unknown', lang)} -->"
    return f"<!-- {i18n.t('agents.export.generated', lang, source=shown)} -->"


def _body(spec: AgentSpec, view: LocalizedAgent, lang: str, source: str) -> list[str]:

    def h(key: str) -> str:
        return i18n.t(f"agents.export.h.{key}", lang)

    parts = [
        _generated_line(source, lang),
        GENERATED_MARKER,
        "",
        f"# {view.name}",
        "",
    ]
    if view.instructions:
        parts += [view.instructions.strip(), ""]
    parts += _section(h("specialties"), _bullets(spec.specialties))
    parts += _section(h("responsibilities"), _bullets(view.responsibilities))
    parts += _section(h("success"), _bullets(view.success_criteria))
    parts += _section(h("checks"), _bullets(f"`{c}`" for c in spec.required_checks))
    parts += _section(h("stop"), _bullets(view.stop_conditions))
    parts += _section(h("escalation"), _escalation(spec, lang))
    parts += _section(h("limits"), _limits(spec, lang))
    parts += _section(h("output"), [view.output_format.strip()] if view.output_format else [])
    parts += _section(h("contract"), [i18n.t("agents.export.contract", lang)])
    return parts


def render_subagent(spec: AgentSpec, lang: str = "en", source: str = "") -> str:
    """The subagent file for a *resolved* spec: YAML frontmatter, then the system prompt.

    ``source`` is the path of the spec file as it should be shown (relative to the
    repository or the working directory); leave it empty for a spec that has no file.
    """
    if spec.extends is not None:
        raise ValidationError(
            "unresolved_spec", i18n.t("agents.error.unresolved", id=spec.id), {"id": spec.id}
        )
    code = i18n.resolve_language(lang)
    view = spec.localized(code)
    front = [FRONTMATTER_FENCE, *_frontmatter(spec, view), FRONTMATTER_FENCE]
    return "\n".join([*front, *_body(spec, view, code, source)]).rstrip("\n") + "\n"


def is_generated_subagent(text: str) -> bool:
    """True when ``text`` is a file ``render_subagent`` produced: it opens with frontmatter
    and carries ``GENERATED_MARKER`` on a line of its own."""
    lines = text.splitlines()
    return bool(lines) and lines[0] == FRONTMATTER_FENCE and GENERATED_MARKER in lines


def export_all(
    specs: Iterable[AgentSpec],
    out_dir: Path,
    lang: str = "en",
    sources: Mapping[str, str] | None = None,
    check: Callable[[Path], object] | None = None,
) -> list[Path]:
    """Write ``<id>.md`` for each resolved spec atomically; never outside ``out_dir``.

    ``sources`` maps an agent id to the spec path shown in its generated comment. Every
    target is checked before any is written: by ``check`` (the caller's own rule, which
    raises to refuse), then against a name that differs only by case and against an existing
    file this exporter did not generate.
    """
    root = Path(out_dir).resolve()
    shown = sources or {}
    rendered: list[tuple[Path, str]] = []
    for spec in specs:
        text = render_subagent(spec, lang, shown.get(spec.id, ""))
        rendered.append((_target(root, spec.id), text))
    for path, _ in rendered:
        if check is not None:
            check(path)
        refuse_case_collision(path)
        _refuse_foreign_file(path)
    for path, text in rendered:
        atomic_write_text(path, text)
    return [path for path, _ in rendered]


def _refuse_foreign_file(path: Path) -> None:
    """Raise when ``path`` exists and is not a subagent file generated by this exporter."""
    if not path.exists():
        return
    try:
        generated = is_generated_subagent(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        generated = False
    if not generated:
        message = i18n.t("agents.error.not_generated_file", path=str(path))
        raise PermissionDenied("not_generated_file", message, {"path": str(path)})


def _target(root: Path, agent_id: str) -> Path:
    if not _SAFE_ID.fullmatch(agent_id) or len(agent_id) > 64:
        raise ValidationError("unsafe_agent_id", i18n.t("agents.error.unsafe_id", id=agent_id))
    path = root / f"{agent_id}.md"
    if path.parent != root or path.is_symlink() or path.resolve().parent != root:
        raise ValidationError("unsafe_agent_id", i18n.t("agents.error.unsafe_id", id=agent_id))
    return path
