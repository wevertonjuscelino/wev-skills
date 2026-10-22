"""linux-core: the macos-core checks inside a blank Linux container (python:3.14-slim, git, curl,
Node, a non-root user) with the clone mounted read-only at /src. Needs the Docker daemon;
without it every check is skipped. Spends network and one docker build, no account."""

from __future__ import annotations

import os
import unittest

from tests.e2e import _core, _docker

SCENARIO = "linux-core"


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=linux-core (make e2e)")
class LinuxCore(_core.CoreChecks):
    scenario = SCENARIO
    container: _docker.ContainerHost

    @classmethod
    def setUpClass(cls) -> None:
        cls.blocked = _docker.daemon_problem()
        if cls.blocked:
            return
        cls.container = _docker.ContainerHost(_docker.build_image())
        cls.host = cls.container
        cls.before = cls.host.home_entries()
        cls.registry = _core.fetch_registry()

    @classmethod
    def tearDownClass(cls) -> None:
        if not cls.blocked:
            cls.container.stop()

    @_core.named("installer's dependency check passes on a stock image")
    def test_01b_dependency_check_passes(self) -> None:
        self.need_install()
        out = type(self).last_install
        ok = "Cannot continue" not in out and "Summary" in out
        self.record("bash install.sh (dependency check)", None, ok, out)


if __name__ == "__main__":
    unittest.main()
