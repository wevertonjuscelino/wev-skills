"""What to do next: the actionable steps of a run, most relevant first.

``next_steps`` returns every step someone can take now; ``next_step`` is the first of them.
A step is a command line, except where only a person may act (an approval, a denied gate, a
task that used all its attempts) or where no command would move the run (a plan waiting for
review in plan mode, a check on a tree nothing changed in): there it is an instruction, and
it never prints a command an agent could run to approve its own request.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from wev_skills import i18n
from wev_skills.core import progress
from wev_skills.core.contracts import Mode, PlanTask, TaskStatus
from wev_skills.core.discovery import CheckSuggestion, default_check
from wev_skills.state.model import Phase, RunState

DISCOVERY_CHECKS_KEY = "checks"
PLAN_FILE = "plan.json"

SuggestReviewer = Callable[[str], str]
Denied = Mapping[str, str]
"""Task id -> approval id, for tasks whose start a person denied (see ``Engine.denied_gates``)."""


def suggestions_of(state: RunState) -> tuple[CheckSuggestion, ...]:
    items = state.discovery.get(DISCOVERY_CHECKS_KEY, [])
    return tuple(CheckSuggestion.from_dict(dict(item)) for item in items)


def needs_checks(state: RunState) -> bool:
    """A run that needs no plan but has no check to run: a plan must supply the checks."""
    direct = state.strategy is not None and not state.strategy.needs_plan
    return state.plan is None and direct and not default_check(suggestions_of(state))


def approval_step(approval_id: str) -> str:
    """What to do about a pending approval: an instruction for the caller, not a command.

    Printing a grant command line here would invite an agent to approve its own request,
    so the step says to stop and names what the human runs in their own terminal.
    """
    return i18n.t("orch.step.approval", id=approval_id)


def reopen_step(state: RunState, task_id: str) -> str:
    """A task that used all its attempts: only a person can give it more."""
    return i18n.t("orch.step.reopen", task=task_id, run=state.run_id)


def denied_step(state: RunState, task_id: str, approval_id: str) -> str:
    """A denied gate: say it was denied and how the operator reopens it, never how to grant."""
    return i18n.t("orch.step.denied", task=task_id, id=approval_id, run=state.run_id)


def _ids(state: RunState, statuses: Sequence[TaskStatus]) -> list[str]:
    tasks = state.plan.tasks if state.plan else ()
    return [t.id for t in tasks if state.tasks[t.id].status in statuses]


def _awaiting_review(state: RunState) -> str | None:
    if not progress.review_required(state):
        return None
    return next(
        (
            tid
            for tid in _ids(state, (TaskStatus.VERIFIED,))
            if not progress.review_accepted(state, tid)
        ),
        None,
    )


def _running_step(state: RunState, task_id: str, suffix: str) -> str:
    fresh = progress.fresh_verification(state, task_id)
    if fresh is not None and fresh.all_met:
        return f"wev task record {task_id} --status verified --summary <text>{suffix}"
    untouched = fresh is not None and fresh.tree_changed is False
    if untouched and not progress.plan_task(state, task_id).read_only:
        return i18n.t("orch.step.no_change", task=task_id, run=state.run_id)
    return f"wev task check {task_id}{suffix}"


def _review_step(
    state: RunState, task_id: str, suggest: SuggestReviewer | None, suffix: str
) -> str:
    executor = state.tasks[task_id].agent_id
    who = (suggest(executor) if suggest else "") or "<agent-id>"
    return f"wev task review {task_id} --reviewer {who} --verdict accept --summary <text>{suffix}"


def _before_tasks(state: RunState, suffix: str) -> tuple[str, ...]:
    """Steps of a run that cannot hand out work yet; empty once tasks can run."""
    if state.phase is Phase.DONE:
        return (f"wev run report{suffix}",)
    if state.plan is None:
        direct = state.strategy is not None and not state.strategy.needs_plan
        if direct and state.mode is not Mode.PLAN and not needs_checks(state):
            return (f"wev task next{suffix}",)
        return (f"wev plan set --file {PLAN_FILE}{suffix}",)
    if state.mode is Mode.PLAN:
        return (i18n.t("orch.step.plan_ready", run=state.run_id),)
    return ()


def _task_steps(state: RunState, suggest: SuggestReviewer | None, suffix: str) -> list[str]:
    live = progress.live_approvals(state)
    held = {note.task_id for note in live if note.kind == progress.KIND_COMMAND}
    running = [tid for tid in _ids(state, (TaskStatus.RUNNING,)) if tid not in held]
    steps = [_running_step(state, tid, suffix) for tid in running]
    steps += [approval_step(note.id) for note in live]
    steps += [f"wev task start {tid}{suffix}" for tid in _ids(state, (TaskStatus.READY,))]
    review = _awaiting_review(state)
    if review is not None:
        steps.append(_review_step(state, review, suggest, suffix))
    return steps


def _held_back(state: RunState, task: PlanTask, stuck: set[str], seen: frozenset[str]) -> bool:
    """``task`` is stuck, or depends (through any chain) on a task that is."""
    if task.id in stuck:
        return True
    tasks = {item.id: item for item in (state.plan.tasks if state.plan else ())}
    chain = seen | {task.id}
    return any(
        dep in tasks and dep not in chain and _held_back(state, tasks[dep], stuck, chain)
        for dep in task.depends_on
    )


def _startable_later(state: RunState, stuck: set[str]) -> list[str]:
    """Waiting tasks that ``wev task next`` can still lead somewhere for."""
    tasks = state.plan.tasks if state.plan else ()
    waiting = (*progress.WAITING, *progress.RETRYABLE)
    return [
        task.id
        for task in tasks
        if state.tasks[task.id].status in waiting
        and not _held_back(state, task, stuck, frozenset())
    ]


def next_steps(
    state: RunState, suggest_reviewer: SuggestReviewer | None = None, denied: Denied | None = None
) -> tuple[str, ...]:
    """Every step that can be taken now. Work an agent can do comes before what waits for
    a person, so a pending approval for one task never hides the step of another; a task
    only a person can unblock (attempts used up, start denied) is not offered as work."""
    suffix = f" --run {state.run_id}"
    early = _before_tasks(state, suffix)
    if early:
        return early
    refused = dict(denied or {})
    steps = _task_steps(state, suggest_reviewer, suffix)
    exhausted = [t for t in _ids(state, (TaskStatus.BLOCKED,)) if progress.exhausted(state, t)]
    if progress.nothing_left(state):
        steps.append(f"wev run finish{suffix}")
    elif _startable_later(state, {*exhausted, *refused}):
        steps.append(f"wev task next{suffix}")
    steps += [reopen_step(state, tid) for tid in exhausted]
    steps += [denied_step(state, tid, approval) for tid, approval in refused.items()]
    return tuple(dict.fromkeys(steps)) or (f"wev run report{suffix}",)


def next_step(
    state: RunState, suggest_reviewer: SuggestReviewer | None = None, denied: Denied | None = None
) -> str:
    """The first of ``next_steps``."""
    return next_steps(state, suggest_reviewer, denied)[0]
