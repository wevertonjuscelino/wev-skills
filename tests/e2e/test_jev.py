"""jev: a real JEV credential in the isolated HOME (`.wev/e2e-home/`), typed by the owner, never
by a test. One real `wev jev ask` call to api.typesafe.ai. The credential file is never read or
printed, and the environment variable is removed from every child.

Label: implemented but untested: never run against a real harness in this change."""

from __future__ import annotations

import json
import os
import unittest

from tests.e2e import _core, _person
from tests.e2e._support import ROOT, FixedTree

SCENARIO = "jev"
QUESTIONS = {"question": {"type": "noul", "instructions": "Is this text a question?"}}
STATE = "How do I rename a file?"


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=jev (make e2e)")
class Jev(_person.PersonChecks):
    scenario = SCENARIO

    @classmethod
    def intro(cls, tree: FixedTree) -> str:
        return (
            "This scenario makes one real call to api.typesafe.ai with YOUR JEV key. Type the key\n"
            "yourself, once, into the isolated HOME (the test never types or reads it):\n"
            f"{_person.exports(tree)}\n  bash {ROOT}/install.sh --source {ROOT} --jev"
        )

    @_core.named("jev status is usable and orchestration is wev")
    def test_01_status(self) -> None:
        done, cmd = self.wev("jev", "status")
        info = _core.parse(done)
        ok = info.get("key_error") is None and info.get("orchestration") == "wev"
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("wev jev ask answers one question")
    def test_02_ask(self) -> None:
        work = self.fixed.root / "jev"
        work.mkdir(exist_ok=True)
        (work / "questions.json").write_text(json.dumps(QUESTIONS), encoding="utf-8")
        (work / "state.txt").write_text(STATE, encoding="utf-8")
        args = ["jev", "ask", "--questions", str(work / "questions.json")]
        done, cmd = self.wev(*args, "--state-file", str(work / "state.txt"))
        ok = done.exit == 0 and "question" in _core.parse(done)
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("wev classify records provider jev (no fallback)")
    def test_03_classify(self) -> None:
        done, cmd = self.wev("classify", "--objective", "rename a variable in one file")
        ok = done.exit == 0 and _core.parse(done).get("source") == "jev"
        self.record(cmd, done.exit, ok, done.output)


if __name__ == "__main__":
    unittest.main()
