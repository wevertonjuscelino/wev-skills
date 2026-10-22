"""codex: install into Codex and run `codex exec` with YOUR real Codex login and tokens, in an
isolated HOME (`.wev/e2e-home/`). Spends a Codex account.

Label: implemented but untested: never run against a real harness in this change. What a hook
line looks like in `codex exec` output is not observed, so that check only looks for "hook"."""

from __future__ import annotations

import json
import os
import unittest

from tests.e2e import _core, _person
from tests.e2e._support import FixedTree, run
from wev_skills import __version__

SCENARIO = "codex"
PROMPT = "print the wev version with the wev skill"


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=codex (make e2e)")
class Codex(_person.PersonChecks):
    scenario = SCENARIO
    needs = "codex"
    exec_output = ""

    @classmethod
    def intro(cls, tree: FixedTree) -> str:
        return (
            "This scenario uses YOUR real Codex login and spends tokens. The login must exist\n"
            "in the isolated HOME (nothing is copied from your real one). Once, in a shell:\n"
            f"{_person.exports(tree)}\n  codex login"
        )

    @_core.named("installer --harness codex exits 0")
    def test_01_install(self) -> None:
        done, cmd = self.installer("codex")
        ok = done.exit == 0 and "Finished with" not in done.output
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("codex exec runs the wev skill (the version is in the output)")
    def test_02_exec(self) -> None:
        self.ask_again(
            "In the isolated shell: run the `codex mcp add` line the installer printed (it is in\n"
            "the report detail of the previous check), then run `codex` once in any git repo,\n"
            "review and trust the wev hooks when Codex asks, and exit."
        )
        repo = _person.throwaway_repo(self.fixed)
        argv = ["codex", "exec", "--skip-git-repo-check", "-C", str(repo), PROMPT]
        done = run(argv, 900, self.local.env(), repo)
        type(self).exec_output = done.output
        ok = done.exit == 0 and __version__ in done.output
        self.record("codex exec <prompt>", done.exit, ok, done.output)

    @_core.named("a hook line appears in the codex exec output")
    def test_03_hook_line(self) -> None:
        self.record("grep -i hook codex-exec-output", None, "hook" in self.exec_output.lower())

    @_core.named("codex mcp list shows rea")
    def test_04_mcp_list(self) -> None:
        done = run(["codex", "mcp", "list", "--json"], 120, self.local.env())
        try:
            names = [str(s.get("name")) for s in json.loads(done.output) if isinstance(s, dict)]
        except ValueError, TypeError:
            names = []
        self.record("codex mcp list --json", done.exit, "rea" in names, done.output)


if __name__ == "__main__":
    unittest.main()
