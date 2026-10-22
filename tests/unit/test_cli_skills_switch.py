"""``wev skills update|rollback|freeze|activate|deactivate|show``, run in-process."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures.fake_registry_server import fake_registry
from tests.unit.test_third_party_fetch import add_file, tarball
from wev_skills import cli
from wev_skills.third_party import check, fetch, state

API = "https://api.github.com/repos/addyosmani/agent-skills"


def release_json(version: str) -> bytes:
    return json.dumps({"tag_name": version, "tarball_url": f"{API}/tarball/{version}"}).encode()


def skill_tar(meta: bytes = b"---\nname: a\ndescription: d\n---\nx\n") -> bytes:
    return tarball(lambda archive: add_file(archive, "x-1/skills/a/SKILL.md", meta))


def skills_tar(*names: str) -> bytes:
    def build(archive: tarfile.TarFile) -> None:
        for name in names:
            meta = f"---\nname: {name}\ndescription: d\n---\n".encode()
            add_file(archive, f"x-1/skills/{name}/SKILL.md", meta)

    return tarball(build)


class SwitchCliCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.dir), "XDG_DATA_HOME": str(self.dir / "data")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.third = self.dir / "data/wev-skills/third-party"

    def run_main(self, *argv: str) -> tuple[int, dict[str, object]]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--lang", "en", *argv])
        return code, json.loads(out.getvalue() or "{}")

    def update(
        self, version: str, tar: bytes | None = None, *args: str
    ) -> tuple[int, dict[str, object]]:
        with (
            mock.patch.object(check, "fetch", return_value=release_json(version)),
            mock.patch.object(fetch, "download", return_value=tar or skill_tar()),
        ):
            return self.run_main("skills", "update", "agent-skills", *args)

    def item(self) -> state.SourceState:
        return state.load(self.third / "state.json").sources["agent-skills"]

    def test_update_switches_and_saves_state(self) -> None:
        code, payload = self.update("v1.0.0")
        self.assertEqual(code, 0)
        result = payload["results"][0]  # type: ignore[index]
        self.assertEqual(
            (result["source"], result["ok"], result["code"]), ("agent-skills", True, "updated")
        )
        self.assertEqual(self.item().active, "v1.0.0")
        self.assertEqual(os.readlink(self.third / "agent-skills/current"), "v1.0.0")
        self.update("v2.0.0")
        self.assertEqual((self.item().active, self.item().previous), ("v2.0.0", "v1.0.0"))

    def test_failed_health_exits_8_and_keeps_the_state(self) -> None:
        self.update("v1.0.0")
        code, payload = self.update("v2.0.0", skill_tar(b"nope"))
        self.assertEqual(code, 8)
        result = payload["results"][0]  # type: ignore[index]
        self.assertEqual((result["ok"], result["code"]), (False, "bad_skill"))
        self.assertIn("invalid", result["health"])
        self.assertEqual(self.item().active, "v1.0.0")

    def test_frozen_is_refused_and_skipped_without_a_source(self) -> None:
        self.assertEqual(self.run_main("skills", "freeze", "agent-skills")[0], 0)
        self.assertTrue(self.item().frozen)
        self.assertEqual(self.update("v1.0.0")[0], 2)
        for name in ("rea", "wev-skills"):
            self.run_main("skills", "freeze", name)
        with mock.patch.object(check, "fetch", side_effect=AssertionError("no network")):
            code, payload = self.run_main("skills", "update")
        self.assertEqual(code, 0)
        self.assertEqual({r["code"] for r in payload["results"]}, {"frozen"})  # type: ignore[attr-defined]
        self.run_main("skills", "freeze", "agent-skills", "--off")
        self.assertFalse(self.item().frozen)

    def test_update_without_a_source_skips_declined_and_never_installed(self) -> None:
        item = state.SourceState(active="v1.0.0", declined="v2.0.0")
        state.save(self.third / "state.json", state.State({"agent-skills": item}))
        urls: list[str] = []

        def fake(url: str, _timeout: float) -> bytes:
            urls.append(url)
            return release_json("v2.0.0")

        with mock.patch.object(check, "fetch", fake):
            code, payload = self.run_main("skills", "update")
        self.assertEqual(code, 0)
        codes = {r["source"]: (r["ok"], r["code"]) for r in payload["results"]}  # type: ignore[attr-defined]
        self.assertEqual(
            codes,
            {
                "rea": (True, "not_installed"),
                "agent-skills": (True, "declined"),
                "wev-skills": (True, "not_installed"),
            },
        )
        self.assertEqual(urls, [f"{API}/releases/latest"])
        self.assertEqual(self.item().active, "v1.0.0")

    def test_rollback(self) -> None:
        self.assertEqual(self.run_main("skills", "rollback", "agent-skills")[0], 5)
        self.update("v1.0.0")
        self.update("v2.0.0")
        code, payload = self.run_main("skills", "rollback", "agent-skills")
        self.assertEqual((code, payload["active"], payload["previous"]), (0, "v1.0.0", "v2.0.0"))
        self.assertEqual(os.readlink(self.third / "agent-skills/current"), "v1.0.0")

    def test_show(self) -> None:
        code, payload = self.run_main("skills", "show", "rea")
        self.assertEqual(code, 0)
        self.assertEqual(payload["mcp_argv"], None)  # not active yet: nothing to start
        self.run_main("skills", "freeze", "rea")
        item = state.load(self.third / "state.json").sources["rea"]
        state.save(
            self.third / "state.json",
            state.State({"rea": state.SourceState(active="1.2.3", frozen=item.frozen)}),
        )
        _, payload = self.run_main("skills", "show", "rea")
        self.assertEqual(payload["mcp_argv"], ["npx", "-y", "rea-agents" + "@" + "1.2.3", "mcp"])
        self.assertTrue(payload["state"]["frozen"])  # type: ignore[index]
        self.assertEqual(self.run_main("skills", "show", "nope")[0], 2)

    def test_activate_and_deactivate(self) -> None:
        (self.dir / ".claude/skills").mkdir(parents=True)
        self.assertEqual(self.run_main("skills", "activate")[0], 5)  # nothing installed
        self.update("v1.0.0")
        code, payload = self.run_main("skills", "activate")
        link = self.dir / ".claude/skills/a"
        self.assertEqual((code, payload["links"]), (0, [str(link)]))
        self.assertTrue((link / "SKILL.md").is_file())
        self.assertFalse((self.dir / ".agents").exists())
        code, payload = self.run_main("skills", "deactivate")
        self.assertEqual((code, payload["removed"]), (0, [str(link)]))
        self.assertFalse(link.is_symlink())

    def test_rollback_is_not_undone_by_the_next_update(self) -> None:
        self.update("v1.0.0")
        self.update("v2.0.0")
        self.run_main("skills", "rollback", "agent-skills")
        self.assertEqual(self.item().declined, "v2.0.0")
        with mock.patch.object(check, "fetch", return_value=release_json("v2.0.0")):
            code, payload = self.run_main("skills", "update")
        rows = {r["source"]: r["code"] for r in payload["results"]}  # type: ignore[attr-defined]
        self.assertEqual((code, rows["agent-skills"]), (0, "declined"))
        self.assertEqual(self.item().active, "v1.0.0")
        self.assertEqual(self.update("v2.0.0", None, "--yes")[0], 0)
        self.assertEqual(self.item().active, "v2.0.0")

    def links(self) -> dict[str, bool]:
        root = self.dir / ".claude/skills"
        return {p.name: p.exists() for p in root.iterdir()}

    def test_activation_follows_an_update_and_a_rollback(self) -> None:
        (self.dir / ".claude/skills").mkdir(parents=True)
        self.update("v1.0.0", skills_tar("a"))
        self.run_main("skills", "activate")
        code, payload = self.update("v2.0.0", skills_tar("b"))
        self.assertEqual(code, 0)
        self.assertEqual(self.links(), {"b": True})
        row = payload["results"][0]  # type: ignore[index]
        self.assertEqual(row["activation"]["ok"], True)
        code, payload = self.run_main("skills", "rollback", "agent-skills")
        self.assertEqual((code, self.links()), (0, {"a": True}))
        self.assertEqual(payload["activation"]["ok"], True)  # type: ignore[index]

    def test_without_a_manifest_an_update_links_nothing(self) -> None:
        (self.dir / ".claude/skills").mkdir(parents=True)
        _, payload = self.update("v1.0.0", skills_tar("a"))
        self.assertEqual(self.links(), {})
        self.assertNotIn("activation", payload["results"][0])  # type: ignore[index]

    def test_a_foreign_entry_after_an_update_is_a_conflict_row(self) -> None:
        (self.dir / ".claude/skills").mkdir(parents=True)
        self.update("v1.0.0", skills_tar("a"))
        self.run_main("skills", "activate")
        (self.dir / ".claude/skills/b").mkdir()  # the person's own directory
        code, payload = self.update("v2.0.0", skills_tar("b"))
        row = payload["results"][0]  # type: ignore[index]
        self.assertEqual((code, row["code"], self.item().active), (8, "updated", "v2.0.0"))
        self.assertEqual(
            (row["activation"]["ok"], row["activation"]["code"]), (False, "foreign_entry")
        )
        self.assertTrue((self.dir / ".claude/skills/b").is_dir())

    def test_a_dripping_registry_stops_an_update_at_the_budget(self) -> None:
        path = "/repos/addyosmani/agent-skills/releases/latest"
        with (
            fake_registry({path: (200, release_json("v1.0.0"), 0.05)}) as fake,
            mock.patch.dict(check.BASE_URLS, {"github": fake.url}),
            mock.patch.object(check, "INTERACTIVE_BUDGET", 0.3),
        ):
            started = time.monotonic()
            code, payload = self.run_main("skills", "update", "agent-skills")
        self.assertLess(time.monotonic() - started, 2.0)
        row = payload["results"][0]  # type: ignore[index]
        self.assertEqual((code, row["code"]), (8, "timed_out"))


if __name__ == "__main__":
    unittest.main()
