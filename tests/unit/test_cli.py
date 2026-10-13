from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import __version__, cli
from wev_skills.core.errors import NotFound, StateConflict

ROOT = Path(__file__).resolve().parents[2]


def run_main(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_version(self) -> None:
        code, out, _ = run_main("version")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"version": __version__})

    def test_config_show_prints_defaults(self) -> None:
        code, out, _ = run_main("config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["models"]["tiers"]["economy"], ["claude-haiku-5-5"])

    def test_config_show_applies_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "c.json")
            path.write_text(json.dumps({"limits": {"max_attempts": 8}}))
            code, out, _ = run_main("--config", str(path), "config", "show")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["limits"]["max_attempts"], 8)

    def test_config_validate_ok_and_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good, bad = Path(tmp, "g.json"), Path(tmp, "b.json")
            good.write_text("{}")
            bad.write_text('{"language": "fr"}')
            code, out, _ = run_main("config", "validate", str(good))
            self.assertEqual((code, json.loads(out)["valid"]), (0, True))
            code, out, err = run_main("config", "validate", str(bad))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        error = json.loads(err)["error"]
        self.assertEqual(error["code"], "invalid_config")
        self.assertEqual(set(error), {"code", "message", "details"})

    def test_missing_file_maps_to_exit_7(self) -> None:
        code, _, err = run_main("config", "validate", "/nonexistent/x.json")
        self.assertEqual(code, 7)
        self.assertEqual(json.loads(err)["error"]["code"], "file_not_found")

    def test_usage_errors_return_2(self) -> None:
        for argv in ([], ["nope"], ["config"], ["--bogus", "version"], ["config", "validate"]):
            with self.subTest(argv=argv):
                code, out, _ = run_main(*argv)
                self.assertEqual((code, out), (2, ""))

    def test_help_returns_zero(self) -> None:
        code, out, _ = run_main("--help")
        self.assertEqual(code, 0)
        self.assertIn("version", out)

    def test_invalid_lang_is_a_validation_error(self) -> None:
        code, _, err = run_main("--lang", "fr", "version")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)["error"]["code"], "unsupported_language")

    def test_lang_switches_help_language(self) -> None:
        _, out, _ = run_main("--lang", "pt-BR", "--help")
        self.assertIn("Imprime a versão", out)

    def test_ensure_ascii_false(self) -> None:
        with mock.patch.object(cli, "build_parser") as build:
            parser = cli.argparse.ArgumentParser()
            parser.set_defaults(handler=lambda args: {"msg": "ação"})
            build.return_value = parser
            code, out, _ = run_main()
        self.assertEqual(code, 0)
        self.assertIn("ação", out)

    def test_wev_errors_use_their_exit_code_and_json_shape(self) -> None:
        for exc, expected in ((NotFound("c", "m", {"a": 1}), 7), (StateConflict("s", "m"), 5)):
            with (
                self.subTest(exc=type(exc).__name__),
                mock.patch.object(cli, "build_parser", side_effect=exc),
            ):
                code, out, err = run_main("version")
            self.assertEqual((code, out), (expected, ""))
            expected_error = {"code": exc.code, "message": "m", "details": exc.details}
            self.assertEqual(json.loads(err), {"error": expected_error})

    def test_unexpected_exception_returns_1_without_traceback(self) -> None:
        with mock.patch.object(cli, "build_parser", side_effect=RuntimeError("secret detail")):
            code, _, err = run_main("version")
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        self.assertNotIn("secret detail", err)
        self.assertEqual(json.loads(err)["error"]["code"], "unexpected_error")

    def test_debug_flag_prints_traceback(self) -> None:
        with (
            mock.patch.dict(os.environ, {"WEV_DEBUG": "1"}),
            mock.patch.object(cli, "build_parser", side_effect=RuntimeError("boom")),
        ):
            code, _, err = run_main("version")
        self.assertEqual(code, 1)
        self.assertIn("Traceback", err)

    def test_non_serializable_result_returns_1(self) -> None:
        parser = cli.argparse.ArgumentParser()
        parser.set_defaults(handler=lambda args: {"x": object()})
        with mock.patch.object(cli, "build_parser", return_value=parser):
            code, out, err = run_main()
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(json.loads(err)["error"]["code"], "bad_result")


class CommandResultTests(unittest.TestCase):
    def run_handler(self, handler: object) -> tuple[int, str, str]:
        parser = cli.argparse.ArgumentParser()
        parser.set_defaults(handler=handler)
        with mock.patch.object(cli, "build_parser", return_value=parser):
            return run_main()

    def test_handler_sets_the_exit_code_and_still_prints_on_stdout(self) -> None:
        code, out, err = self.run_handler(lambda args: cli.CommandResult({"ok": False}, 4))
        self.assertEqual((code, err), (4, ""))
        self.assertEqual(json.loads(out), {"ok": False})

    def test_handler_can_choose_stderr(self) -> None:
        result = cli.CommandResult({"note": "x"}, 0, stream="stderr")
        code, out, err = self.run_handler(lambda args: result)
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(json.loads(err), {"note": "x"})

    def test_raw_text_is_printed_as_is(self) -> None:
        code, out, _ = self.run_handler(lambda args: cli.CommandResult("# Título\n", raw=True))
        self.assertEqual((code, out), (0, "# Título\n"))

    def test_plain_return_values_keep_working(self) -> None:
        code, out, _ = self.run_handler(lambda args: [1, 2])
        self.assertEqual((code, json.loads(out)), (0, [1, 2]))

    def test_unusable_results_return_1(self) -> None:
        bad = (
            cli.CommandResult({"x": object()}),
            cli.CommandResult({}, stream="nowhere"),
            cli.CommandResult({"not": "text"}, raw=True),
            cli.CommandResult({}, exit_code=True),
        )
        for result in bad:
            with self.subTest(result=result):
                code, out, err = self.run_handler(lambda args, value=result: value)
                self.assertEqual((code, out), (1, ""))
                self.assertEqual(json.loads(err)["error"]["code"], "bad_result")


class CommandDiscoveryTests(unittest.TestCase):
    def test_meta_module_is_discovered(self) -> None:
        self.assertIn("meta", cli.discover_command_modules())

    def test_broken_group_is_reported_but_does_not_break_cli(self) -> None:
        with mock.patch.object(cli, "discover_command_modules", return_value=["meta", "ghost"]):
            code, out, err = run_main("version")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["version"], __version__)
        self.assertIn("ghost", json.loads(err)["warning"])


class LauncherTests(unittest.TestCase):
    def test_bin_wev_runs_as_real_subprocess(self) -> None:
        launcher = ROOT / "bin" / "wev"
        self.assertTrue(os.access(launcher, os.X_OK))
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(launcher), "version"],
            capture_output=True,
            text=True,
            env=env,
            cwd="/",
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"version": __version__})

    def test_bin_wev_follows_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp, "wev-link")
            link.symlink_to(ROOT / "bin" / "wev")
            env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
            proc = subprocess.run(
                [sys.executable, str(link), "version"],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_bin_wev_exit_code_propagates(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "bin" / "wev"), "config", "validate", "/nonexistent.json"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 7)


if __name__ == "__main__":
    unittest.main()
