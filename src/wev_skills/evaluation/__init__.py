"""Deterministic evaluation harness driven by a scripted agent.

Scope, stated plainly: this package replays fixed trajectories against the real context
manager, guard, model router and local decision policy. It shows that those components behave
as designed under controlled trajectories. It calls no model, so it cannot measure how any
model performs, and its cost and duration figures are simulated units, not money or time.
"""

from __future__ import annotations

from wev_skills.evaluation.agent import ScriptedAgent
from wev_skills.evaluation.configs import (
    SIMULATED_PRICE_PER_TOKEN,
    HarnessConfig,
    StubSummarizer,
    load_configs,
    parse_configs,
)
from wev_skills.evaluation.harness import run, run_in_order, run_one, schedule
from wev_skills.evaluation.metrics import (
    ConfigAggregate,
    Counts,
    EvalReport,
    RunResult,
    SubtaskOutcome,
)
from wev_skills.evaluation.report import notice, render_json, render_markdown, to_document
from wev_skills.evaluation.tasks import (
    EvalTask,
    load_task,
    load_tasks,
    parse_task,
    resolve_evals_dir,
)

__all__ = [
    "SIMULATED_PRICE_PER_TOKEN",
    "ConfigAggregate",
    "Counts",
    "EvalReport",
    "EvalTask",
    "HarnessConfig",
    "RunResult",
    "ScriptedAgent",
    "StubSummarizer",
    "SubtaskOutcome",
    "load_configs",
    "load_task",
    "load_tasks",
    "notice",
    "parse_configs",
    "parse_task",
    "render_json",
    "render_markdown",
    "resolve_evals_dir",
    "run",
    "run_in_order",
    "run_one",
    "schedule",
    "to_document",
]
