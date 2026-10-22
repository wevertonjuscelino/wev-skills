"""``write_env_key`` and ``wev jev key set``: the installer stores the JEV key in the env file.

The config directory points at a temporary directory; no real key, keychain or network is used.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import cli
from wev_skills.core.errors import ValidationError
from wev_skills.decisions.jev_key import ApiKey, resolve_api_key, write_env_key

VAR = "TYPESAFE_API_KEY"
FILE_NAME = "." + "env"
KEY = "ts-test-0123456789abcdef"


class _TtyStdin(io.StringIO):
    def isatty(self) -> bool:
        return True


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.cfg = self.dir / "cfg" / "wev-skills"
        self.file = self.cfg / FILE_NAME
        env = {"HOME": str(self.dir), "XDG_CONFIG_HOME": str(self.dir / "cfg")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(VAR, None)
        os.environ.pop("JEV_API_URL", None)

    def seed(self, text: str) -> None:
        self.cfg.mkdir(parents=True, mode=0o700)
        self.file.write_bytes(text.encode("utf-8"))
        os.chmod(self.file, 0o600)


class WriteEnvKeyTest(_Case):
    def test_roundtrip_through_resolve_api_key(self) -> None:
        write_env_key(self.file, KEY)
        self.assertEqual(resolve_api_key({}, self.file, lambda: None), ApiKey(KEY, "env_file"))

    def test_other_lines_are_kept_byte_for_byte(self) -> None:
        self.seed(f"# my keys\r\nOTHER='x y'\n{VAR}=old\nexport LAST=1")
        write_env_key(self.file, KEY)
        expected = f"# my keys\r\nOTHER='x y'\n{VAR}={KEY}\nexport LAST=1"
        self.assertEqual(self.file.read_bytes(), expected.encode("utf-8"))

    def test_key_appended_when_absent(self) -> None:
        self.seed("# c\nOTHER=1")
        write_env_key(self.file, KEY)
        self.assertEqual(self.file.read_bytes(), f"# c\nOTHER=1\n{VAR}={KEY}\n".encode())

    def test_later_key_lines_dropped_and_crlf_kept(self) -> None:
        self.seed(f"A=1\r\n# {VAR}=comment\r\n{VAR}=old\r\nB=2\r\nexport {VAR}=older\r\n")
        write_env_key(self.file, KEY)
        expected = f"A=1\r\n# {VAR}=comment\r\n{VAR}={KEY}\r\nB=2\r\n"
        self.assertEqual(self.file.read_bytes(), expected.encode("utf-8"))

    def test_existing_world_readable_file_ends_private(self) -> None:
        self.seed("A=1\n")
        os.chmod(self.file, 0o644)
        write_env_key(self.file, KEY)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)

    def test_modes_on_a_fresh_directory(self) -> None:
        write_env_key(self.file, KEY)
        self.assertEqual(stat.S_IMODE(self.file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.cfg.stat().st_mode), 0o700)

    def assert_refused(self, code: str, key: str = KEY) -> None:
        with self.assertRaises(ValidationError) as caught:
            write_env_key(self.file, key)
        self.assertEqual(caught.exception.code, code)
        if key:
            self.assertNotIn(key, caught.exception.message)

    def test_symlinked_file_refused(self) -> None:
        self.seed("")
        target = self.dir / "elsewhere"
        target.write_text("", encoding="utf-8")
        self.file.unlink()
        self.file.symlink_to(target)
        self.assert_refused("env_file_refused")
        self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_symlinked_parent_refused(self) -> None:
        real = self.dir / "real"
        real.mkdir()
        self.cfg.parent.mkdir()
        self.cfg.symlink_to(real)
        self.assert_refused("env_file_refused")
        self.assertEqual(list(real.iterdir()), [])

    def test_invalid_keys_refused(self) -> None:
        bad_keys = ("", "a b", "a\tb", "a\nb", "a\x00b", "a\x7fb", "k ", "x" * 513,
                    "é" * 257, "key\U0001f511", "ключ", '"abc"', "'abc'")  # fmt: skip
        for bad in bad_keys:
            with self.subTest(key=repr(bad)[:20]):
                self.assert_refused("jev_key_invalid", bad)
        self.assertFalse(self.file.exists())

    def test_longest_key_accepted(self) -> None:
        write_env_key(self.file, "x" * 512)

    def test_failed_replace_leaves_old_file_and_no_temp(self) -> None:
        self.seed(f"{VAR}=old\n")
        with mock.patch("os.replace", side_effect=OSError("boom")), self.assertRaises(OSError):
            write_env_key(self.file, KEY)
        self.assertEqual(self.file.read_text(encoding="utf-8"), f"{VAR}=old\n")
        self.assertEqual([p.name for p in self.cfg.iterdir()], [FILE_NAME])


class KeySetCommandTest(_Case):
    def run_cli(self, stdin: io.TextIOBase) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with (
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
            mock.patch.object(sys, "stdin", stdin),
        ):
            code = cli.main(["--lang", "en", "jev", "key", "set"])
        return code, out.getvalue(), err.getvalue()

    def test_writes_key_and_never_prints_it(self) -> None:
        code, out, err = self.run_cli(io.StringIO(KEY + "\n"))
        self.assertEqual(code, 0, err)
        self.assertNotIn(KEY, out + err)
        payload = json.loads(out)
        self.assertEqual(payload, {"written": str(self.file), "key_source": "env_file",
                                   "usable": True})  # fmt: skip
        self.assertEqual(resolve_api_key({}, self.file, lambda: None), ApiKey(KEY, "env_file"))

    def test_env_var_shadows_the_written_key(self) -> None:
        with mock.patch.dict(os.environ, {VAR: "ts-env-key"}):
            code, out, err = self.run_cli(io.StringIO(KEY + "\n"))
        self.assertEqual(code, 0, err)
        self.assertNotIn(KEY, out + err)
        self.assertNotIn("ts-env-key", out + err)
        payload = json.loads(out)
        self.assertEqual((payload["key_source"], payload["shadowed_by_env"]), ("env", True))

    def test_undecodable_stdin_refused(self) -> None:
        stdin = io.TextIOWrapper(io.BytesIO(b"ab\xffcd\n"), encoding="utf-8")
        code, out, err = self.run_cli(stdin)
        self.assertEqual(code, 2)
        self.assertIn("jev_key_invalid", out + err)
        self.assertFalse(self.file.exists())

    def test_only_the_trailing_newline_is_stripped(self) -> None:
        code, out, err = self.run_cli(io.StringIO(KEY + " \n"))
        self.assertEqual(code, 2)
        self.assertNotIn(KEY, out + err)
        self.assertFalse(self.file.exists())

    def test_tty_stdin_refused(self) -> None:
        code, out, err = self.run_cli(_TtyStdin(KEY + "\n"))
        self.assertEqual(code, 2)
        self.assertIn("pipe", out + err)
        self.assertFalse(self.file.exists())


if __name__ == "__main__":
    unittest.main()
