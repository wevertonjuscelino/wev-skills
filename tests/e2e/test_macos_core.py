"""macos-core: the installer, rea, update, rollback and uninstall for real on this Mac, in an
isolated HOME. Spends network only (npm registry, GitHub releases), no account."""

from __future__ import annotations

import os
import sys
import unittest
from collections.abc import Sequence

from tests.e2e import _core
from tests.e2e._support import ROOT, Done, Tree, mcp_tool_count, run

SCENARIO = "macos-core"
WEV = ROOT / "bin" / "wev"
INSTALLER = ROOT / "install.sh"


class LocalHost:
    """This Mac, with HOME and the XDG roots inside a temporary tree."""

    def __init__(self) -> None:
        self.tree: Tree | None = Tree()
        self._tree = self.tree
        self.source = str(ROOT)

    def cleanup(self) -> None:
        self._tree.cleanup()

    def run_wev(self, args: Sequence[str], timeout: float) -> Done:
        return run([sys.executable, str(WEV), *args], timeout, self._tree.env())

    def run_install(self, args: Sequence[str], timeout: float) -> Done:
        return run(["bash", str(INSTALLER), *args], timeout, self._tree.env())

    def tool_count(self, timeout: float) -> int:
        argv = [sys.executable, str(WEV), "rea", "serve"]
        return mcp_tool_count(argv, self._tree.env(), timeout)

    def home_entries(self) -> frozenset[str]:
        return self._tree.listing()

    def exists(self, what: str) -> bool:
        if what.startswith("home:"):
            return (self._tree.home / what[5:]).exists()
        base = self._tree.data if what == "data" else self._tree.config
        return (base / "wev-skills").exists()

    def state_file(self) -> str:
        return str(self._tree.data / "wev-skills" / "third-party" / "state.json")

    def read_state(self) -> str:
        with open(self.state_file(), encoding="utf-8") as handle:
            return handle.read()

    def write_state(self, text: str) -> None:
        with open(self.state_file(), "w", encoding="utf-8") as handle:
            handle.write(text)


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=macos-core (make e2e)")
class MacosCore(_core.CoreChecks):
    scenario = SCENARIO
    local: LocalHost

    @classmethod
    def setUpClass(cls) -> None:
        cls.local = LocalHost()
        cls.host = cls.local
        cls.before = cls.host.home_entries()
        cls.registry = _core.fetch_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.local.cleanup()


if __name__ == "__main__":
    unittest.main()
