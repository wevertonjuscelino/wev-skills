"""gemini: install the Gemini CLI extension and run `gemini -p … -o json` (headless, from
docs/research/harness-gemini.md). Needs the CLI, which the owner installs first; without it every
check is skipped. Spends a Gemini account when it runs.

Label: implemented but untested: never run against a real harness in this change."""

from __future__ import annotations

import json
import os
import unittest

from tests.e2e import _core, _person
from tests.e2e._support import FixedTree, run
from wev_skills import __version__

SCENARIO = "gemini"
PROMPT = "print the wev version with the wev skill"


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=gemini (make e2e)")
class Gemini(_person.PersonChecks):
    scenario = SCENARIO
    needs = "gemini"

    @classmethod
    def intro(cls, tree: FixedTree) -> str:
        return (
            "This scenario uses YOUR Gemini credentials and spends tokens. Sign in once, in a\n"
            f"shell:\n{_person.exports(tree)}\n  gemini    # sign in, then exit"
        )

    @_core.named("installer --harness gemini exits 0")
    def test_01_install(self) -> None:
        done, cmd = self.installer("gemini")
        ok = done.exit == 0 and "Finished with" not in done.output
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("gemini extensions list shows the wev extension")
    def test_02_extension_listed(self) -> None:
        self.ask_again(
            "In the isolated shell: run the `gemini extensions link` line the installer printed\n"
            "(it is in the report detail of the previous check)."
        )
        done = run(["gemini", "extensions", "list", "-o", "json"], 120, self.local.env())
        self.record("gemini extensions list -o json", done.exit, "wev" in done.output, done.output)

    @_core.named("gemini -p prints the wev version")
    def test_03_headless(self) -> None:
        argv = ["gemini", "-p", PROMPT, "-o", "json"]
        done = run(argv, 900, self.local.env(), _person.throwaway_repo(self.fixed))
        try:
            response = str(json.loads(done.output).get("response", ""))
        except ValueError, AttributeError:
            response = ""
        self.record("gemini -p <prompt> -o json", done.exit, __version__ in response, done.output)


if __name__ == "__main__":
    unittest.main()
