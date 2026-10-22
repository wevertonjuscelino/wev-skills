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

from tests.unit.test_rea_image import FakeRunner
from wev_skills import cli
from wev_skills.core.contracts import RawCommandResult
from wev_skills.third_party import state


class DockerRunner(FakeRunner):
    """Succeeds unless the docker subcommand (``info``, ``image``, ``build``) is in ``fail``."""

    def __init__(self) -> None:
        super().__init__()
        self.fail: set[str] = set()

    def run(self, argv, cwd, timeout, env) -> RawCommandResult:  # type: ignore[no-untyped-def]
        self.code = 1 if argv[1] in self.fail else 0
        return super().run(argv, cwd, timeout, env)


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
        # a deterministic repository root: the tests must not depend on the process cwd
        self.work = self.dir / "work"
        (self.work / ".git").mkdir(parents=True)
        previous = os.getcwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)
        self.runner = DockerRunner()
        runner = mock.patch("wev_skills.commands.rea._runner", return_value=self.runner)
        runner.start()
        self.addCleanup(runner.stop)

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
        account = self.dir / "account"
        account.mkdir()
        link = self.dir / "elsewhere"
        link.symlink_to(account)
        with (
            mock.patch.dict(os.environ, {"HOME": str(account)}),
            mock.patch("pathlib.Path.cwd", return_value=link),
        ):
            code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "rea_cwd_refused")  # type: ignore[index]

    def test_serve_creates_private_home_dirs(self) -> None:
        self.pin()
        self.fake("docker")
        work = self.work
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
        work = self.work
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

    def isolated_serve(self, dry_run: bool = False) -> tuple[int, dict[str, object]]:
        self.pin()
        self.fake("docker")
        work = self.work
        args = ["rea", "serve", *(["--dry-run"] if dry_run else [])]
        patched = mock.patch("wev_skills.rea.launch.serve", side_effect=SystemExit(0))
        with patched as served, mock.patch("pathlib.Path.cwd", return_value=work):
            self.served = served
            try:
                return run_main(*args)
            except SystemExit as exit_:  # the fake exec: the process would have been replaced
                return int(str(exit_.code)), {}

    def test_serve_refuses_when_docker_is_down(self) -> None:
        self.runner.fail = {"info"}
        code, payload = self.isolated_serve()
        self.assertEqual(code, 8)
        self.assertEqual(payload["error"]["code"], "docker_unavailable")  # type: ignore[index]
        self.assertIn("wev rea mode direct", payload["error"]["message"])  # type: ignore[index]
        self.served.assert_not_called()

    def test_serve_refuses_when_the_image_is_missing(self) -> None:
        self.runner.fail = {"image"}
        code, payload = self.isolated_serve()
        self.assertEqual(code, 5)
        self.assertEqual(payload["error"]["code"], "rea_image_missing")  # type: ignore[index]
        self.assertIn("wev rea build-image", payload["error"]["message"])  # type: ignore[index]
        self.served.assert_not_called()

    def test_dry_run_skips_the_docker_probes(self) -> None:
        self.runner.fail = {"info", "image"}
        code, payload = self.isolated_serve(dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn("argv", payload)
        self.assertEqual(self.runner.calls, [])

    def test_serve_execs_when_docker_and_image_are_ready(self) -> None:
        code, _ = self.isolated_serve()
        self.assertEqual(code, 0)
        self.served.assert_called_once()
        self.assertEqual(
            [c[0][1:] for c in self.runner.calls],
            [("info",), ("image", "inspect", "wev-rea:6.7.0")],
        )

    def test_status_image_present(self) -> None:
        self.pin()
        self.fake("docker")
        _, payload = run_main("rea", "status")
        self.assertIs(payload["image_present"], True)
        self.runner.fail = {"image"}
        _, payload = run_main("rea", "status")
        self.assertIs(payload["image_present"], False)

    def test_status_image_present_is_null_without_version_or_docker(self) -> None:
        self.fake("docker")
        _, payload = run_main("rea", "status")
        self.assertIsNone(payload["image_present"])
        self.pin()
        (self.bin / "docker").unlink()
        _, payload = run_main("rea", "status")
        self.assertIsNone(payload["image_present"])

    def test_status_warns_when_isolated_without_docker(self) -> None:
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"isolated"}', encoding="utf-8")
        _, payload = run_main("rea", "status")
        warnings = payload["warnings"]
        assert isinstance(warnings, list)
        self.assertEqual(len(warnings), 2)
        self.assertIn("Docker was not found", warnings[1])

    def test_build_image_default_and_explicit_version(self) -> None:
        self.pin()
        self.fake("docker")
        code, payload = run_main("rea", "build-image")
        self.assertEqual((code, payload), (0, {"image": "wev-rea:6.7.0", "built": True}))
        argv = self.runner.calls[0][0]
        self.assertEqual(
            argv[:6],
            (
                str(self.bin / "docker"),
                "build",
                "--build-arg",
                "REA_VERSION=6.7.0",
                "-t",
                "wev-rea:6.7.0",
            ),
        )
        self.assertTrue(argv[7].endswith("docker/rea/Dockerfile"))
        _, payload = run_main("rea", "build-image", "--version", "6.8.0")
        self.assertEqual(payload["image"], "wev-rea:6.8.0")

    def test_build_image_failures(self) -> None:
        self.pin()
        self.fake("docker")
        self.runner.fail = {"build"}
        code, payload = run_main("rea", "build-image")
        self.assertEqual((code, payload["error"]["code"]), (8, "rea_image_build_failed"))  # type: ignore[index]
        code, payload = run_main("rea", "build-image", "--version", "latest")
        self.assertEqual((code, payload["error"]["code"]), (2, "rea_version_invalid"))  # type: ignore[index]

    def test_build_image_without_docker_or_pin(self) -> None:
        code, payload = run_main("rea", "build-image")
        self.assertEqual((code, payload["error"]["code"]), (5, "rea_not_installed"))  # type: ignore[index]
        self.pin()
        code, payload = run_main("rea", "build-image")
        self.assertEqual((code, payload["error"]["code"]), (2, "rea_docker_missing"))  # type: ignore[index]

    def repo_with_fake_docker(self) -> Path:
        repo = self.dir / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "bin").mkdir()
        fake = repo / "bin" / "docker"
        fake.write_text("#!/bin/sh\n", encoding="utf-8")
        fake.chmod(0o755)
        return repo

    def test_a_docker_inside_the_repository_is_never_used(self) -> None:
        repo = self.repo_with_fake_docker()
        self.pin()
        with (
            mock.patch("pathlib.Path.cwd", return_value=repo),
            mock.patch("wev_skills.commands.rea._exec_path", return_value=(str(repo / "bin"),)),
        ):
            _, status = run_main("rea", "status")
            code, mode = run_main("rea", "mode", "isolated")
            direct, _ = run_main("rea", "mode", "direct")
            built, build = run_main("rea", "build-image")
        self.assertEqual((status["docker"], status["image_present"]), ("missing", None))
        self.assertEqual((code, mode["error"]["code"]), (2, "rea_docker_missing"))  # type: ignore[index]
        self.assertEqual(direct, 0)
        self.assertEqual((built, build["error"]["code"]), (3, "program_in_run_root"))  # type: ignore[index]
        self.assertEqual(self.runner.calls, [])

    def in_repo_link(self, name: str, target: Path) -> Path:
        link = self.work / "bin" / name
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(target)
        return link

    def run_with_path(self, entry: Path, *argv: str) -> tuple[int, dict[str, object]]:
        with mock.patch("wev_skills.commands.rea._exec_path", return_value=(str(entry),)):
            return run_main(*argv)

    def assert_refused(self, result: tuple[int, dict[str, object]]) -> None:
        code, payload = result
        self.assertEqual((code, payload["error"]["code"]), (3, "program_in_run_root"))  # type: ignore[index]
        self.assertEqual(self.runner.calls, [])

    def test_an_in_repo_symlink_to_an_outside_program_is_refused(self) -> None:
        self.pin()
        self.fake("docker")
        self.in_repo_link("docker", self.bin / "docker")
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"isolated"}', encoding="utf-8")
        entry = self.work / "bin"
        self.assert_refused(self.run_with_path(entry, "rea", "serve", "--dry-run"))
        self.assert_refused(self.run_with_path(entry, "rea", "serve"))
        self.assert_refused(self.run_with_path(entry, "rea", "build-image"))

    def test_an_outside_symlink_into_the_repo_is_refused(self) -> None:
        self.pin()
        target = self.work / "docker"
        target.write_text("#!/bin/sh\n", encoding="utf-8")
        target.chmod(0o755)
        (self.bin / "docker").symlink_to(target)
        self.assert_refused(self.run_with_path(self.bin, "rea", "build-image"))

    def test_serve_refuses_an_in_repo_npx(self) -> None:
        self.pin()
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"direct"}', encoding="utf-8")
        npx = self.work / "bin" / "npx"
        npx.parent.mkdir()
        npx.write_text("#!/bin/sh\n", encoding="utf-8")
        npx.chmod(0o755)
        self.assert_refused(self.run_with_path(npx.parent, "rea", "serve", "--dry-run"))

    def test_serve_resolves_only_the_program_its_mode_needs(self) -> None:
        self.pin()
        self.fake("npx")
        bad = self.work / "bin"
        bad.mkdir()
        (bad / "docker").write_text("#!/bin/sh\n", encoding="utf-8")
        (bad / "docker").chmod(0o755)
        self.conf.parent.mkdir(parents=True)
        self.conf.write_text('{"mode":"direct"}', encoding="utf-8")
        with mock.patch(
            "wev_skills.commands.rea._exec_path", return_value=(str(self.bin), str(bad))
        ):
            code, payload = run_main("rea", "serve", "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(payload["argv"][0], str(self.bin / "npx"))  # type: ignore[index]

    def test_status_image_present_is_null_when_the_daemon_is_down(self) -> None:
        self.pin()
        self.fake("docker")
        self.runner.fail = {"info"}
        _, payload = run_main("rea", "status")
        self.assertEqual((payload["docker"], payload["image_present"]), ("found", None))

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
        work = self.work
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
