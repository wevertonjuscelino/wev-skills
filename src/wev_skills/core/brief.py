"""The plan reminder: a compact, plain-text brief of one run.

A persistent plan re-shown to the model is one of the harness components whose value
depends on model capability (docs/research/hypotheses.md, H8). This module only builds the
text; whether showing it helps a given model has not been measured here. The Claude Code
hooks inject it after context compaction and, when ``harness.plan_reminder`` is on, with
each prompt.

The brief is recorded state, not the truth about the repository: ``wev run resume`` checks.

The objective, task titles and acceptance criteria come from the request and from plan
files. They are data. Each is cleaned (no control characters or escape sequences, one line,
cut to a limit) and they are shown inside a fence that says so (``security.untrusted.wrap``).
The run line, the approval lines and the next step, which the engine writes, stay outside.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import PlanTask, TaskStatus
from wev_skills.core.errors import ValidationError
from wev_skills.core.textsafe import clean_text
from wev_skills.security import untrusted
from wev_skills.state.model import RunState

DEFAULT_MAX_CHARS = 600
MIN_MAX_CHARS = 80
FIELD_MAX_CHARS = 160
TITLE_MAX_CHARS = 60
ELLIPSIS = "..."
PRIORITY_FRAME = 0
"""The run line and the next step: kept before anything else."""
PRIORITY_CONTEXT = 1
PRIORITY_TASKS = 2
PRIORITY_CRITERIA = 3
CURRENT_STATUSES = (TaskStatus.RUNNING, TaskStatus.READY)
SOURCE_LABEL = "wev run record"

Line = tuple[int, str]


def one_line(text: str, limit: int = FIELD_MAX_CHARS) -> str:
    """``text`` on a single line, shortened with a visible marker when longer than ``limit``."""
    return clean_text(text, limit)


def current_task(state: RunState) -> PlanTask | None:
    """The first running task, else the first ready one, in plan order."""
    tasks = state.plan.tasks if state.plan else ()
    for status in CURRENT_STATUSES:
        for task in tasks:
            if state.tasks[task.id].status is status:
                return task
    return None


def _task_lines(state: RunState, lang: str) -> list[Line]:
    if state.plan is None:
        return [(PRIORITY_TASKS, i18n.t("orch.brief.no_plan", lang))]
    tasks = state.plan.tasks
    done = sum(1 for task in tasks if state.tasks[task.id].status is TaskStatus.VERIFIED)
    lines = [(PRIORITY_TASKS, i18n.t("orch.brief.tasks", lang, done=done, total=len(tasks)))]
    for task in tasks:
        record = state.tasks[task.id]
        title = one_line(task.title or task.objective, TITLE_MAX_CHARS)
        agent = one_line(record.agent_id, TITLE_MAX_CHARS) or "-"
        name = one_line(task.id, TITLE_MAX_CHARS)
        lines.append((PRIORITY_TASKS, f"- {name} [{record.status.value}] {title} ({agent})"))
    return lines


def _criteria_lines(state: RunState, lang: str) -> list[Line]:
    task = current_task(state)
    if task is None or not task.acceptance_criteria:
        return []
    heading = i18n.t("orch.brief.current", lang, task=one_line(task.id, TITLE_MAX_CHARS))
    items = [f"- {one_line(text)}" for text in task.acceptance_criteria]
    return [(PRIORITY_CRITERIA, line) for line in (heading, *items)]


def data_lines(state: RunState, lang: str) -> list[Line]:
    """Lines made of recorded text: objective, tasks, the current task's criteria."""
    objective = i18n.t("orch.brief.objective", lang, objective=one_line(state.objective))
    return [
        (PRIORITY_CONTEXT, objective),
        *_intake_lines(state, lang),
        *_task_lines(state, lang),
        *_criteria_lines(state, lang),
    ]


def _intake_lines(state: RunState, lang: str) -> list[Line]:
    intake = state.discovery.get("intake")
    if not isinstance(intake, Mapping) or not isinstance(intake.get("brief"), Mapping):
        return []
    recorded = intake["brief"]
    lines: list[Line] = []
    for field in ("scope", "constraints"):
        value = recorded.get(field)
        if isinstance(value, str) and value:
            text = i18n.t(f"intake.brief.{field}", lang, value=one_line(value))
            lines.append((PRIORITY_CONTEXT, text))
    criteria = recorded.get("done", ())
    if isinstance(criteria, (tuple, list)):
        for value in criteria:
            if isinstance(value, str):
                text = i18n.t("intake.brief.done", lang, value=one_line(value))
                lines.append((PRIORITY_CRITERIA, text))
    return lines


def _approval_lines(state: RunState, lang: str) -> list[Line]:
    lines: list[Line] = []
    live = [note.id for note in progress.live_approvals(state)]
    stale = [note.id for note in progress.stale_approvals(state)]
    if live:
        text = i18n.t("orch.brief.approvals", lang, ids=", ".join(live))
        lines.append((PRIORITY_CONTEXT, text))
    if stale:
        text = i18n.t("orch.brief.stale_approvals", lang, ids=", ".join(stale))
        lines.append((PRIORITY_CRITERIA, text))
    return lines


def brief_lines(state: RunState, next_step: str, lang: str) -> list[Line]:
    """Every line of the brief with its priority, in display order (without the fence)."""
    header = i18n.t(
        "orch.brief.header", lang, run=state.run_id, mode=state.mode.value, phase=state.phase.value
    )
    step = " ".join(next_step.split())
    return [
        (PRIORITY_FRAME, header),
        *data_lines(state, lang),
        *_approval_lines(state, lang),
        (PRIORITY_FRAME, i18n.t("orch.brief.next", lang, step=step)),
    ]


def _size(texts: Sequence[str]) -> int:
    return len("\n".join(texts))


def fit_lines(lines: Sequence[Line], max_chars: int, marker: str) -> str:
    """Join as many whole lines as fit in ``max_chars``, most important first.

    Lines keep their display order and none is ever cut. Frame lines (priority 0) are
    placed first and a frame line that does not fit is skipped; the first other line that
    does not fit ends the selection, so nothing less important is shown in its place.
    ``marker`` (with ``{count}``) says how many lines were left out and goes before the
    last line when there is room for it.
    """
    texts = [text for _, text in lines]
    if _size(texts) <= max_chars:
        return "\n".join(texts)
    order = sorted(range(len(lines)), key=lambda index: (lines[index][0], index))
    kept: list[int] = []
    for index in order:
        candidate = [*kept, index]
        frame = lines[index][0] == PRIORITY_FRAME
        note = marker.format(count=len(lines) - len(candidate))
        reserve = 0 if frame else len(note) + 1
        if _size([texts[i] for i in candidate]) + reserve > max_chars:
            if frame:
                continue
            break
        kept = candidate
    shown = [texts[index] for index in sorted(kept)]
    note = marker.format(count=len(lines) - len(kept))
    if shown and _size([*shown, note]) <= max_chars:
        shown.insert(len(shown) - 1 if len(shown) > 1 else len(shown), note)
    return "\n".join(shown)


def _fenced(texts: Sequence[str]) -> str:
    return untrusted.wrap("\n".join(texts), SOURCE_LABEL)


def _kept_data(data: Sequence[Line], room: int) -> list[int]:
    """Indexes of the data lines that fit, fenced, in ``room`` characters; most important
    first, and the first line that does not fit ends the selection."""
    order = sorted(range(len(data)), key=lambda index: (data[index][0], index))
    kept: list[int] = []
    for index in order:
        candidate = sorted([*kept, index])
        if len(_fenced([data[i][1] for i in candidate])) > room:
            break
        kept = candidate
    return kept


def assemble(
    header: Line, data: Sequence[Line], tail: Sequence[Line], max_chars: int, marker: str
) -> str:
    """The brief: run line, the fenced data, then the engine's own lines.

    Engine lines are placed first. Data lines take what room is left, and are dropped
    whole, never cut, when the fence with them does not fit; a marker says how many lines
    were left out.
    """
    whole = [header[1], _fenced([text for _, text in data]), *(text for _, text in tail)]
    if _size(whole) <= max_chars:
        return "\n".join(whole)
    frame = fit_lines([header, *tail], max_chars, "").split("\n")
    note_room = len(marker.format(count=len(data) + len(tail) + 1)) + 1
    room = max_chars - _size(frame) - 1 - note_room
    kept = _kept_data(data, room)
    shown = [text for text in frame if text]
    omitted = len(data) - len(kept) + (1 + len(tail) - len(shown))
    if kept and shown:
        shown.insert(1, _fenced([data[i][1] for i in kept]))
    note = marker.format(count=omitted)
    if omitted and shown and _size([*shown, note]) <= max_chars:
        shown.insert(len(shown) - 1 if len(shown) > 1 else len(shown), note)
    return "\n".join(shown)


def build_brief(
    state: RunState, next_step: str, max_chars: int = DEFAULT_MAX_CHARS, lang: str | None = None
) -> str:
    """The brief of ``state`` in at most ``max_chars`` characters; pure, nothing is read."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < MIN_MAX_CHARS:
        message = i18n.t("orch.error.max_chars", minimum=MIN_MAX_CHARS)
        raise ValidationError("invalid_max_chars", message, {"minimum": MIN_MAX_CHARS})
    code = i18n.resolve_language(lang)
    marker = i18n.t("orch.brief.omitted", code, run=state.run_id, count="{count}")
    lines = brief_lines(state, next_step, code)
    data = data_lines(state, code)
    tail = lines[1 + len(data) :]
    with i18n.use_language(code):
        return assemble(lines[0], data, tail, max_chars, marker)
