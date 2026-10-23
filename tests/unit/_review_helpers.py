"""Shared by the review tests: a real git repository, a run started in it, scripted replies."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.unit._orchestrator_helpers import RUN_ID, TickClock, catalog
from wev_skills import i18n
from wev_skills.config import load_config
from wev_skills.core import wiring
from wev_skills.core.contracts import Mode, TaskSignals
from wev_skills.core.orchestrator import Orchestrator
from wev_skills.core.ports import SubprocessRunner
from wev_skills.state.store import StateStore, run_dir

LINES = 30


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", *args),
        cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip


def item(line: int = 5, title: str = "Off by one", file: str = "a.py", tag: str = "important"):
    return {"file": file, "line": line, "title": title, "body": "It is wrong.", "tag": tag,
            "class_wide": False}  # fmt: skip


def found(*items: dict[str, object]) -> str:
    return json.dumps({"findings": list(items)})


def vote(index: int, real: bool = True, kind: str = "bug", tag: str = "important"):
    return {"index": index, "real": real, "tag": tag, "kind": kind}


def votes(*items: dict[str, object]) -> str:
    return json.dumps({"votes": list(items)})


class ReviewRepo(unittest.TestCase):
    """A repository with ``a.py``, an engine whose review is ``quick`` with agent ``reviewer``."""

    review: dict[str, Any] = {"agent": "reviewer", "depth": "quick"}

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text(".wev/\nstate/\n")
        (self.root / "Makefile").write_text("test:\n\t@true\n")
        self.write("a.py", "".join(f"x{n} = {n}\n" for n in range(1, LINES + 1)))
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "one")
        language = i18n.use_language("en")
        language.__enter__()
        self.addCleanup(language.__exit__, None, None, None)
        self.overrides: dict[str, Any] = {"review": dict(self.review)}

    def write(self, name: str, text: str) -> None:
        (self.root / name).write_text(text)

    def edit(self, line: int, text: str, name: str = "a.py") -> None:
        rows = (self.root / name).read_text().splitlines(keepends=True)
        rows[line - 1] = text + "\n"
        self.write(name, "".join(rows))

    def orch(self) -> Orchestrator:
        config = load_config(None, self.overrides)
        services = wiring.build_services(config, self.root, SubprocessRunner(), TickClock())
        services = replace(services, agents=catalog())
        return Orchestrator(
            StateStore(run_dir(services.state_dir, RUN_ID), services.clock), services
        )

    def start(self) -> None:
        signals = TaskSignals("Add a greeting", files_touched_estimate=1)
        self.orch().start("Add a greeting", Mode.AUTO, signals, RUN_ID)
