"""Shared builders for the agents tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import AgentSpec


def data(agent_id: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema_version": 1,
        "id": agent_id,
        "name": agent_id.title(),
        "description": f"The {agent_id} agent.",
    }
    base.update(fields)
    return base


def make(agent_id: str, **fields: Any) -> AgentSpec:
    return AgentSpec.from_dict(data(agent_id, **fields))


def factory_for(*specs: AgentSpec) -> AgentFactory:
    registry = AgentRegistry()
    for spec in specs:
        registry = registry.register(spec)
    return AgentFactory(registry)


def run(*argv: str) -> tuple[int, Any, str]:
    """Run the CLI in-process; ``cli`` is imported late so spec tests do not depend on it."""
    from wev_skills import cli

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None), err.getvalue()


class RepoCase(unittest.TestCase):
    """Runs each test inside a temporary repository root: the commands write only there.

    The root sits one level below the temporary directory, so a write that escapes it by
    ``..`` still lands in a directory that is removed after the test.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve() / "repo"
        (self.tmp / ".git").mkdir(parents=True)
        previous = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, previous)

    def write(self, name: str, doc: object) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path
