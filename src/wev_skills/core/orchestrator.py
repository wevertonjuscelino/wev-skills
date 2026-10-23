"""The orchestrator: one validated transition per method, over a ``StateStore``.

Flow: REQUEST, DISCOVER, CLASSIFY, PLAN, DECIDE, EXECUTE, VERIFY, REVIEW, DELIVER. The
model reasons and edits; these methods keep the record and refuse what the rules forbid.
Task-level operations live in ``task_flow``, ``task_exec`` and ``task_outcomes``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.config_review import DEPTH_OFF
from wev_skills.core import (
    active,
    brief,
    fsutil,
    guard_ack,
    plan_flow,
    plan_warnings,
    planning,
    progress,
    report,
    review_cap,
    run_start,
    task_check,
    task_exec,
    task_flow,
    task_outcomes,
    task_reopen,
    tool_select,
)
from wev_skills.core.contracts import Evidence, Mode, Plan, TaskSignals, TaskStatus
from wev_skills.core.engine import Engine, restamp_started
from wev_skills.core.errors import StateConflict, WevError
from wev_skills.core.run_start import START_MODES
from wev_skills.evaluation.scoring import SCORES_FILE
from wev_skills.guards.execution import GuardVerdict
from wev_skills.review.changed import changed_paths
from wev_skills.review.gate import (
    config_weakened,
    current_config,
    finish_refusal,
    read_comparisons,
)
from wev_skills.review.trees import write_tree
from wev_skills.state.model import Phase, RunState, with_decision, with_phase, with_repo
from wev_skills.state.resume import check_drift

__all__ = ["START_MODES", "Orchestrator"]

TREE = "tree-check"
"""Source of the decision ``run finish`` records: which tasks changed after verification."""
FINISH = "wev run finish"


class Orchestrator(Engine):
    # -- run level ----------------------------------------------------------

    def start(
        self, objective: str, mode: Mode, signals: TaskSignals, run_id: str | None = None
    ) -> dict[str, Any]:
        """REQUEST to DECIDE; see ``run_start.start``. Refused while another run is active."""
        return run_start.start(self, objective, mode, signals, run_id)

    def status(self) -> dict[str, Any]:
        state = self.reconciled(self.load())
        verdict = self.run_verdict(state)
        return {
            "run_id": state.run_id,
            "objective": state.objective,
            "mode": state.mode.value,
            "phase": state.phase.value,
            "tasks": report.task_table(state),
            "pending_approvals": [note.id for note in progress.live_approvals(state)],
            "stale_approvals": [note.id for note in progress.stale_approvals(state)],
            "blockers": list(state.blockers),
            "guard": verdict.to_dict(),
            "config": {"source": state.config_source, "digest": state.config_digest},
            **self._steps(state, verdict),
        }

    def _steps(self, state: RunState, verdict: GuardVerdict) -> dict[str, Any]:
        """The step fields; a blocking guard verdict comes before everything else."""
        blocked = verdict.action in progress.BLOCKING_ACTIONS
        first = f"wev guard check --run {state.run_id}" if blocked else None
        return self.step_fields(state, first)

    def _step(self, state: RunState, verdict: GuardVerdict) -> str:
        step: str = self._steps(state, verdict)["next_step"]
        return step

    def resume(self) -> dict[str, Any]:
        """Compare the record with the real repository; never assume a running task finished."""
        state = self.load()
        root = self.cwd(state)
        drift = check_drift(state, self.services.runner, exclude=self.excluded(root))
        repo = self.snapshot(root)
        stamp = self.stamp()
        notes = drift.notes or (i18n.t("orch.resume.no_drift"),)
        text = i18n.t("orch.decision.resume", drifted=str(drift.drifted).lower())

        def change(current: RunState) -> RunState:
            moved = current
            for task_id in drift.stale_running_tasks:
                if moved.tasks[task_id].status is TaskStatus.RUNNING:
                    moved = restamp_started(moved, task_id, stamp)
            moved = with_repo(moved, repo) if repo is not None else moved
            return with_decision(moved, self.decision(moved.phase, text, notes, "resume"))

        after = self.commit(change, "run.resumed", {"drift": drift.to_dict()})
        return {
            "run_id": after.run_id,
            "drift": drift.to_dict(),
            "needs_reverification": list(drift.stale_running_tasks),
            **self.step_fields(after),
        }

    def guard_check(self, task_id: str | None = None) -> GuardVerdict:
        state = self.load()
        if task_id is None:
            return review_cap.run_guard_verdict(self, state)
        task = progress.plan_task(state, task_id)
        return progress.task_verdict(
            progress.guard_events(state, task_id),
            self.task_limits(state, task_id),
            self.now(),
            progress.unresolved_dependencies(state, task),
        )

    def acknowledge_guard(
        self, task_id: str | None, reason: str, operator: str, confirmation: str
    ) -> dict[str, Any]:
        """Clear a tripped guard on a person's say-so; see ``guard_ack.acknowledge``."""
        return guard_ack.acknowledge(self, task_id, reason, operator, confirmation)

    def brief(self, max_chars: int | None = None, lang: str | None = None) -> str:
        """The plan reminder for this run (see ``core.brief``). Read-only."""
        state = self.reconciled(self.load())
        limit = self.services.config.harness.plan_reminder_max_chars
        step = self._step(state, self.run_verdict(state))
        return brief.build_brief(state, step, limit if max_chars is None else max_chars, lang)

    def finish(self) -> dict[str, Any]:
        """Mark the run done, whatever its outcome, so it stops being the active run.

        The tree is compared once more with the last verified record; what changed after
        it is stored with the run, so the closed record is not judged by later work."""
        state = self.reconciled(self.load())
        if state.phase is not Phase.DONE:
            refusal = self._review_refusal(state)
            if refusal is not None:
                raise refusal
        changed = self._changed(state)
        complete = progress.run_complete(state) and not changed
        if state.phase is not Phase.DONE:
            outcome = i18n.t("orch.finish.complete" if complete else "orch.finish.incomplete")
            text = i18n.t("orch.decision.finished", outcome=outcome)
            check = self.decision(Phase.DONE, i18n.t("orch.decision.tree_check"), changed, TREE)

            def change(current: RunState) -> RunState:
                done = with_decision(with_phase(current, Phase.DONE), check)
                return with_decision(done, self.decision(Phase.DONE, text))

            state = self.commit(change, "run.finished", {"complete": complete, "changed": changed})
            self._unregister(state.run_id)
        return {
            "run_id": state.run_id,
            "phase": state.phase.value,
            "complete": complete,
            "changed_after_verification": list(changed),
            **self.step_fields(state),
        }

    def _review_refusal(self, state: RunState) -> WevError | None:
        config = self.services.config
        runner, root = self.services.runner, Path(self.cwd(state))
        changed: frozenset[str] = frozenset()
        weakened = False
        if config.review.depth != DEPTH_OFF:  # with review off this gate does no git work
            if state.base:
                changed = changed_paths(runner, root, state.base, write_tree(runner, root))
            weakened = config_weakened(config, current_config(state.config_source, root))
        comparisons = read_comparisons(self.services.state_dir / SCORES_FILE)
        return finish_refusal(
            state, config, self.fingerprint(state), changed, comparisons, weakened
        )

    def _changed(self, state: RunState) -> tuple[str, ...]:
        """Tasks that are "verified, then changed": computed now for an open run, read from
        the record of ``run finish`` for a closed one."""
        if state.phase is not Phase.DONE:
            return progress.changed_after_verification(state, self.fingerprint(state))
        checks = [d for d in state.decisions if d.source == TREE]
        return checks[-1].reasons if checks else ()

    def _unregister(self, run_id: str) -> None:
        """Drop the run from the per-user registry; a registry that cannot be written is
        reported in the audit log (a stale entry is harmless: readers check the state)."""
        try:
            active.unregister_run(self.services.state_dir, run_id)
        except (OSError, StateConflict) as exc:
            why = {"run_id": run_id, "why": type(exc).__name__}
            self.services.audit.append("registry.unavailable", why)

    def report(self, lang: str | None = None) -> dict[str, Any]:
        state = self.reconciled(self.load())
        approvals = [r.to_dict() for r in self.services.approvals.list()]
        verdict = self.run_verdict(state)
        changed = self._changed(state)
        built = report.build_report(state, approvals, verdict, lang, changed)
        fields = self._steps(state, verdict)
        if changed and state.phase is not Phase.DONE and fields["next_step"].startswith(FINISH):
            recheck = [f"wev task check {task_id} --run {state.run_id}" for task_id in changed]
            fields = {"next_step": recheck[0], "next_steps": [*recheck, *fields["next_steps"]]}
        return {**built, **fields}

    # -- plan ---------------------------------------------------------------

    def set_plan(self, path: str, amend_reason: str | None = None) -> dict[str, Any]:
        """Store a plan. ``amend_reason`` is what ``--amend --reason`` gives: without it a
        change to a started task's criteria, checks, files, risk or ``read_only`` is refused."""
        plan = planning.load_plan(path)
        state = self.retry(lambda: self.adopt_plan(plan, "plan.set", amend_reason))
        return {**self.show_plan(state), "warnings": plan_warnings.for_plan(self, state)}

    def show_plan(self, state: RunState | None = None) -> dict[str, Any]:
        current = state if state is not None else self.load()
        return {
            "run_id": current.run_id,
            "plan": current.plan.to_dict() if current.plan else None,
            "tasks": report.task_table(current),
            **self.step_fields(current),
        }

    def adopt_plan(self, plan: Plan, event: str, amend_reason: str | None = None) -> RunState:
        return plan_flow.adopt_plan(self, plan, event, amend_reason)

    # -- tasks --------------------------------------------------------------

    def next_tasks(self) -> dict[str, Any]:
        return self.retry(lambda: task_flow.next_tasks(self))

    def start_task(self, task_id: str) -> dict[str, Any]:
        with fsutil.locked(
            self.store.run_dir / "execution", self.services.config.limits.lock_timeout_seconds
        ):
            return self.retry(lambda: task_flow.start_task(self, task_id))

    def exec_command(
        self,
        argv: Sequence[str],
        task_id: str | None = None,
        timeout: float | None = None,
        polling: bool = False,
        flaky: bool = False,
    ) -> tuple[dict[str, Any], int]:
        with fsutil.locked(
            self.store.run_dir / "execution", self.services.config.limits.lock_timeout_seconds
        ):
            return task_exec.exec_command(self, argv, task_id, timeout, polling, flaky)

    def check_task(self, task_id: str, stop_on_failure: bool = True) -> dict[str, Any]:
        with fsutil.locked(
            self.store.run_dir / "execution", self.services.config.limits.lock_timeout_seconds
        ):
            return task_check.check_task(self, task_id, stop_on_failure)

    def record_task(
        self,
        task_id: str,
        status: TaskStatus,
        summary: str,
        changed_files: Sequence[str] = (),
        blockers: Sequence[str] = (),
        evidence: Sequence[Evidence] = (),
    ) -> dict[str, Any]:
        return self.retry(
            lambda: task_outcomes.record_task(
                self, task_id, status, summary, changed_files, blockers, evidence
            )
        )

    def review_task(
        self, task_id: str, reviewer: str, accepted: bool, summary: str
    ) -> dict[str, Any]:
        return self.retry(
            lambda: task_outcomes.review_task(self, task_id, reviewer, accepted, summary)
        )

    def restore_tool(self, task_id: str, tool: str, reason: str) -> dict[str, Any]:
        """Give a running task back a tool its selection dropped; see ``tool_select``."""
        return self.retry(lambda: tool_select.restore(self, task_id, tool, reason))

    def reopen_task(
        self, task_id: str, reason: str, operator: str, confirmation: str
    ) -> dict[str, Any]:
        """Human-only: reset a task's attempts and send it back to PENDING."""
        return self.retry(
            lambda: task_reopen.reopen_task(self, task_id, reason, operator, confirmation)
        )
