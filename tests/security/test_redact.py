from __future__ import annotations

import json
import time
import unittest

from wev_skills.security.redact import MARKER, redact, redact_argv, redact_mapping

# Every secret-looking or hash-looking fixture is assembled at runtime from fragments,
# so no realistic credential literal is ever stored in the repository.
ALNUM = "aB3dE5gH7jK9" + "mN1pQ2sT4vW6xY8z"
PEM_HEAD = "-----BEGIN " + "RSA PRIVATE" + " KEY-----"
PEM_TAIL = "-----END " + "RSA PRIVATE" + " KEY-----"
PEM = f"{PEM_HEAD}\nMIIE{ALNUM}\n{ALNUM}==\n{PEM_TAIL}"
AWS_ID = "AK" + "IA" + "EXAMPLE" + "FAKE" + "12345"
GITHUB = {prefix + "_": prefix + "_" + ALNUM + "0011223344" for prefix in ("ghp", "gho", "ghs")}
GITHUB_PAT = "github_" + "pat_" + ALNUM + "_" + ALNUM
SLACK = "xox" + "b-" + "123456789012-" + ALNUM
SK_STYLE = "sk" + "-" + ALNUM * 2
SK_VENDOR_STYLE = "sk" + "-" + "ant-" + "api03-" + ALNUM
JWT = ".".join(("ey" + "J" + ALNUM, "ey" + "J" + ALNUM[::-1], ALNUM[:20] + "-_x"))
PASSWORD = "example_" + "Tr0ub4dor" + "And3horse"
HEX40 = "9fceb02d0a" * 4
HEX64 = "e3b0c442" * 8
SHORT = "hunt" + "er2" + "Xq"
BASIC = "YWRt" + "aW46" + "ZXhhbXBsZV9mYWtl"
PK_WORDS = "PRIV" + "ATE KEY"
DASHES = "-" * 5
TIME_BOUND_SECONDS = 3.0
ADVERSARIAL_SIZE = 200_000


def pem(kind: str, newline: str = "\n", block: str = "", body: str = "MIIE" + ALNUM) -> str:
    head = f"{DASHES}BEGIN {kind}{PK_WORDS}{block}{DASHES}"
    tail = f"{DASHES}END {kind}{PK_WORDS}{block}{DASHES}"
    return f"{head}{newline}{body}{newline}{ALNUM}=={newline}{tail}"


VENDOR_TOKENS = {
    "stripe_secret": "sk" + "_live_" + ALNUM,
    "stripe_restricted": "rk" + "_live_" + ALNUM,
    "stripe_test": "sk" + "_test_" + ALNUM,
    "stripe_webhook": "wh" + "sec_" + ALNUM,
    "anthropic": "sk" + "-ant-" + "api03-" + ALNUM,
    "openai_project": "sk" + "-proj-" + ALNUM,
    "hugging_face": "hf" + "_" + ALNUM,
    "google_oauth": "ya" + "29." + ALNUM + "-" + ALNUM,
    "sendgrid": "SG" + "." + ALNUM[:22] + "." + ALNUM + ALNUM[:15],
    "digitalocean": "dop" + "_v1_" + HEX64,
    "pypi": "pypi" + "-AgEI" + ALNUM + ALNUM,
    "npm": "npm" + "_" + ALNUM + ALNUM[:8],
}
SLACK_HOOK = "https://hooks." + "slack.com/services/" + "T00000000/B00000000/" + ALNUM
DISCORD_HOOK = "https://discord" + ".com/api/webhooks/" + "123456789012345678/" + ALNUM + "-_x"
TEAMS_HOOK = (
    "https://acme.webhook." + "office.com/webhookb2/" + ALNUM + "@" + ALNUM + "/IncomingWebhook/x"
)


class RedactPatternTests(unittest.TestCase):
    def assert_masked(self, text: str, *secrets: str) -> str:
        result = redact(text)
        for secret in secrets:
            self.assertNotIn(secret, result, text)
        self.assertIn(MARKER, result, text)
        return result

    def test_pem_private_key_block(self) -> None:
        result = self.assert_masked(f"key follows\n{PEM}\nafter", ALNUM, "MIIE")
        self.assertEqual(result, f"key follows\n{MARKER}\nafter")

    def test_truncated_pem_block_is_masked_to_the_end(self) -> None:
        self.assert_masked(f"log: {PEM_HEAD}\nMIIE{ALNUM}", ALNUM)

    def test_authorization_headers(self) -> None:
        url = "https://api.example.com"
        for header in (
            f"Authorization: Bearer {ALNUM}",
            f"authorization: basic {ALNUM}==",
            f'curl -H "Authorization: Bearer {ALNUM}" {url}',
            f"Proxy-Authorization: Basic {ALNUM}",
            f'{{"Authorization": "Bearer {ALNUM}"}}',
            f"sent header bearer {ALNUM}",
        ):
            with self.subTest(header=header):
                self.assert_masked(header, ALNUM)
        self.assertIn(url, redact(f'-H "Authorization: Bearer {ALNUM}" {url}'))

    def test_token_formats(self) -> None:
        tokens = [AWS_ID, *GITHUB.values(), GITHUB_PAT, SLACK, SK_STYLE, SK_VENDOR_STYLE, JWT]
        for token in tokens:
            for text in (token, f"using {token} now", f"({token})", f"x={token}", f'"{token}"'):
                with self.subTest(text=text):
                    self.assert_masked(text, token)

    def test_secret_named_assignments(self) -> None:
        secret = PASSWORD
        lines = (
            f"PASSWORD={secret}", f"export DB_PASSWORD='{secret}'", f"password: {secret}",
            f'"password": "{secret}"', f"api_key = {secret}", f"API-KEY: {secret}",
            f"client_secret={secret}", f"AWS_SECRET_ACCESS_KEY={secret}", f"token={secret}",
            f"access_token: {secret}", f"private_key='{secret}'", f"apikey={secret}",
            f"https://example.com/cb?token={secret}&next=/home", f"passwd={secret}",
            f"session_id={secret}", f"--password {secret}", f"--api-key={secret}",
            f"db_pwd={secret}", f"Cookie: sid={secret}; theme=dark",
            f"Set-Cookie: sid={secret}; HttpOnly",
        )  # fmt: skip
        for line in lines:
            with self.subTest(line=line):
                self.assert_masked(line, secret)

    def test_assignment_keeps_the_key_and_surrounding_text(self) -> None:
        self.assertEqual(
            redact(f"user=ana password={PASSWORD} host=db1"), f"user=ana password={MARKER} host=db1"
        )
        self.assertEqual(
            redact(f"/cb?token={PASSWORD}&next=/home"), f"/cb?token={MARKER}&next=/home"
        )
        quoted = json.loads(redact(json.dumps({"password": PASSWORD, "user": "ana"})))
        self.assertEqual(quoted, {"password": MARKER, "user": "ana"})

    def test_password_embedded_in_url(self) -> None:
        for url in (
            f"postgres://admin:{PASSWORD}@db.internal:5432/app",
            f"https://ci:{PASSWORD}@github.com/acme/repo.git",
            f"DATABASE_URL=redis://:{PASSWORD}@cache:6379/0",
        ):
            with self.subTest(url=url):
                result = self.assert_masked(url, PASSWORD)
                self.assertIn("@", result)
        self.assertEqual(redact(f"mysql://root:{PASSWORD}@h/db"), f"mysql://root:{MARKER}@h/db")

    def test_multiple_secrets_in_one_text(self) -> None:
        text = f"id={AWS_ID} gh={GITHUB['ghp_']}\npassword={PASSWORD}\n{PEM}\njwt {JWT}"
        self.assert_masked(text, AWS_ID, GITHUB["ghp_"], PASSWORD, ALNUM, JWT)


class RedactSafetyTests(unittest.TestCase):
    ORDINARY = (
        "2026-10-13 12:00:01 INFO request_id=ab12cd34 status=200 path=/api/users duration=12ms",
        f"commit {HEX40}",
        f"Merge 3f2a1b4 into {HEX40} (HEAD -> main)",
        f"sha256:{HEX64}",
        "Ran 42 tests in 0.31s -- OK (tokens_used=1500, max_tokens: 4096, token_count=7)",
        "PWD=/home/ana/project OLDPWD=/home/ana",
        "GET https://example.com:8443/path?page=2&sort=asc HTTP/1.1",
        "git@github.com:acme/repo.git and https://github.com/acme/repo.git",
        "The tokenizer splits text; basic authentication is described in the docs.",
        "Use the bearer authentication scheme; the bearer of this note may enter.",
        "File \"src/app.py\", line 12, in main\n    raise ValueError('bad input')",
        "task-list-2026-10-13-final-version-with-a-long-name.md",
        "uuid 123e4567-e89b-12d3-a456-426614174000",
        "",
    )

    def test_ordinary_text_is_left_intact(self) -> None:
        for text in self.ORDINARY:
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)

    def test_is_idempotent(self) -> None:
        secret = PASSWORD
        samples = [
            PEM, f"Authorization: Bearer {ALNUM}", AWS_ID, GITHUB_PAT, SLACK, SK_STYLE, JWT,
            f"password={secret}", f'"api_key": "{secret}"', f"--token {secret}",
            f"postgres://u:{secret}@h/db", f"Cookie: a={secret}; b=2", f"bearer {ALNUM}",
            f"token: bearer {ALNUM}", f"password='{secret}' secret=\"{secret}\"",
            f"a {PEM_HEAD} unterminated {ALNUM}", *self.ORDINARY,
        ]  # fmt: skip
        samples.append("\n".join(samples))
        for text in samples:
            with self.subTest(text=text[:40]):
                once = redact(text)
                self.assertEqual(redact(once), once)

    def test_never_raises(self) -> None:
        inputs: list[object] = [
            "\x00\xff",
            "\ud800 lone surrogate",
            "=" * 1000,
            ":" * 1000,
            "password=",
            "password:",
            "://:@",
            PEM_HEAD,
            None,
            42,
            b"bytes",
            ["password=x"],
            "é" * 50 + "token=ção",
        ]
        for value in inputs:
            with self.subTest(value=repr(value)[:30]):
                self.assertIsInstance(redact(value), str)  # type: ignore[arg-type]

    def test_hostile_input_stays_fast(self) -> None:
        hostile = (
            "a." * 20000,
            "password" * 5000,
            "://" * 10000,
            "--" + "token-" * 5000,
            "eyJ" * 10000,
            "token=" * 10000,
            "x" * 200000,
        )
        started = time.monotonic()
        for text in hostile:
            redact(text)
        self.assertLess(time.monotonic() - started, 5.0)


class RedactFalsePositiveTests(unittest.TestCase):
    ORDINARY = (
        "git log --author=x",
        "git log --author x --oneline",
        "ls -p",
        "ls -p /tmp/dir",
        "grep -p pattern file",
        "token_count=5",
        "https://example.com/a?page=2",
        "https://example.com/a?page=2&sort=asc&keyword=x#frag",
        "tar -pxf a.tar",
        "docker run -p 8080:80 nginx",
        "ssh -p 2222 host",
        "mkdir -p a/b/c && cd a",
        "cp -a src dst",
        "curl -sS https://example.com/health",
        "curl -u ana https://example.com",
        "scp -P 22 a ana@host:/tmp",
        "http://host:8080/path/user@example.com",
        "mailto ana@example.com from https://example.com/x",
        "tests: 12 pass, 0 fail (pass=12 fail=0)",
        "PWD=/home/ana/project OLDPWD=/home/ana",
        "primary_key=id sort_key=name public_key=ssh-ed25519",
        "keyboard=us monkey=yes passenger=2 bypass=true compass: north",
        "authored by ana; authentication: enabled; auth_type=basic",
        "fix auth: handle refresh (see docs/auth.md); auth is required",
        "docker login --password-stdin registry.example.com",
        "tool --token-file /run/secrets/t --verbose",
        "-----BEGIN CERTIFICATE-----\nMIIBxyz\n-----END CERTIFICATE-----",
        "-----BEGIN PUBLIC KEY-----\nMIIBxyz\n-----END PUBLIC KEY-----",
        "a secret is something you keep; the password policy changed",
        "hf_hub and sk-learn and npm_config_cache are names",
        "x-ray: clear; X-Request-Id: 12345; Accept: */*",
    )

    def test_text_without_secrets_is_unchanged(self) -> None:
        for text in self.ORDINARY:
            with self.subTest(text=text):
                self.assertEqual(redact(text), text)

    def test_argv_without_secrets_is_unchanged(self) -> None:
        for text in self.ORDINARY:
            argv = tuple(text.split())
            with self.subTest(argv=argv):
                self.assertEqual(redact_argv(argv), argv)


class RedactPerformanceTests(unittest.TestCase):
    ADVERSARIAL = {
        "password": "password" * 25_000,
        "password_eq": "password=" * 22_000,
        "password_quote": 'password="' * 20_000,
        "scheme": "a://" * 50_000,
        "scheme_colon": "a://b:" * 34_000,
        "url_colon": ("http://" + "a" * 250) * 800,
        "dashes": "--" * 100_000,
        "dash_words": "--a" * 67_000,
        "dashdash_password": ("--" + "a" * 40 + "password" + "b" * 40) * 2_200,
        "flag_p": "-p " * 67_000,
        "flag_px": "mysql " + "-px " * 50_000,
        "flag_u": "curl " + "-u a:b " * 28_000,
        "curl": "curl " * 40_000,
        "cookie": "cookie:" * 28_000,
        "authorization": "authorization:" * 14_000,
        "x_header": "x-" * 100_000,
        "x_header_words": "x-a-b-c-d-key" * 15_000,
        "jwt": "eyJ" * 66_000,
        "jwt_dots": ("eyJ" + "a" * 60 + ".") * 3_000,
        "token_tail": ("token" + "a" * 64) * 3_000,
        "query": "?key=" * 40_000,
        "amp": "&" * ADVERSARIAL_SIZE,
        "begin": (DASHES + "BEGIN ") * 18_000,
        "pem_open": (DASHES + "BEGIN " + PK_WORDS + DASHES + "\n") * 6_000,
        "pem_body": DASHES + "BEGIN " + PK_WORDS + DASHES + ("\n" + "A" * 64) * 3_000,
        "bearer": "bearer " * 28_000,
        "sk": "sk-" * 66_000,
        "hooks": "https://hooks." * 14_000,
        "a_run": "a" * ADVERSARIAL_SIZE,
        "dash_run": "-" * ADVERSARIAL_SIZE,
        "quote_run": '"' * ADVERSARIAL_SIZE,
        "backslash_run": "\\" * ADVERSARIAL_SIZE,
        "colon_run": ":" * ADVERSARIAL_SIZE,
        "at_run": "@" * ADVERSARIAL_SIZE,
        "newline_run": "\n" * ADVERSARIAL_SIZE,
        "space_run": " " * ADVERSARIAL_SIZE,
        "underscore_key": "_key" * 50_000,
    }

    def test_each_adversarial_input_stays_fast(self) -> None:
        for name, text in self.ADVERSARIAL.items():
            with self.subTest(name=name):
                sized = text[:ADVERSARIAL_SIZE]
                started = time.monotonic()
                result = redact(sized)
                self.assertLess(time.monotonic() - started, TIME_BOUND_SECONDS)
                self.assertIsInstance(result, str)

    def test_idempotent_on_adversarial_and_mixed_input(self) -> None:
        mixed = "\n".join(
            (
                f"mysql -uroot -p{SHORT} db",
                f"curl -u a:{SHORT} -H 'X-Api-Key: {SHORT}' {SLACK_HOOK}",
                pem("PGP ", block=" BLOCK"),
                f"https://u:pa/{SHORT}@h/db?sig={SHORT}&code={SHORT}",
                f'--password "{SHORT} x" --token {SHORT}',
                *VENDOR_TOKENS.values(),
                f"senha: {SHORT}",
                f'"{{\\"password\\": \\"{SHORT}\\"}}"',
                f'password="{SHORT}',
            )
        )
        samples = [mixed, *(text[:5_000] for text in self.ADVERSARIAL.values())]
        for text in samples:
            with self.subTest(text=text[:30]):
                once = redact(text)
                self.assertEqual(redact(once), once)
        self.assertNotIn(SHORT, redact(mixed))


class RedactMappingTests(unittest.TestCase):
    def test_masks_secret_named_keys_and_redacts_string_values(self) -> None:
        source = {
            "user": "ana", "password": PASSWORD, "API_KEY": 12345, "Authorization": None,
            "note": f"used {SK_STYLE}", "count": 3, "tokens_used": 1500,
            "nested": {"session_cookie": "abc", "items": [f"token={PASSWORD}", 7]},
            "private_key": {"kty": "RSA"},
        }  # fmt: skip
        result = redact_mapping(source)
        self.assertEqual(result, {
            "user": "ana", "password": MARKER, "API_KEY": MARKER, "Authorization": MARKER,
            "note": f"used {MARKER}", "count": 3, "tokens_used": 1500,
            "nested": {"session_cookie": MARKER, "items": [f"token={MARKER}", 7]},
            "private_key": MARKER,
        })  # fmt: skip

    def test_returns_a_new_dict_and_leaves_the_source_alone(self) -> None:
        inner = {"token": PASSWORD}
        source = {"inner": inner, "list": [inner]}
        result = redact_mapping(source)
        self.assertIsNot(result, source)
        self.assertEqual(source, {"inner": {"token": PASSWORD}, "list": [{"token": PASSWORD}]})
        self.assertEqual(result, {"inner": {"token": MARKER}, "list": [{"token": MARKER}]})

    def test_deep_or_cyclic_structures_do_not_raise(self) -> None:
        cyclic: dict[str, object] = {"name": "loop"}
        cyclic["self"] = cyclic
        result = redact_mapping(cyclic)
        self.assertEqual(result["name"], "loop")
        self.assertIn(MARKER, json.dumps(result))
        odd = {1: "a", ("t",): f"password={PASSWORD}"}
        masked = redact_mapping(odd)  # type: ignore[arg-type]
        self.assertEqual(masked, {1: "a", ("t",): f"password={MARKER}"})


if __name__ == "__main__":
    unittest.main()
