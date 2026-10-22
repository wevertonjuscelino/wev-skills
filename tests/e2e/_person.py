"""What the scenarios that need a person, an account or a CLI share: the CLI probe, the pause
for Enter on /dev/tty (the runner's own tty helper), the persistent isolated HOME, and a
throwaway git repository."""

from __future__ import annotations

import importlib.util
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TextIO

from tests.e2e import _core
from tests.e2e._support import ROOT, Done, FixedTree
from tests.e2e.test_macos_core import LocalHost

NO_TTY = "needs a person at the terminal"


def _runner_open_tty() -> TextIO | None:
    spec = importlib.util.spec_from_file_location("wev_e2e_runner", ROOT / "scripts" / "e2e.py")
    assert spec and spec.loader  # noqa: S101 - the file is in this repository
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("wev_e2e_runner", module)
    spec.loader.exec_module(module)
    handle: TextIO | None = module.open_tty()
    return handle


def await_person(step: str) -> str | None:
    """Print `step` on the terminal and wait for Enter. None when the person pressed Enter,
    else the reason the scenario cannot go on."""
    tty = _runner_open_tty()
    if tty is None:
        return NO_TTY
    with tty:
        tty.write(f"\n{step}\n\nPress Enter when done (Ctrl-C stops): ")
        tty.flush()
        return None if tty.readline() else NO_TTY


def exports(tree: FixedTree) -> str:
    """The lines that put a shell in the isolated HOME, for the person to paste."""
    pairs = (
        ("HOME", tree.home),
        ("XDG_CONFIG_HOME", tree.config),
        ("XDG_DATA_HOME", tree.data),
        ("XDG_STATE_HOME", tree.state),
    )
    return "\n".join(f"  export {k}={shlex.quote(str(v))}" for k, v in pairs)


def throwaway_repo(tree: FixedTree) -> Path:
    repo = tree.root / "repo"
    repo.mkdir(exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)  # noqa: S607 - fixed argv
    return repo


class PersonChecks(_core.Checks):
    """A scenario that may need a CLI and a person. `needs` names the CLI (or None); `intro`
    says what the person must do before the checks start."""

    needs: str | None = None
    local: LocalHost
    fixed: FixedTree

    @classmethod
    def intro(cls, tree: FixedTree) -> str:
        raise NotImplementedError

    @classmethod
    def setUpClass(cls) -> None:
        if cls.needs and shutil.which(cls.needs) is None:
            cls.blocked = f"{cls.needs} not installed"
            return
        cls.fixed = FixedTree()
        cls.blocked = await_person(cls.intro(cls.fixed))
        if cls.blocked:
            return
        cls.local = LocalHost(cls.fixed)
        cls.host = cls.local

    def ask_again(self, step: str) -> None:
        """A second pause in the middle of a scenario; skips the check without a person."""
        reason = await_person(step)
        if reason:
            self.skip("", reason)

    def installer(self, harness: str) -> tuple[Done, str]:
        args = ["--yes", "--lang", "en", "--source", self.host.source, "--harness", harness]
        return self.install_sh(*args, "--no-jev", "--rea-mode", "direct")
