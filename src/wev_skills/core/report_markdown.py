"""Markdown form of the delivery report, in English or Brazilian Portuguese.

Everything the report shows about the run (objective, titles, summaries, blockers, command
text) is recorded data that came from plan files, repository files and command output. Each
field is cleaned and cut, and the body is fenced as data with ``security.untrusted.wrap``.
Only the title, the notices and the next step, which the engine writes, stay outside.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from wev_skills import i18n
from wev_skills.core.textsafe import clean_text
from wev_skills.security import untrusted

NONE_MARK = "-"
SOURCE_LABEL = "wev run record"


def _escape(value: object) -> str:
    """One table-safe line: the report holds run data, which must not break the layout."""
    text = NONE_MARK if value in (None, "") else clean_text(value)
    return text.replace("|", "\\|")


class _Writer:
    def __init__(self, lang: str) -> None:
        self.lang = lang
        self.lines: list[str] = []

    def t(self, key: str, **params: object) -> str:
        return i18n.t(f"orch.report.{key}", self.lang, **params)

    def label(self, group: str, value: object) -> str:
        """A translated enum value (status, evidence label); the raw value when unknown."""
        key = f"orch.report.{group}.{value}"
        text = i18n.t(key, self.lang)
        return _escape(value) if text == key else text

    def heading(self, level: int, text: str) -> None:
        if self.lines and self.lines[-1]:
            self.lines.append("")
        self.lines.extend([f"{'#' * level} {text}", ""])

    def bullet(self, text: str) -> None:
        self.lines.append(f"- {text}")

    def field(self, key: str, value: object) -> None:
        self.bullet(f"**{self.t(key)}:** {_escape(value)}")

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
        self.lines.append("| " + " | ".join(self.t(h) for h in headers) + " |")
        self.lines.append("|" + "---|" * len(headers))
        self.lines.extend("| " + " | ".join(_escape(c) for c in row) + " |" for row in rows)

    def items(self, heading_key: str, values: Sequence[object]) -> None:
        self.heading(2, self.t(heading_key))
        if not values:
            self.lines.append(self.t("none"))
        for value in values:
            self.bullet(_escape(value))


def _summary(out: _Writer, report: Mapping[str, Any]) -> None:
    out.field("objective", report["objective"])
    out.field("mode", report["mode"])
    out.field("status", out.label("status", report["status"]))
    classification, strategy = report.get("classification"), report.get("strategy")
    if classification:
        out.field("classification", out.t("classification_value", **classification))
    if strategy:
        out.field("strategy", out.t("strategy_value", **strategy))
    if report["reasons"]:
        out.heading(2, out.t("reasons"))
        for reason in report["reasons"]:
            out.bullet(_escape(reason))


def _tools(out: _Writer, chosen: Mapping[str, Any] | None) -> None:
    """The task's tool selection; the token figures are estimates and are labeled so."""
    if not chosen:
        return

    def line(key: str, **params: object) -> None:
        out.bullet(i18n.t(f"decisions.tools.report.{key}", out.lang, **params))

    def names(key: str) -> str:
        return _escape(", ".join(chosen[key]))

    line("offered", tools=names("offered"))
    line("selected", tools=names("selected"), source=_escape(chosen["source"]))
    line("dropped", tools=names("dropped"))
    estimate = chosen["estimated_definition_tokens"]
    line("estimate", offered=estimate["offered"], selected=estimate["selected"])
    line("misses", count=chosen["miss_count"])
    for miss in chosen["misses"]:
        line("miss", tool=_escape(miss["tool"]), reason=_escape(miss["reason"]))


def _task(out: _Writer, task: Mapping[str, Any]) -> None:
    out.heading(3, f"{_escape(task['id'])}: {_escape(task['title'])}")
    out.field("task_status", out.label("task", task["status"]))
    out.field("evidence", out.label("evidence", task["evidence"]))
    out.field("agent", task["agent_id"])
    out.field("model", task["model"])
    out.field("attempts", task["attempts"])
    if task.get("blocked_because"):
        out.field("blocked_because", out.label("blocked", task["blocked_because"]))
    if task["summary"]:
        out.field("summary", task["summary"])
    if task.get("work_note"):
        out.bullet(_escape(task["work_note"]))
    for warning in task.get("warnings", ()):
        out.bullet(out.t("warning", text=_escape(warning)))
    _tools(out, task.get("tool_selection"))
    out.lines.append("")
    out.table(
        ("criterion", "criterion_status", "evidence", "support"),
        [
            (
                c["criterion"],
                out.label("criterion", c["status"]),
                out.label("evidence", c["evidence"]),
                c.get("support_note", ""),
            )
            for c in task["criteria"]
        ],
    )
    out.lines.append("")
    if task["checks_run"]:
        out.table(
            ("check_ran", "exit_code", "log", "evidence"),
            [
                (c["command"], c["exit_code"], c["log_ref"], out.label("evidence", c["evidence"]))
                for c in task["checks_run"]
            ],
        )
    else:
        out.lines.append(out.t("no_checks_ran"))
    for check in task["checks_not_run"]:
        reason = check["reason"] or out.t("not_run")
        out.bullet(
            out.t("check_not_run", command=_escape(check["command"]), reason=_escape(reason))
        )
    _reviews(out, task["review"])


def _reviews(out: _Writer, review: Mapping[str, Any]) -> None:
    for item in review["reviews"]:
        verdict = out.t("review_accept" if item["accepted"] else "review_reject")
        out.bullet(
            out.t(
                "review_line",
                reviewer=_escape(item["reviewer"]),
                verdict=verdict,
                summary=_escape(item["summary"]),
            )
            + " "
            + out.t("reviewer_self_declared")
        )
    if review["required"] and not review["accepted"]:
        out.bullet(out.t("review_missing"))


def _amendments(out: _Writer, report: Mapping[str, Any]) -> None:
    """Every plan change made to a task that had already started, with before and after."""
    out.heading(2, out.t("plan_amendments"))
    found = report.get("plan_amendments", ())
    if not found:
        out.lines.append(out.t("none"))
    for item in found:
        out.bullet(
            out.t("amendment", at=item["at"], task=_escape(item["task_id"]))
            + " "
            + _escape(item["reason"])
        )
        rows = [
            (c["field"], "; ".join(c["before"]) or NONE_MARK, "; ".join(c["after"]) or NONE_MARK)
            for c in item["changes"]
        ]
        out.lines.append("")
        out.table(("amended_field", "amended_before", "amended_after"), rows)
        out.lines.append("")


def _body(out: _Writer, report: Mapping[str, Any]) -> str:
    _summary(out, report)
    out.heading(2, out.t("tasks"))
    if not report["tasks"]:
        out.lines.append(out.t("none"))
    for task in report["tasks"]:
        _task(out, task)
    approvals = [
        f"{a['id']} ({a['status']}{', ' + out.t('stale') if a.get('stale') else ''}): {a['action']}"
        for a in report["approvals"]
    ]
    _amendments(out, report)
    out.items("approvals", approvals)
    out.items("stale_approvals", report.get("stale_approvals", ()))
    out.items("blockers", report["blockers"])
    trips = [
        f"{t.get('at') or NONE_MARK} {t['task_id'] or NONE_MARK}: {t['action']} ({t['rule']})"
        for t in report["guard"]["trips"]
    ]
    out.items("guard_trips", trips)
    acknowledged = [
        f"{a['at']}: {'; '.join(a['reasons'][:1])}"
        for a in report["guard"].get("acknowledgements", ())
    ]
    out.items("guard_acknowledgements", acknowledged)
    out.items("changed_files", report["changed_files"])
    return "\n".join(out.lines).strip()


def render_markdown(report: Mapping[str, Any], lang: str | None = None) -> str:
    """The report as Markdown. It restates the JSON report; it adds no claim of its own."""
    code = i18n.resolve_language(lang)
    out = _Writer(code)
    with i18n.use_language(code):
        fenced = untrusted.wrap(_body(out, report), SOURCE_LABEL)
    head = [f"# {out.t('title', run=_escape(report['run_id']))}", ""]
    head += [f"> {notice}" for notice in report.get("notices", ())]
    tail = [f"## {out.t('next_step')}", "", f"`{_escape(report['next_step'])}`"]
    return "\n".join([*head, "", fenced, "", *tail]).strip() + "\n"
