"""claude: install into Claude Code and run it headless with YOUR real Claude login and tokens,
in an isolated HOME (`.wev/e2e-home/`). Spends a Claude Code account.

Label: implemented but untested: never run against a real harness in this change. The shape of
`claude plugin list --json` and of the stream-json transcript is read from `claude --help`, not
observed, so the checks search for names instead of fields."""

from __future__ import annotations

import json
import os
import unittest

from tests.e2e import _core, _person
from tests.e2e._support import Done, FixedTree, run

SCENARIO = "claude"
PROMPT = "Run /wev-orchestrate with the objective: print the wev version"
TOOLS = "Bash,Read,Skill"
RUN_TIMEOUT = 900.0


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=claude (make e2e)")
class Claude(_person.PersonChecks):
    scenario = SCENARIO
    needs = "claude"
    run_done = Done(-1, "")

    @classmethod
    def intro(cls, tree: FixedTree) -> str:
        return (
            "This scenario uses YOUR real Claude Code login and spends tokens. The login must\n"
            "exist in the isolated HOME (nothing is copied from your real one). Once, in a shell:\n"
            f"{_person.exports(tree)}\n  claude    # then /login, and exit"
        )

    @_core.named("installer --harness claude exits 0")
    def test_01_install(self) -> None:
        done, cmd = self.installer("claude")
        ok = done.exit == 0 and "Finished with" not in done.output
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("claude plugin list shows wev-skills enabled")
    def test_02_plugin_listed(self) -> None:
        done = run(["claude", "plugin", "list", "--json"], 120, self.local.env())
        try:
            items = json.loads(done.output) if done.exit == 0 else []
        except ValueError:
            items = []
        found = [i for i in items if isinstance(i, dict) and "wev-skills" in json.dumps(i)]
        ok = bool(found) and all(i.get("enabled", True) is not False for i in found)
        self.record("claude plugin list --json", done.exit, ok, done.output)

    @_core.named("claude -p runs /wev-orchestrate and exits 0")
    def test_03_headless_run(self) -> None:
        argv = ["claude", "-p", PROMPT, "--output-format", "stream-json", "--verbose"]
        argv += ["--allowedTools", TOOLS]
        repo = _person.throwaway_repo(self.fixed)
        done = run(argv, RUN_TIMEOUT, self.local.env(), repo)
        type(self).run_done = done
        cmd = "claude -p <prompt> --output-format stream-json --verbose"
        self.record(cmd, done.exit, done.exit == 0, done.output)

    @_core.named("the hook ran: a .wev/ run exists or the session context is in the transcript")
    def test_04_hook_ran(self) -> None:
        repo = _person.throwaway_repo(self.fixed)
        ok = (repo / ".wev").exists() or "session-context" in self.run_done.output
        self.record("ls <repo>/.wev; grep session-context transcript", None, ok)

    @_core.named("wev-reverse and wev-orchestrate appear in the transcript")
    def test_05_skills_listed(self) -> None:
        text = self.run_done.output
        ok = "wev-reverse" in text and "wev-orchestrate" in text
        self.record("grep wev-reverse wev-orchestrate transcript", None, ok)

    @_core.named("mcp__rea__ tools appear in the transcript's tool list")
    def test_06_rea_tools(self) -> None:
        self.record("grep mcp__rea__ transcript", None, "mcp__rea__" in self.run_done.output)

    @_core.named("skills check --daily (SessionStart hook) left the marker")
    def test_07_marker(self) -> None:
        state = json.loads(self.local.read_state())
        self.record("grep checked_at state.json", None, bool(state.get("checked_at")))


if __name__ == "__main__":
    unittest.main()
