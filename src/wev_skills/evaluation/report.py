"""Report rendering: JSON and Markdown, English and Brazilian Portuguese.

Every rendering starts with the notice that the results come from a scripted agent. Tables
hold raw counts and rates per configuration; no difference or improvement between
configurations is computed or printed anywhere.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from wev_skills import i18n
from wev_skills.evaluation.configs import SELECTION_OFF, HarnessConfig
from wev_skills.evaluation.metrics import Counts, EvalReport, RunResult

EMPTY_CELL = "-"
_COUNT_COLUMNS = (
    "attempts",
    "escalations",
    "tier_escalations",
    "guard_trips",
    "context_overflows",
    "items_elided",
    "items_summarized",
    "info_loss_failures",
    "unexecuted_verifications",
    "tool_selection_misses",
    "estimated_tool_tokens_offered",
    "estimated_tool_tokens_selected",
    "cost_units",
    "duration_units",
)


def notice(lang: str | None = None) -> str:
    """The mandatory statement of what a scripted evaluation can and cannot show."""
    return i18n.t("evaluation.notice", lang)


def to_document(report: EvalReport, lang: str | None = None) -> dict[str, Any]:
    """The JSON document: the notice first, then the language-neutral results."""
    language = i18n.resolve_language(lang)
    return {"notice": notice(language), "language": language, **report.to_dict()}


def render_json(report: EvalReport, lang: str | None = None) -> str:
    return json.dumps(to_document(report, lang), ensure_ascii=False, indent=2) + "\n"


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(" --- " for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def _count_headers(lang: str) -> list[str]:
    return [i18n.t(f"evaluation.col.{name}", lang) for name in _COUNT_COLUMNS]


def _count_cells(counts: Counts) -> list[object]:
    return [getattr(counts, name) for name in _COUNT_COLUMNS]


def _criteria_cell(counts: Counts) -> str:
    return f"{counts.criteria_met}/{counts.criteria_total}"


def _aggregate_section(report: EvalReport, lang: str) -> list[str]:
    headers = [
        i18n.t(f"evaluation.col.{name}", lang)
        for name in ("config", "runs", "successes", "success_rate", "criteria", "criteria_rate")
    ]
    rows = [
        [
            f"`{agg.config_id}`",
            agg.runs,
            agg.successes,
            f"{agg.success_rate:.4f}",
            _criteria_cell(agg.counts),
            f"{agg.criteria_rate:.4f}",
            *_count_cells(agg.counts),
        ]
        for agg in report.aggregates
    ]
    title = i18n.t("evaluation.report.aggregate", lang)
    return [f"## {title}", "", *_table([*headers, *_count_headers(lang)], rows), ""]


def _rules_section(report: EvalReport, lang: str) -> list[str]:
    headers = [i18n.t("evaluation.col.config", lang), i18n.t("evaluation.col.rules", lang)]
    rows = [
        [
            f"`{agg.config_id}`",
            ", ".join(f"{rc.rule}: {rc.count}" for rc in agg.counts.guard_trips_by_rule)
            or EMPTY_CELL,
        ]
        for agg in report.aggregates
    ]
    return [f"## {i18n.t('evaluation.report.rules', lang)}", "", *_table(headers, rows), ""]


def _subtasks_cell(run: RunResult) -> str:
    parts = [
        f"{sub.subtask_id}: {sub.status.value}" + (f" ({sub.failure})" if sub.failure else "")
        for sub in run.subtasks
    ]
    return "; ".join(parts)


def _task_section(report: EvalReport, task_id: str, lang: str) -> list[str]:
    runs = [run for run in report.runs if run.task_id == task_id]
    yes, no = i18n.t("evaluation.yes", lang), i18n.t("evaluation.no", lang)
    headers = [
        i18n.t(f"evaluation.col.{name}", lang)
        for name in ("config", "executor_tier", "planned", "tools", "success", "criteria")
    ]
    rows = [
        [
            f"`{run.config_id}`",
            run.executor_tier or EMPTY_CELL,
            yes if run.planned else no,
            f"{run.tool_profile}: {len(run.tools)}" if run.tool_profile else EMPTY_CELL,
            yes if run.success else no,
            _criteria_cell(run.counts),
            *_count_cells(run.counts),
            _subtasks_cell(run),
        ]
        for run in runs
    ]
    category = runs[0].category if runs else EMPTY_CELL
    all_headers = [*headers, *_count_headers(lang), i18n.t("evaluation.col.subtasks", lang)]
    return [f"### `{task_id}` ({category})", "", *_table(all_headers, rows), ""]


def _config_row(config: HarnessConfig, lang: str) -> list[object]:
    routing = f"fixed: {config.fixed_tier}" if config.routing == "fixed" else config.routing
    guard = i18n.t("evaluation.on" if config.guard_enabled else "evaluation.off", lang)
    return [
        f"`{config.id}`",
        config.planning,
        config.context_policy,
        config.elide_at,
        config.summarize_at,
        config.keep_recent,
        config.min_elide_tokens,
        config.max_attempts,
        config.max_parallel,
        routing,
        guard,
        config.executor_tier,
        config.tool_profile,
        config.tool_selection,
    ]


def _configs_section(report: EvalReport, lang: str) -> list[str]:
    names = (
        "config",
        "planning",
        "context_policy",
        "elide_at",
        "summarize_at",
        "keep_recent",
        "min_elide_tokens",
        "max_attempts",
        "max_parallel",
        "routing",
        "guard",
        "executor_tier",
        "tool_profile",
        "tool_selection",
    )
    headers = [i18n.t(f"evaluation.col.{name}", lang) for name in names]
    rows = [_config_row(config, lang) for config in report.configs]
    return [f"## {i18n.t('evaluation.report.configs', lang)}", "", *_table(headers, rows), ""]


def _tools_section(report: EvalReport, lang: str) -> list[str]:
    """Per subtask, what selection handed out and what had to be restored (selection on)."""
    names = ("run", "subtask", "tools_selected", "tools_dropped", "tools_restored")
    headers = [i18n.t(f"evaluation.col.{name}", lang) for name in names]
    rows = [
        [
            f"`{run.task_id}` / `{run.config_id}`",
            tools.subtask_id,
            ", ".join(tools.selected) or EMPTY_CELL,
            ", ".join(tools.dropped) or EMPTY_CELL,
            ", ".join(tools.restored) or EMPTY_CELL,
        ]
        for run in report.runs
        if run.tool_selection not in ("", SELECTION_OFF)
        for tools in run.subtask_tools
    ]
    title = i18n.t("evaluation.report.tool_selection", lang)
    note = i18n.t("evaluation.report.tool_selection_text", lang)
    return [f"## {title}", "", note, "", *_table(headers, rows), ""]


def _header(report: EvalReport, lang: str) -> list[str]:
    prices = ", ".join(
        f"{price.tier} = {price.simulated_units_per_token_step}"
        for price in report.simulated_prices
    )
    return [
        f"> {notice(lang)}",
        "",
        f"# {i18n.t('evaluation.report.title', lang)}",
        "",
        i18n.t("evaluation.report.label", lang, label=report.evidence_label),
        "",
        i18n.t("evaluation.report.units", lang, prices=prices),
        "",
    ]


def render_markdown(report: EvalReport, lang: str | None = None) -> str:
    language = i18n.resolve_language(lang)
    lines = [*_header(report, language), *_aggregate_section(report, language)]
    lines.extend(_rules_section(report, language))
    lines.extend([f"## {i18n.t('evaluation.report.per_task', language)}", ""])
    for task_id in report.task_ids:
        lines.extend(_task_section(report, task_id, language))
    lines.extend(_tools_section(report, language))
    lines.extend(_configs_section(report, language))
    lines.extend(
        [
            f"## {i18n.t('evaluation.report.limits', language)}",
            "",
            i18n.t("evaluation.report.limits_text", language),
        ]
    )
    return "\n".join(lines) + "\n"
