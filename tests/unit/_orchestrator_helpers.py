"""Shared fixtures for the orchestrator tests: a scripted runner, a ticking clock, three agents.

The runner is a stand-in, not evidence about git or any real command: it answers the few
git queries the engine sends from attributes a test sets, and every other argv from a script.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.unit._agent_helpers import make
from wev_skills import i18n
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.config import load_config
from wev_skills.core import shown_lessons, wiring
from wev_skills.core.contracts import Mode, RawCommandResult, TaskSignals, TaskStatus
from wev_skills.core.orchestrator import Orchestrator
from wev_skills.state.store import StateStore, run_dir

RUN_ID = "run-1"
DOER = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True}
READER = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": False}


class TickClock:
    """Each reading is one second after the previous one, so timestamps are ordered."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.value = start

    def now(self) -> float:
        self.value += 1.0
        return self.value


class FakeRunner:
    def __init__(self, root: str) -> None:
        self.root = root
        self.is_repo = True
        self.head = "abc123"
        self.branch = "main"
        self.porcelain = ""
        self.diff = ""
        self.script: dict[tuple[str, ...], tuple[int | None, str, str]] = {}
        self.calls: list[tuple[str, ...]] = []

    def on(
        self, argv: Sequence[str], exit_code: int | None = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        self.script[tuple(argv)] = (exit_code, stdout, stderr)

    def commands(self) -> list[tuple[str, ...]]:
        return [call for call in self.calls if call[0] != "git"]

    def _git(self, args: tuple[str, ...]) -> tuple[int | None, str, str]:
        if not self.is_repo:
            return 128, "", "fatal: not a git repository"
        answers = {
            ("rev-parse", "--show-toplevel"): self.root,
            ("rev-parse", "HEAD"): self.head,
            ("branch", "--show-current"): self.branch,
            ("status", "--porcelain"): self.porcelain,
        }
        if args[1:2] == ("diff",):
            return 0, "" if "--cached" in args else self.diff, ""
        return 0, answers.get(args[1:], ""), ""

    def edit(self, note: str = "") -> None:
        """Simulate work on the tree: the diff the fake git reports changes."""
        self.edits = getattr(self, "edits", 0) + 1
        self.diff = f"edit {self.edits} {note}".strip()

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RawCommandResult:
        args = tuple(argv)
        self.calls.append(args)
        code, out, err = self._git(args) if args[0] == "git" else self.script.get(args, (0, "", ""))
        return RawCommandResult(args, code, out, err, 5, timed_out=code is None)


def catalog() -> wiring.AgentCatalog:
    """builder and fixer may change files; reviewer is read-only and reviews."""
    specs = [
        make(
            "builder",
            specialties=["implementation"],
            model="standard",
            permissions=DOER,
            tools={"allow": ["Read", "Edit", "Bash"]},
        ),
        make(
            "fixer", specialties=["debugging"], permissions=DOER, tools={"allow": ["Read", "Edit"]}
        ),
        make("reviewer", specialties=["review"], permissions=READER, tools={"allow": ["Read"]}),
    ]
    registry = AgentRegistry(specs)
    return wiring.AgentCatalog(registry, AgentFactory(registry), frozenset())


class OrchestratorCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.runner = FakeRunner(str(self.root))
        self.clock = TickClock()
        self.overrides: dict[str, Any] = {}
        # A discoverable check: a run that needs no plan still needs something to verify with.
        (self.root / "Makefile").write_text("test:\n\t@true\n", encoding="utf-8")
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)

    def services(self) -> wiring.Services:
        config = load_config(None, self.overrides)
        built = wiring.build_services(config, self.root, self.runner, self.clock)
        return replace(built, agents=catalog())

    def orch(self, run_id: str = RUN_ID) -> Orchestrator:
        """A fresh orchestrator per call: nothing may survive between calls but the state."""
        services = self.services()
        store = StateStore(run_dir(services.state_dir, run_id), services.clock)
        return Orchestrator(store, services)

    def start(
        self, objective: str = "Add a greeting", mode: Mode = Mode.AUTO, **signals: Any
    ) -> dict[str, Any]:
        fields = {"files_touched_estimate": 1, **signals}
        return self.orch().start(objective, mode, TaskSignals(objective, **fields), RUN_ID)

    def plan_file(self, *tasks: dict[str, Any], objective: str = "Do the work") -> str:
        path = self.root / "plan.json"
        filled = [{"title": t["id"], "objective": f"do {t['id']}", **t} for t in tasks]
        path.write_text(json.dumps({"objective": objective, "tasks": filled}), encoding="utf-8")
        return str(path)

    def set_plan(self, *tasks: dict[str, Any]) -> dict[str, Any]:
        return self.orch().set_plan(self.plan_file(*tasks))

    def state(self) -> Any:
        return self.orch().load()

    def evidence_file(self, name: str, text: str = "seen\n") -> str:
        """A file in the run's evidence directory: a place manual evidence may point at."""
        path = self.orch().store.run_dir / "evidence" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return str(path)

    def lessons_shown(self, task_id: str = "task-1") -> tuple[str, ...]:
        """What the task's committed starts recorded in the run's ``events.jsonl``."""
        orchestrator = self.orch()
        record = orchestrator.load().tasks[task_id]
        records = shown_lessons.by_task(orchestrator.store.events()).get(task_id, ())
        return shown_lessons.for_task(records, record.agent_id, record.lessons_shown)

    def status_of(self, task_id: str) -> TaskStatus:
        status: TaskStatus = self.state().tasks[task_id].status
        return status

    def audit_types(self) -> list[str]:
        return [event["type"] for event in self.services().audit.read()]

    def grant(self, approval_id: str) -> None:
        self.services().approvals.grant(approval_id, "ana")

    def run_task(self, task_id: str = "task-1", work: bool = True) -> None:
        """next + start for a task that needs no approval, then (by default) some work:
        checks that passed before the task and an unchanged tree would verify nothing."""
        self.orch().next_tasks()
        self.orch().start_task(task_id)
        if work:
            self.runner.edit(task_id)

    def verify(self, task_id: str = "task-1", work: bool = True) -> None:
        """Some work, then check + record verified for a running task whose checks pass."""
        if work:
            self.runner.edit(task_id)
        self.orch().check_task(task_id)
        self.orch().record_task(task_id, TaskStatus.VERIFIED, "done")
