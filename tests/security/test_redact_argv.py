from __future__ import annotations

import time
import unittest

from tests.security.test_redact import (
    ALNUM,
    BASIC,
    DISCORD_HOOK,
    SHORT,
    SLACK_HOOK,
    TEAMS_HOOK,
    TIME_BOUND_SECONDS,
    VENDOR_TOKENS,
)
from wev_skills.security.redact import MARKER, redact_argv


class RedactArgvTests(unittest.TestCase):
    def test_secret_flag_values(self) -> None:
        for flag in (
            "--password",
            "--passwd",
            "--pass",
            "--pw",
            "--token",
            "--secret",
            "--api-key",
            "--apikey",
            "--auth",
            "--access-key",
            "--private-key",
            "--db-password",
            "--client-secret",
            "--PASSWORD",
            "-password",
        ):
            with self.subTest(flag=flag):
                self.assertEqual(
                    redact_argv(["tool", flag, SHORT, "run"]), ("tool", flag, MARKER, "run")
                )
                self.assertEqual(
                    redact_argv(["tool", f"{flag}={SHORT}", "run"]),
                    ("tool", f"{flag}={MARKER}", "run"),
                )

    def test_value_with_spaces_or_dashes_is_one_token(self) -> None:
        self.assertEqual(
            redact_argv(["tool", "--password", f"two words {SHORT}", "x"]),
            ("tool", "--password", MARKER, "x"),
        )
        self.assertEqual(
            redact_argv(["tool", "--token", f"mid-dle-{SHORT}"]), ("tool", "--token", MARKER)
        )
        self.assertEqual(
            redact_argv(["tool", "--password", "--verbose", "x"]),
            ("tool", "--password", "--verbose", "x"),
        )

    def test_flags_whose_value_is_not_the_secret_are_left(self) -> None:
        for argv in (
            ("docker", "login", "--password-stdin", "registry"),
            ("tool", "--token-file", "/run/secrets/t"),
            ("git", "log", "--author", "ana"),
            ("tool", "--passes", "3"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(redact_argv(argv), argv)

    def test_client_password_flags(self) -> None:
        cases: dict[tuple[str, ...], tuple[str, ...]] = {
            ("mysql", "-u", "root", "-p", SHORT, "db"): ("mysql", "-u", "root", "-p", MARKER, "db"),
            ("mysql", "-uroot", f"-p{SHORT}", "db"): ("mysql", "-uroot", f"-p{MARKER}", "db"),
            ("/usr/local/bin/mysqldump", f"-p{SHORT}"): ("/usr/local/bin/mysqldump", f"-p{MARKER}"),
            ("mariadb", "-p", SHORT): ("mariadb", "-p", MARKER),
            ("sshpass", "-p", SHORT, "ssh", "host"): ("sshpass", "-p", MARKER, "ssh", "host"),
            ("sudo", "sshpass", f"-p{SHORT}", "ssh", "h"): (
                "sudo",
                "sshpass",
                f"-p{MARKER}",
                "ssh",
                "h",
            ),
            ("docker", "login", "-u", "bob", "-p", SHORT, "reg"): (
                "docker",
                "login",
                "-u",
                "bob",
                "-p",
                MARKER,
                "reg",
            ),
            ("podman", "login", f"-p{SHORT}", "reg"): ("podman", "login", f"-p{MARKER}", "reg"),
            ("redis-cli", "-a", SHORT, "ping"): ("redis-cli", "-a", MARKER, "ping"),
            ("MYSQL.EXE", "-p", SHORT): ("MYSQL.EXE", "-p", MARKER),
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(redact_argv(argv), expected)

    def test_p_flag_of_other_programs_is_left(self) -> None:
        for argv in (
            ("ls", "-p"),
            ("grep", "-p", "mysql"),
            ("tar", "-pxf", "a.tar"),
            ("mkdir", "-p", "a/b"),
            ("docker", "run", "-p", "8080:80", "nginx"),
            ("ssh", "-p", "2222", "host"),
            ("cp", "-a", "src", "dst"),
            ("echo", "-p", "x", "mysql"),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(redact_argv(argv), argv)

    def test_curl_and_wget_user_credentials_keep_the_user(self) -> None:
        url = "https://x.example/a"
        cases: dict[tuple[str, ...], tuple[str, ...]] = {
            ("curl", "-u", f"admin:{SHORT}", url): ("curl", "-u", f"admin:{MARKER}", url),
            ("curl", "--user", f"admin:{SHORT}", url): ("curl", "--user", f"admin:{MARKER}", url),
            ("curl", f"--user=admin:{SHORT}", url): ("curl", f"--user=admin:{MARKER}", url),
            ("curl", f"-uadmin:{SHORT}", url): ("curl", f"-uadmin:{MARKER}", url),
            ("curl", "--proxy-user", f"p:{SHORT}", url): (
                "curl",
                "--proxy-user",
                f"p:{MARKER}",
                url,
            ),
            ("curl", f"--proxy-user=p:{SHORT}", url): ("curl", f"--proxy-user=p:{MARKER}", url),
            ("wget", "--user", f"u:{SHORT}", url): ("wget", "--user", f"u:{MARKER}", url),
            ("/usr/bin/curl", "-u", f"a:{SHORT}:{SHORT}"): ("/usr/bin/curl", "-u", f"a:{MARKER}"),
            ("curl", "-u", "ana", url): ("curl", "-u", "ana", url),
            ("git", "-u", f"a:{SHORT}"): ("git", "-u", f"a:{SHORT}"),
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(redact_argv(argv), expected)

    def test_sensitive_headers(self) -> None:
        for name in (
            "Authorization",
            "Proxy-Authorization",
            "X-Api-Key",
            "X-Auth-Token",
            "X-Auth",
            "Cookie",
        ):
            for value in (f"Basic {BASIC}", SHORT):
                for argv in (
                    ["curl", "-H", f"{name}: {value}", "https://x"],
                    ["curl", "--header", f"{name}: {value}", "https://x"],
                    ["curl", f"--header={name}: {value}", "https://x"],
                    ["curl", f"-H{name}:{value}", "https://x"],
                ):
                    with self.subTest(argv=argv):
                        result = redact_argv(argv)
                        self.assertEqual(len(result), len(argv))
                        self.assertNotIn(value.split()[-1], " ".join(result))
                        self.assertIn(name, " ".join(result))
                        self.assertEqual(result[-1], "https://x")
        plain = ("curl", "-H", "Accept: application/json", "https://x")
        self.assertEqual(redact_argv(plain), plain)

    def test_url_tokens_and_webhooks(self) -> None:
        argv = [
            "curl",
            f"https://ci:{SHORT}@git.example/acme/repo.git",
            f"https://{ALNUM}@git.example/r",
            f"https://x.example/cb?access_token={SHORT}&x=1",
            f"https://x.example/b?sv=1&sig={SHORT}",
            SLACK_HOOK,
            DISCORD_HOOK,
            TEAMS_HOOK,
            VENDOR_TOKENS["hugging_face"],
            f"PASSWORD={SHORT}",
        ]
        result = redact_argv(argv)
        self.assertEqual(len(result), len(argv))
        self.assertEqual(result[0], "curl")
        for token in result[1:]:
            with self.subTest(token=token[:30]):
                self.assertIn(MARKER, token)
                self.assertNotIn(SHORT, token)
                self.assertNotIn(ALNUM, token)
        self.assertEqual(result[3], f"https://x.example/cb?access_token={MARKER}&x=1")

    def test_same_length_idempotent_and_does_not_mutate(self) -> None:
        samples: list[list[str]] = [
            ["tool", "--password", SHORT],
            ["mysql", f"-p{SHORT}"],
            ["curl", "-u", f"a:{SHORT}"],
            ["curl", "-H", f"Authorization: Bearer {ALNUM}"],
            ["tool", f"--token={SHORT}"],
            ["sshpass", "-p", SHORT, "ssh", "-p", "22", "h"],
            ["tool", "--password"],
            [],
            ["ls"],
            ["redis-cli", "-a"],
            ["curl", "-u"],
            ["x", "", " ", "--", "-", "--=", "-p"],
        ]
        for argv in samples:
            with self.subTest(argv=argv):
                copy = list(argv)
                once = redact_argv(argv)
                self.assertEqual(argv, copy)
                self.assertIsInstance(once, tuple)
                self.assertEqual(len(once), len(argv))
                self.assertEqual(redact_argv(once), once)
                self.assertNotIn(SHORT, " ".join(once))

    def test_never_raises(self) -> None:
        odd: list[object] = [
            None,
            42,
            "curl -u a:b",
            b"bytes",
            [None, 1, b"x"],
            ("--password",),
            [["nested"]],
            iter(["tool", "--password", SHORT]),
            ["\x00", "\ud800"],
            ["--password", None],
        ]
        for value in odd:
            with self.subTest(value=repr(value)[:30]):
                result = redact_argv(value)  # type: ignore[arg-type]
                self.assertIsInstance(result, tuple)
                self.assertTrue(all(isinstance(token, str) for token in result))
        self.assertEqual(redact_argv(["--password", None]), ("--password", MARKER))  # type: ignore[list-item]
        self.assertEqual(redact_argv(iter(["t", "--pw", SHORT])), ("t", "--pw", MARKER))  # type: ignore[arg-type]

    def test_stays_fast_on_many_tokens(self) -> None:
        argv = ["mysql", *(["-p", "x", "--password", "y", "-u", "a:b"] * 20_000)]
        started = time.monotonic()
        result = redact_argv(argv)
        self.assertLess(time.monotonic() - started, TIME_BOUND_SECONDS)
        self.assertEqual(len(result), len(argv))


if __name__ == "__main__":
    unittest.main()
