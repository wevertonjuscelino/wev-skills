"""update-daily: with rea pinned at the previous release and the daily marker removed, the daily
check (`wev skills check --daily`, what the SessionStart hook runs) prints the one-paragraph
notice; `skills decline rea` silences it; `skills update rea --yes` switches. Spends network only
(npm registry), no account.

Label: implemented but untested: never run against a real harness in this change. The wording of
the notice is not asserted: the check looks for the rea name and the newest version."""

from __future__ import annotations

import json
import os
import unittest

from tests.e2e import _core, _person
from tests.e2e._support import Done, Tree
from tests.e2e.test_macos_core import LocalHost

SCENARIO = "update-daily"


@unittest.skipUnless(os.environ.get("WEV_E2E") == SCENARIO, "set WEV_E2E=update-daily (make e2e)")
class UpdateDaily(_core.Checks):
    scenario = SCENARIO
    local: LocalHost

    @classmethod
    def setUpClass(cls) -> None:
        cls.blocked = _person.await_person("Network only, an isolated temporary HOME, no account.")
        if cls.blocked:
            return
        cls.local = LocalHost(Tree())
        cls.host = cls.local
        cls.registry = _core.fetch_registry()
        if cls.registry is None:
            cls.blocked = "registry unreachable"

    @classmethod
    def tearDownClass(cls) -> None:
        if not cls.blocked:
            cls.local.cleanup()

    def reset_marker(self) -> None:
        data = json.loads(self.host.read_state())
        data["checked_at"] = None
        self.host.write_state(json.dumps(data))

    def notice(self) -> tuple[Done, str]:
        self.reset_marker()
        return self.wev("skills", "check", "--daily")

    @_core.named("installer exits 0, then rea is pinned at the previous release")
    def test_01_pin_previous(self) -> None:
        newest, previous = self.registry or ("", "")
        done, cmd = self.install_sh(
            *["--yes", "--lang", "en", "--source", self.host.source, "--harness", ""],
            *["--no-jev", "--rea-mode", "direct"],
        )
        fetched, _ = self.wev("skills", "install", "rea", "--version", previous)
        base = self.local._tree.data / "wev-skills" / "third-party" / "rea"
        tmp = base / "current.tmp-e2e"
        os.symlink(previous, tmp)
        os.replace(tmp, base / "current")
        data = json.loads(self.host.read_state())
        data["sources"]["rea"].update(active=previous, previous=None, latest_seen=None)
        self.host.write_state(json.dumps(data))
        ok = done.exit == 0 and fetched.exit == 0 and self.active() == previous
        note = "state and current link set by hand: the CLI cannot make an older release active"
        self.record(cmd, done.exit, ok, done.output + fetched.output, note)

    @_core.named("skills check --daily prints the notice for the newest release")
    def test_02_notice(self) -> None:
        newest = (self.registry or ("", ""))[0]
        done, cmd = self.notice()
        ok = done.exit == 0 and "rea" in done.output and newest in done.output
        self.record(cmd, done.exit, ok, done.output)

    @_core.named("skills decline rea silences the notice")
    def test_03_decline(self) -> None:
        newest = (self.registry or ("", ""))[0]
        declined, cmd = self.wev("skills", "decline", "rea")
        done, _ = self.notice()
        ok = declined.exit == 0 and done.exit == 0 and newest not in done.output
        self.record(cmd, declined.exit, ok, declined.output + done.output)

    @_core.named("skills update rea --yes switches to the newest release")
    def test_04_update(self) -> None:
        newest = (self.registry or ("", ""))[0]
        done, cmd = self.wev("skills", "update", "rea", "--yes", timeout=_core.LONG)
        self.record(cmd, done.exit, done.exit == 0 and self.active() == newest, done.output)


if __name__ == "__main__":
    unittest.main()
