"""Eval task fixtures: a scenario plus the scripted trajectory the agent replays."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wev_skills import i18n, schema
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import Plan, PlanTask, TaskSignals
from wev_skills.core.errors import NotFound, ValidationError

SCHEMA_NAME = "eval-task"
CATEGORIES = (
    "simple-fix",
    "multi-file-feature",
    "failing-test",
    "context-overload",
    "agent-loop",
    "remote-diagnosis",
    "tool-selection",
)
CONTEXT_KINDS = frozenset({"tool_output", "note", "requirement", "decision"})
"""Step kinds that always add an item to the context and therefore need ``tokens``."""
OUTCOME_KINDS = frozenset({"command", "verify"})
REPEATABLE_KINDS = frozenset({"command", "handoff"})
OUTCOME_PASS = "pass"
OUTCOME_FAIL = "fail"

EVALS_DIR = Path(__file__).resolve().parents[3] / "evals"
"""``evals/`` at the repository root; absent when the package is installed without the repo."""
TASKS_SUBDIR = "tasks"
CONFIGS_FILE = Path("baselines") / "configs.json"


@dataclass(frozen=True)
class Criterion(Serializable):
    id: str
    text: str


@dataclass(frozen=True)
class Subtask(Serializable):
    id: str
    depends_on: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    objective: str = ""
    """What this subtask is for; tool selection reads it. Empty: the task's objective."""
    read_only: bool = False


@dataclass(frozen=True)
class Conditions(Serializable):
    """Mechanical rules that turn a step into a failure under some configurations."""

    requires_verbatim: tuple[str, ...] = ()
    pass_from_attempt: int = 1
    min_tier: str = ""


@dataclass(frozen=True)
class Step(Serializable):
    id: str
    subtask: str
    kind: str
    description: str = ""
    tokens: int = 0
    needed_later: bool = False
    signature: str = ""
    outcome: str = OUTCOME_PASS
    repeat: int = 1
    polling: bool = False
    flaky: bool = False
    criteria: tuple[str, ...] = ()
    from_agent: str = ""
    to_agent: str = ""
    needs_tool: str = ""
    """The tool this step stands for; checked only when tool selection is on."""
    conditions: Conditions = field(default_factory=Conditions)


@dataclass(frozen=True)
class EvalTask(Serializable):
    id: str
    title: str
    category: str
    signals: TaskSignals
    window_tokens: int
    acceptance_criteria: tuple[Criterion, ...]
    subtasks: tuple[Subtask, ...]
    script: tuple[Step, ...]
    description: str = ""

    def steps_for(self, subtask_id: str) -> tuple[Step, ...]:
        """The steps of one subtask, in script order."""
        return tuple(step for step in self.script if step.subtask == subtask_id)

    def plan(self) -> Plan:
        """The subtasks as a ``Plan``, so ordering uses the engine's own dependency rules."""
        tasks = tuple(
            PlanTask(sub.id, sub.id, self.signals.objective, sub.depends_on, sub.files)
            for sub in self.subtasks
        )
        return Plan(self.signals.objective, tasks)


def _duplicates(ids: Sequence[str]) -> list[str]:
    return sorted({item for item in ids if ids.count(item) > 1})


def _structure_problems(task: EvalTask) -> list[str]:
    found = [
        i18n.t("evaluation.task.duplicate", what=what, ids=", ".join(dups))
        for what, ids in (
            ("subtask", [s.id for s in task.subtasks]),
            ("step", [s.id for s in task.script]),
            ("criterion", [c.id for c in task.acceptance_criteria]),
        )
        if (dups := _duplicates(ids))
    ]
    found.extend(task.plan().problems())
    known = {sub.id for sub in task.subtasks}
    found.extend(
        i18n.t("evaluation.task.unknown_subtask", step=step.id, subtask=step.subtask)
        for step in task.script
        if step.subtask not in known
    )
    scripted = {step.subtask for step in task.script}
    found.extend(
        i18n.t("evaluation.task.empty_subtask", subtask=sub.id)
        for sub in task.subtasks
        if sub.id not in scripted
    )
    return found


def _kind_problems(step: Step) -> list[str]:
    rules = (
        (step.kind in CONTEXT_KINDS and step.tokens <= 0, "evaluation.task.needs_tokens"),
        (step.kind in OUTCOME_KINDS and not step.signature, "evaluation.task.needs_signature"),
        (step.kind == "verify" and not step.criteria, "evaluation.task.needs_criteria"),
        (step.kind != "verify" and bool(step.criteria), "evaluation.task.criteria_not_verify"),
        (
            step.kind == "handoff" and not (step.from_agent and step.to_agent),
            "evaluation.task.needs_agents",
        ),
        (
            step.kind not in OUTCOME_KINDS and step.outcome != OUTCOME_PASS,
            "evaluation.task.outcome_not_allowed",
        ),
        (
            step.kind not in REPEATABLE_KINDS and step.repeat != 1,
            "evaluation.task.repeat_not_allowed",
        ),
        (
            step.kind != "command" and (step.polling or step.flaky),
            "evaluation.task.flags_not_command",
        ),
        (step.needed_later and step.tokens <= 0, "evaluation.task.needed_without_tokens"),
    )
    return [i18n.t(key, step=step.id, kind=step.kind) for hit, key in rules if hit]


def _criteria_problems(task: EvalTask) -> list[str]:
    known = {criterion.id for criterion in task.acceptance_criteria}
    verified = {cid for step in task.script for cid in step.criteria}
    found = [
        i18n.t("evaluation.task.unknown_criterion", step=step.id, criterion=cid)
        for step in task.script
        for cid in step.criteria
        if cid not in known
    ]
    found.extend(
        i18n.t("evaluation.task.unverified_criterion", criterion=cid)
        for cid in sorted(known - verified)
    )
    return found


def _dependency_problems(task: EvalTask) -> list[str]:
    """``requires_verbatim`` must name an earlier ``needed_later`` step of the same subtask."""
    found: list[str] = []
    for sub in task.subtasks:
        earlier: dict[str, Step] = {}
        used: set[str] = set()
        for step in task.steps_for(sub.id):
            for required in step.conditions.requires_verbatim:
                source = earlier.get(required)
                if source is None or not source.needed_later:
                    found.append(
                        i18n.t("evaluation.task.bad_requirement", step=step.id, item=required)
                    )
                used.add(required)
            earlier[step.id] = step
        found.extend(
            i18n.t("evaluation.task.unused_needed", step=step_id)
            for step_id, step in earlier.items()
            if step.needed_later and step_id not in used
        )
    return found


def task_problems(task: EvalTask) -> list[str]:
    """Every semantic problem in a schema-valid task (empty when it is consistent)."""
    found = _structure_problems(task)
    for step in task.script:
        found.extend(_kind_problems(step))
    found.extend(_criteria_problems(task))
    found.extend(_dependency_problems(task))
    return found


def parse_task(data: Any, source: str = "<memory>") -> EvalTask:
    """Validate ``data`` against the schema and the semantic rules, then build the task."""
    schema.validate_or_raise(data, schema.load(SCHEMA_NAME), what=f"eval task {source}")
    task = EvalTask.from_dict(data)
    problems = task_problems(task)
    if problems:
        raise ValidationError(
            "invalid_eval_task",
            i18n.t("evaluation.error.invalid_task", source=source, first=problems[0]),
            {"errors": problems, "path": source},
        )
    return task


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise NotFound(
            "file_not_found",
            i18n.t("evaluation.error.file_not_found", path=str(path)),
            {"path": str(path)},
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "file_unreadable",
            i18n.t("evaluation.error.file_unreadable", path=str(path), error=str(exc)),
            {"path": str(path)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "invalid_json",
            i18n.t("evaluation.error.invalid_json", path=str(path), error=str(exc)),
            {"path": str(path)},
        ) from exc


def load_task(path: str | Path) -> EvalTask:
    file = Path(path)
    return parse_task(read_json(file), source=str(file))


def load_tasks(directory: str | Path) -> tuple[EvalTask, ...]:
    """Every ``*.json`` task in ``directory``, sorted by file name; ids must be unique."""
    root = Path(directory)
    if not root.is_dir():
        raise NotFound(
            "tasks_dir_not_found",
            i18n.t("evaluation.error.tasks_dir", path=str(root)),
            {"path": str(root)},
        )
    tasks = tuple(load_task(path) for path in sorted(root.glob("*.json")))
    if not tasks:
        raise NotFound(
            "no_eval_tasks",
            i18n.t("evaluation.error.no_tasks", path=str(root)),
            {"path": str(root)},
        )
    dups = _duplicates([task.id for task in tasks])
    if dups:
        raise ValidationError(
            "duplicate_eval_task",
            i18n.t("evaluation.task.duplicate", what="task", ids=", ".join(dups)),
            {"ids": dups},
        )
    return tasks


def resolve_evals_dir(root: str | Path | None = None) -> Path:
    """The ``evals/`` directory, or ``NotFound`` when the package runs without the repo."""
    path = Path(root) if root is not None else EVALS_DIR
    if not path.is_dir():
        raise NotFound(
            "evals_dir_not_found",
            i18n.t("evaluation.error.evals_dir", path=str(path)),
            {"path": str(path)},
        )
    return path
