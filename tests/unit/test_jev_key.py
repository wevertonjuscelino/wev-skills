"""Resolution of the JEV key: environment, then the user's env file, then the keychain.

Nothing here reads the real environment or the real keychain: the home and config
directories point at temporary directories and the keychain is a lambda.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.decisions import jev_key
from wev_skills.decisions.jev_key import ApiKey, resolve_api_key
from wev_skills.decisions.jev_wire import JevUnavailable

VAR = "TYPESAFE_API_KEY"
FILE_NAME = "." + "env"


class ResolveApiKeyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.dir), "XDG_CONFIG_HOME": str(self.dir / "cfg")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.file = self.dir / FILE_NAME

    def write(self, text: str, mode: int = 0o600) -> Path:
        self.file.write_text(text, encoding="utf-8")
        os.chmod(self.file, mode)
        return self.file

    def test_env_var_wins_over_file_and_keychain(self) -> None:
        self.write(f"{VAR}=k-file\n")
        found = resolve_api_key({VAR: "k-env"}, self.file, lambda: "k-chain")
        self.assertEqual(found, ApiKey("k-env", "env"))

    def test_file_used_when_env_missing(self) -> None:
        self.write(f"{VAR}=k-file\n")
        found = resolve_api_key({}, self.file, lambda: "k-chain")
        self.assertEqual(found, ApiKey("k-file", "env_file"))

    def test_keychain_used_last(self) -> None:
        found = resolve_api_key({}, self.file, lambda: "k-chain")
        self.assertEqual(found, ApiKey("k-chain", "keychain"))

    def test_none_when_nothing_found(self) -> None:
        self.assertIsNone(resolve_api_key({}, self.file, lambda: None))

    def test_env_file_formats(self) -> None:
        cases = {
            f'# c\n\nexport {VAR}="k1"\r\n': "k1",
            f"{VAR}='k2'\n": "k2",
            f"{VAR} = k3 \n": "k3",
        }
        for text, expected in cases.items():
            with self.subTest(expected=expected):
                self.write(text)
                found = resolve_api_key({}, self.file, lambda: None)
                self.assertEqual(found, ApiKey(expected, "env_file"))

    def test_insecure_env_file_refused(self) -> None:
        self.write(f"{VAR}=k-file\n", mode=0o644)
        with self.assertRaises(JevUnavailable) as caught:
            resolve_api_key({}, self.file, lambda: "k-chain")
        self.assertEqual(caught.exception.code, "env_file_insecure")
        self.assertIn(str(self.file), str(caught.exception))
        self.assertIn("chmod 600", str(caught.exception))

    def test_missing_env_file_is_not_an_error(self) -> None:
        found = resolve_api_key({}, self.dir / "absent", lambda: "k-chain")
        self.assertEqual(found, ApiKey("k-chain", "keychain"))

    def test_unreadable_env_file_is_jev_unavailable(self) -> None:
        self.file.mkdir(mode=0o700)  # a directory where the file should be
        undecodable = self.dir / "binary"
        undecodable.write_bytes(b"\xff\xfe\x00")
        os.chmod(undecodable, 0o600)
        unreadable = self.dir / "noread"
        unreadable.write_text(f"{VAR}=k\n", encoding="utf-8")
        os.chmod(unreadable, 0o200)
        for path in (self.file, undecodable, unreadable):
            with self.subTest(path=path.name):
                if path is unreadable and os.geteuid() == 0:
                    self.skipTest("root can read anything")
                with self.assertRaises(JevUnavailable) as caught:
                    resolve_api_key({}, path, lambda: "k-chain")
                self.assertEqual(caught.exception.code, "env_file_unreadable")
                self.assertIn(str(path), str(caught.exception))

    def test_env_file_path_is_under_the_user_config_home(self) -> None:
        self.assertEqual(jev_key.env_file_path(), self.dir / "cfg" / "wev-skills" / FILE_NAME)

    def test_repr_hides_key(self) -> None:
        self.assertNotIn("k-env", repr(ApiKey("k-env", "env")))

    def test_keychain_off_darwin_is_none(self) -> None:
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch("subprocess.run", side_effect=AssertionError("must not run")),
        ):
            self.assertIsNone(jev_key.macos_keychain())


if __name__ == "__main__":
    unittest.main()
