"""opencode: install into OpenCode and prove it loads the wev skills offline (`opencode debug
skill`, from docs/research/harness-opencode.md). OpenCode has no documented headless run, so that
check is skipped with the reason. Needs the CLI, which the owner installs first; without it every
check is skipped. Spends no account.

Label: implemented but untested: never run against a real harness in this change."""

from __future__ import annotations

import os
import unittest

from tests.e2e import _core, _person
from tests.e2e._support import FixedTree, run

SCENARIO = "opencode"


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=opencode (make e2e)")
class OpenCode(_person.PersonChecks):
    scenario = SCENARIO
    needs = "opencode"

    @classmethod
    def intro(cls, tree: FixedTree) -> str:
        return f"No account is used. The checks run in the isolated HOME:\n{_person.exports(tree)}"

    @_core.named("installer --harness opencode exits 0")
    def test_01_install(self) -> None:
        done, cmd = self.installer("opencode")
        ok = done.exit == 0 and "Finished with" not in done.output
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("opencode debug skill lists the wev skills")
    def test_02_skills_load(self) -> None:
        done = run(["opencode", "debug", "skill"], 120, self.local.env())
        self.record("opencode debug skill", done.exit, "wev" in done.output, done.output)

    @_core.named("a headless opencode run uses the wev skill")
    def test_03_headless(self) -> None:
        self.skip("", "the research found no OpenCode headless run (harness-opencode.md, 6)")


if __name__ == "__main__":
    unittest.main()
