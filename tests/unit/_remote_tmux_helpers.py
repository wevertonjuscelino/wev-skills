"""Shared setup for the tmux controller tests and the ``wev remote`` command tests."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fixtures.fake_remote import FakeGate, FakeRemoteHost, make_controller
from tests.fixtures.operator_prompt import at_terminal
from wev_skills import cli
from wev_skills.commands import remote as remote_cmd
from wev_skills.config import RemoteHost, config_digest, parse_config
from wev_skills.core import active, wiring
from wev_skills.core.contracts import (
    Classification,
    Complexity,
    Mode,
    Plan,
    PlanTask,
    RiskLevel,
)
from wev_skills.governance.approvals import ApprovalStore
from wev_skills.remote.session import (
    RemoteRun,
    owner_token,
    session_name,
)
from wev_skills.state import model
from wev_skills.state.store import StateStore, run_dir

STAGING = RemoteHost("staging-1", "staging", True)
ARGV = ("pytest", "-q", "tests/unit")
NAME = session_name("T-1", "staging-1")
TOKEN = owner_token("T-1", "staging-1")
STEM = f".wev/remote/{NAME}.{TOKEN[5:]}"
HOSTS = [
    {"alias": "staging-1", "environment": "staging", "allow_mutating": True},
    {"alias": "prod-1", "environment": "production", "allow_mutating": False},
]
RUN_ID = "run-1"
REMOTE_AGENT = "remote-ops"
LOCAL_AGENT = "senior-engineer"
Reply = tuple[int, dict[str, Any], dict[str, Any]]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.host = FakeRemoteHost()
        self.gate = FakeGate()
        self.ctl = make_controller(self.host, (STAGING,), self.gate)

    def start(self, **kwargs: object) -> RemoteRun:
        return self.ctl.start(  # type: ignore[arg-type]
            "staging-1", "T-1", ARGV, Mode.EXECUTE, RiskLevel.LOW, **kwargs
        )


class CliBase(unittest.TestCase):
    """``wev`` run from a temporary directory against the fake host, an operator at a terminal.

    Without ``make_run`` no run is active and ``--config`` names a file with the inventory.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.repo)
        self.state_dir = self.tmp / "state"
        self.config: str | None = str(self.tmp / "config.json")
        document = {"state_dir": str(self.state_dir), "remote": {"hosts": HOSTS}}
        Path(self.config).write_text(json.dumps(document), encoding="utf-8")
        self.host = FakeRemoteHost()
        runner = mock.patch.object(remote_cmd, "_default_runner", lambda: self.host)
        for patcher in (runner, at_terminal()):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_run(
        self,
        mode: Mode = Mode.EXECUTE,
        agent: str = REMOTE_AGENT,
        risk: RiskLevel = RiskLevel.LOW,
    ) -> StateStore:
        """An active run in the working directory that pins the inventory, with task T-1."""
        pinned = parse_config(None, {"remote": {"hosts": HOSTS}})
        self.state_dir = self.repo / ".wev"
        store = StateStore(run_dir(self.state_dir, RUN_ID))
        store.create("objective", mode, RUN_ID, pinned.to_dict(), config_digest(pinned), "test")
        active.register_run(self.repo, self.state_dir, RUN_ID)
        level = Classification(Complexity.SIMPLE, risk, 0.0, False, (), "test")
        plan = Plan("objective", (PlanTask("T-1", "remote check", "run it"),))

        def prepare(state: model.RunState) -> model.RunState:
            planned = model.with_plan(model.with_classification(state, level), plan)
            record = dataclasses.replace(planned.tasks["T-1"], agent_id=agent)
            return dataclasses.replace(planned, tasks={**planned.tasks, "T-1": record})

        store.update(prepare)
        self.config = None
        return store

    def main(self, *argv: str) -> Reply:
        out, err = io.StringIO(), io.StringIO()
        config = [] if self.config is None else ["--config", self.config]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--lang", "en", *config, *argv])
        stdout = json.loads(out.getvalue()) if out.getvalue().strip() else {}
        stderr = json.loads(err.getvalue()) if err.getvalue().strip() else {}
        return code, stdout, stderr

    def run_cli(self, *argv: str) -> Reply:
        return self.main("remote", *argv)

    def grant(self, *action: str) -> None:
        """Request one exact action through the CLI and grant it as the scripted operator.

        ``approval request`` binds the request to the working directory, which is what a
        local command needs; a remote start asks for (and spends) a grant without one.
        """
        code, request, _ = self.main(
            "approval", "request", "--risk", "high", "--reason", "test", "--", *action
        )
        self.assertEqual(code, 0)
        self.grant_id(request["id"])

    def grant_id(self, approval_id: str) -> None:
        """Grant, as the scripted operator, the approval a refused start asked for."""
        code, _, err = self.main("approval", "grant", approval_id)
        self.assertEqual((code, err), (0, {}))

    def grant_remote(self, *action: str) -> None:
        """File ``<alias> <command>`` the way the controller does, then grant it by id."""
        store = ApprovalStore(self.state_dir / wiring.APPROVALS_FILE)
        self.grant_id(store.request(action, RiskLevel.HIGH, "test", "test").id)
