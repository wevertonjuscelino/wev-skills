"""``wev rea serve|status|mode`` in-process, with HOME/XDG and the exec path in a temp dir."""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import cli
from wev_skills.third_party import state


def run_main(*argv: str) -> tuple[int, dict[str, object]]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--lang", "en", *argv])
    return code, json.loads(out.getvalue() or err.getvalue() or "{}")


class ReaCliTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        env = {
            "HOME": str(self.dir),
            "XDG_DATA_HOME": str(self.dir / "data"),
            "XDG_CONFIG_HOME": str(self.dir / "conf"),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        which = mock.patch("wev_skills.commands.rea._exec_path", return_value=(str(self.bin),))
        which.start()
        self.addCleanup(which.stop)
        self.conf = self.dir / "conf" / "wev-skills" / "rea.json"

    def fake(self, name: str) -> None:
        path = self.bin / name
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        path.chmod(0o755)

    def pin(self, version: str = "6.7.0") -> None:
        item = state.SourceState(active=version)
        state.save(state.data_home() / "state.json", state.State({"rea": item}, None))

    def test_status_default_direct_without_docker(self) -> None:
        self.pin()
        code, payload = run_main("rea", "status")
        self.assertEqual(code, 0)
        self.assertEqual(
            {k: v for k, v in payload.items() if k != "warnings"},
            {
                "mode": "direct", "mode_source": "default", "version": "6.7.0",
                "image": "wev-rea:6.7.0", "docker": "missing", "image_present": None,
            },
        )  # fmt: skip
        warnings = payload["warnings"]
        assert isinstance(warnings, list)
        self.assertEqual(len(warnings), 1)
        self.assertIn("permissions", warnings[0])

    def test_status_default_isolated_with_docker(self) -> None:
        self.fake("docker")
        code, payload = run_main("rea", "status")
        self.assertEqual(code, 0)
        self.assertEqual(
            (payload["mode"], payload["docker"], payload["version"], payload["image"]),
            ("isolated", "found", None, None),
        )
        warnings = payload["warnings"]
        assert isinstance(warnings, list)
        self.assertIn("Frida", warnings[0])

    def test_status_reports_config_source(self) -> None:
        self.pin()
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"direct"}', encoding="utf-8")
        _, payload = run_main("rea", "status")
        self.assertEqual((payload["mode_source"], payload["image"]), ("config", "wev-rea:6.7.0"))

    def test_status_rejects_an_image_key(self) -> None:
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"direct","image":"x/y:1"}', encoding="utf-8")
        code, _ = run_main("rea", "status")
        self.assertEqual(code, 2)

    def test_serve_isolated_without_docker_prints_no_argv(self) -> None:
        self.pin()
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"isolated"}', encoding="utf-8")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["--lang", "en", "rea", "serve", "--dry-run"])
        self.assertEqual((code, out.getvalue()), (2, ""))
        code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(payload["error"]["code"], "rea_docker_missing")  # type: ignore[index]

    def test_serve_direct_without_npx(self) -> None:
        self.pin()
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"direct"}', encoding="utf-8")
        code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 7)
        self.assertEqual(payload["error"]["code"], "rea_npx_missing")  # type: ignore[index]

    def test_serve_cwd_symlink_to_home_is_refused(self) -> None:
        self.pin()
        self.fake("docker")
        link = self.dir / "elsewhere"
        link.symlink_to(self.dir)
        with mock.patch("pathlib.Path.cwd", return_value=link):
            code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "rea_cwd_refused")  # type: ignore[index]

    def test_serve_creates_private_home_dirs(self) -> None:
        self.pin()
        self.fake("docker")
        work = self.dir / "work"
        work.mkdir()
        patched = mock.patch("wev_skills.rea.launch.serve", side_effect=SystemExit(0))
        cwd = mock.patch("pathlib.Path.cwd", return_value=work)
        with patched, cwd, self.assertRaises(SystemExit):
            run_main("rea", "serve")
        home = self.dir / "data" / "wev-skills" / "rea" / "home"
        self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(home.parent.stat().st_mode), 0o700)

    def test_serve_refuses_a_symlinked_home(self) -> None:
        self.pin()
        self.fake("docker")
        work = self.dir / "work"
        work.mkdir()
        target = self.dir / "target"
        target.mkdir()
        home = self.dir / "data" / "wev-skills" / "rea" / "home"
        home.parent.mkdir(parents=True)
        home.symlink_to(target)
        patched = mock.patch("wev_skills.rea.launch.serve", side_effect=SystemExit(0))
        with patched as served, mock.patch("pathlib.Path.cwd", return_value=work):
            code, payload = run_main("rea", "serve")
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "rea_home_refused")  # type: ignore[index]
        served.assert_not_called()

    def test_mode_carries_the_warning(self) -> None:
        _, payload = run_main("rea", "mode", "direct")
        warnings = payload["warnings"]
        assert isinstance(warnings, list)
        self.assertIn("permissions", warnings[0])
        self.fake("docker")
        _, payload = run_main("rea", "mode", "isolated")
        self.assertIn("Frida", payload["warnings"][0])  # type: ignore[index]

    def test_status_rejects_invalid_config(self) -> None:
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"isolated; sh"}', encoding="utf-8")
        code, payload = run_main("rea", "status")
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "rea_config_invalid")  # type: ignore[index]

    def test_mode_direct_writes_private_config(self) -> None:
        code, payload = run_main("rea", "mode", "direct")
        self.assertEqual((code, payload["mode"]), (0, "direct"))
        self.assertEqual(json.loads(self.conf.read_text("utf-8"))["mode"], "direct")
        self.assertEqual(stat.S_IMODE(self.conf.stat().st_mode), 0o600)

    def test_mode_isolated_refused_without_docker(self) -> None:
        code, payload = run_main("rea", "mode", "isolated")
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "rea_docker_missing")  # type: ignore[index]
        self.assertFalse(self.conf.exists())

    def test_mode_isolated_with_docker(self) -> None:
        self.fake("docker")
        code, _ = run_main("rea", "mode", "isolated")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.conf.read_text("utf-8"))["mode"], "isolated")

    def test_mode_rejects_other_values(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["rea", "mode", "isolated; sh"]), 2)
        self.assertFalse(self.conf.exists())

    def test_serve_dry_run_direct(self) -> None:
        self.pin()
        self.fake("npx")
        code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(
            payload, {"argv": [str(self.bin / "npx"), "-y", "rea-agents" + "@6.7.0", "mcp"]}
        )

    def test_serve_dry_run_isolated_uses_the_wev_home(self) -> None:
        self.pin()
        self.fake("docker")
        work = self.dir / "work"
        work.mkdir()
        with mock.patch("pathlib.Path.cwd", return_value=work):
            code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 0)
        argv = payload["argv"]
        assert isinstance(argv, list)
        self.assertEqual(argv[0], str(self.bin / "docker"))
        self.assertIn(f"{self.dir / 'data' / 'wev-skills' / 'rea' / 'home'}:/opt/rea-home", argv)
        self.assertEqual(argv[-1], "wev-rea:6.7.0")

    def test_serve_not_installed(self) -> None:
        code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 5)
        self.assertEqual(payload["error"]["code"], "rea_not_installed")  # type: ignore[index]

    def test_serve_execs_without_dry_run(self) -> None:
        self.pin()
        self.fake("npx")
        patched = mock.patch("wev_skills.rea.launch.serve", side_effect=SystemExit(0))
        with patched as served, self.assertRaises(SystemExit):
            run_main("rea", "serve")
        served.assert_called_once()
        self.assertEqual(served.call_args.args[0][1:], ("-y", "rea-agents" + "@6.7.0", "mcp"))


if __name__ == "__main__":
    unittest.main()
