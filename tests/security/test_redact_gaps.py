from __future__ import annotations

import json
import unittest

from tests.security.test_redact import (
    ALNUM,
    BASIC,
    DASHES,
    DISCORD_HOOK,
    HEX40,
    PK_WORDS,
    SHORT,
    SLACK_HOOK,
    TEAMS_HOOK,
    VENDOR_TOKENS,
    pem,
)
from wev_skills.security.redact import MARKER, SECRET_NAME, redact, redact_mapping

# Like the fixtures it imports, every secret-looking value here is built at runtime.


class RedactGapTests(unittest.TestCase):
    """Each case was a leak found by the security review."""

    def assert_masked(self, text: str, *secrets: str) -> str:
        result = redact(text)
        for secret in secrets:
            self.assertNotIn(secret, result, text)
        self.assertIn(MARKER, result, text)
        self.assertEqual(redact(result), result, f"not idempotent: {text!r}")
        return result

    def test_authorization_headers_with_any_scheme(self) -> None:
        for line in (
            f"Authorization: Basic {BASIC}",
            f"Proxy-Authorization: Basic {BASIC}",
            f"curl -H 'Authorization: Basic {BASIC}' https://x.example",
            f"Authorization: Negotiate {BASIC}",
            f"authorization: AWS4-HMAC-SHA256 Credential=x/y, Signature={BASIC}",
            f'Authorization: Digest username="ana", response="{BASIC}"',
            f"Authorization: {BASIC}",
            f'{{"authorization": "Custom {BASIC}"}}',
            f'"{{\\"Authorization\\": \\"Basic {BASIC}\\"}}"',
        ):
            with self.subTest(line=line):
                self.assert_masked(line, BASIC)
        kept = redact(f"curl -H 'Authorization: Basic {BASIC}' https://x.example/a")
        self.assertIn("https://x.example/a", kept)
        self.assertEqual(redact(f"Authorization: Basic {BASIC}"), f"Authorization: {MARKER}")

    def test_api_key_style_headers(self) -> None:
        for name in (
            "X-Api-Key",
            "x-api-key",
            "X-Auth-Token",
            "X-Auth",
            "X-Vault-Token",
            "X-Amz-Security-Token",
            "X-Goog-Api-Key",
            "X-Hub-Signature",
        ):
            for line in (f"{name}: {SHORT}", f'curl -H "{name}: {SHORT}" https://x.example'):
                with self.subTest(line=line):
                    self.assert_masked(line, SHORT)

    def test_token_like_url_query_parameters(self) -> None:
        for name in (
            "token",
            "access_token",
            "api_key",
            "key",
            "sig",
            "signature",
            "secret",
            "password",
            "code",
            "auth",
            "X-Amz-Signature",
            "refresh_token",
        ):
            url = f"https://x.example/cb?v=2020&{name}={SHORT}&next=/home"
            with self.subTest(name=name):
                self.assertEqual(
                    self.assert_masked(url, SHORT),
                    f"https://x.example/cb?v=2020&{name}={MARKER}&next=/home",
                )
        self.assert_masked(f"GET /cb?code={SHORT} HTTP/1.1", SHORT)

    def test_webhook_urls(self) -> None:
        for url in (SLACK_HOOK, DISCORD_HOOK, TEAMS_HOOK):
            with self.subTest(url=url[:30]):
                result = self.assert_masked(f"notify {url} done", ALNUM)
                self.assertTrue(result.startswith("notify https://"))
                self.assertTrue(result.endswith(" done"))

    def test_credentials_in_urls(self) -> None:
        slashed = "pa/ss" + SHORT
        cases = {
            f"postgres://user:{slashed}@host/db": f"postgres://user:{MARKER}@host/db",
            f"https://{ALNUM}@github.com/o/r.git": f"https://{MARKER}@github.com/o/r.git",
            f"SENTRY_DSN=https://{HEX40}@o1.ingest.example/1": None,
            f"amqps://svc:{SHORT}/{SHORT}@mq.internal:5671/vhost": None,
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                result = self.assert_masked(url, SHORT, ALNUM, HEX40)
                if expected is not None:
                    self.assertEqual(result, expected)

    def test_split_flag_values_in_text(self) -> None:
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
            "--client_secret",
            "-password",
        ):
            for text in (
                f"tool {flag} {SHORT} run",
                f"tool {flag}={SHORT} run",
                f'tool {flag} "{SHORT} two words" run',
            ):
                with self.subTest(text=text):
                    result = self.assert_masked(text, SHORT, "two words")
                    self.assertTrue(result.startswith(f"tool {flag}"))
                    self.assertTrue(result.endswith(" run"))

    def test_client_password_flags_in_text(self) -> None:
        cases = {
            f"mysql -u root -p {SHORT} db": f"mysql -u root -p {MARKER} db",
            f"mysql -uroot -p{SHORT} db": f"mysql -uroot -p{MARKER} db",
            f"/usr/bin/mysqldump -h db -p{SHORT} app": f"/usr/bin/mysqldump -h db -p{MARKER} app",
            f"mariadb -p{SHORT}": f"mariadb -p{MARKER}",
            f"sshpass -p {SHORT} ssh host": f"sshpass -p {MARKER} ssh host",
            f"docker login -u bob -p {SHORT} reg": f"docker login -u bob -p {MARKER} reg",
            f"podman login -p{SHORT} reg": f"podman login -p{MARKER} reg",
            f"redis-cli -a {SHORT} ping": f"redis-cli -a {MARKER} ping",
            f"curl -u admin:{SHORT} https://x": f"curl -u admin:{MARKER} https://x",
            f"curl --user admin:{SHORT} https://x": f"curl --user admin:{MARKER} https://x",
            f"curl --user=admin:{SHORT} https://x": f"curl --user=admin:{MARKER} https://x",
            f"curl -s --proxy-user p:{SHORT} https://x": f"curl -s --proxy-user p:{MARKER} https://x",
            f"wget --user u:{SHORT} https://x": f"wget --user u:{MARKER} https://x",
            f"$ curl -sS -u 'admin:{SHORT}' https://x": f"$ curl -sS -u 'admin:{MARKER}' https://x",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.assert_masked(text, SHORT), expected)

    def test_vendor_token_prefixes(self) -> None:
        for name, token in VENDOR_TOKENS.items():
            for text in (token, f"using {token} now", f"({token})", f'"{token}"'):
                with self.subTest(name=name, text=text[:20]):
                    self.assert_masked(text, token, token[-12:])

    def test_private_key_block_kinds_and_line_breaks(self) -> None:
        blocks = {
            "rsa": pem("RSA "),
            "plain": pem(""),
            "openssh": pem("OPENSSH "),
            "ec": pem("EC "),
            "encrypted": pem("ENCRYPTED "),
            "pgp": pem("PGP ", block=" BLOCK"),
            "crlf": pem("RSA ", newline="\r\n"),
            "json_escaped": pem("", newline="\\n"),
            "json_escaped_crlf": pem("", newline="\\r\\n"),
            "lowercase": pem("RSA ").lower(),
            "with_headers": pem(
                "RSA ", body="Proc-Type: 4,ENCRYPTED\nDEK-Info: AES,0A\n\nMIIE" + ALNUM
            ),
        }
        for name, block in blocks.items():
            with self.subTest(name=name):
                result = self.assert_masked(f"before {block} after", ALNUM, "MIIE", ALNUM.lower())
                self.assertTrue(result.startswith("before "))
                self.assertTrue(result.endswith(" after"))
        quoted = json.loads(redact(json.dumps({"key": pem(""), "user": "ana"})))
        self.assertEqual(quoted, {"key": MARKER, "user": "ana"})

    def test_private_key_without_end_line_keeps_the_text_after_the_block(self) -> None:
        head = f"{DASHES}BEGIN RSA {PK_WORDS}{DASHES}"
        text = f"{head}\nMIIE{ALNUM}\n{ALNUM}==\nlater unrelated log line KEEPME\nand more text"
        result = self.assert_masked(text, ALNUM, "MIIE")
        self.assertEqual(result, f"{MARKER}\nlater unrelated log line KEEPME\nand more text")
        self.assertEqual(redact(f"see {head} for details"), f"see {MARKER} for details")

    def test_quoted_values_with_other_or_escaped_quotes(self) -> None:
        tail = "SECRET" + "TAIL"
        for text in (
            f'export DB_PASSWORD="ab\'cd {tail}"',
            f"password='ab\"cd {tail}'",
            f'{{"password": "ab\\"cd {tail}"}}',
            f'{{"password": "it\'s {tail}"}}',
            f'{{"password": "correct horse {tail}"}}',
            f'"{{\\"password\\": \\"ab {tail}\\"}}"',
        ):
            with self.subTest(text=text):
                self.assert_masked(text, tail)
        self.assertEqual(
            json.loads(redact(json.dumps({"password": f'a"b {tail}', "user": "ana"}))),
            {"password": MARKER, "user": "ana"},
        )

    def test_more_secret_names(self) -> None:
        for line in (
            f"ENCRYPTION_KEY={SHORT}",
            f"SIGNING_KEY: {SHORT}",
            f"OPENAI_KEY={SHORT}",
            f"AccountName=x;AccountKey={SHORT}==;",
            f"SharedAccessKeyName=n;SharedAccessKey={SHORT}",
            f"//registry.example.org/:_authToken={SHORT}",
            f"//registry.example.org/:_auth={SHORT}",
            f"senha: {SHORT}",
            f"senha={SHORT}",
            f"chave={SHORT}",
            f"pass={SHORT}",
            f"pwd={SHORT}",
            f"DB_PWD={SHORT} ; pwd: {SHORT}",
            f"DB_PASS={SHORT}",
            f"AUTH={SHORT}",
            f"AZURE_CLIENT_SECRET={SHORT}",
            f'"private_key_id": "{SHORT}"',
            f"password => {SHORT}",
        ):
            with self.subTest(line=line):
                self.assert_masked(line, SHORT)
        for name in (
            "ENCRYPTION_KEY",
            "signing-key",
            "accountkey",
            "SharedAccessKey",
            "_authToken",
            "senha",
            "chave",
            "db_pass",
        ):
            with self.subTest(name=name):
                self.assertIsNotNone(SECRET_NAME.search(name))

    def test_mapping_masks_bare_secret_names(self) -> None:
        source = {
            "pwd": SHORT,
            "senha": SHORT,
            "auth": SHORT,
            "pass": SHORT,
            "_auth": SHORT,
            "encryption_key": SHORT,
            "passwd": SHORT,
            "author": "ana",
            "key": "name",
            "token_count": 5,
            "primary_key": "id",
            "public_key": "ssh-ed25519 AAAA",
        }
        result = redact_mapping(source)
        for name in ("pwd", "senha", "auth", "pass", "_auth", "encryption_key", "passwd"):
            with self.subTest(name=name):
                self.assertEqual(result[name], MARKER)
        for name in ("author", "key", "token_count", "primary_key", "public_key"):
            with self.subTest(name=name):
                self.assertEqual(result[name], source[name])


if __name__ == "__main__":
    unittest.main()
