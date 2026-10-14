"""Tests for scripts/scan_secrets.py. Fabricated keys are built at runtime from fragments."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scan_secrets.py"


def _load():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("scan_secrets", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = _load()

FAKE_AWS = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
FAKE_PEM = "-" * 5 + "BEGIN RSA PRIVATE" + " KEY" + "-" * 5
FAKE_GH = "gh" + "p_" + "a" * 36


class ScanTextTests(unittest.TestCase):
    def test_flags_aws_key_id(self) -> None:
        self.assertEqual(scan.scan_text(f"id = {FAKE_AWS}"), [(1, "aws-access-key-id")])

    def test_flags_pem_header(self) -> None:
        self.assertEqual(scan.scan_text("x\n" + FAKE_PEM), [(2, "pem-private-key")])

    def test_flags_github_token(self) -> None:
        self.assertEqual(scan.scan_text(FAKE_GH), [(1, "github-token")])

    def test_clean_text_passes(self) -> None:
        text = "Use an environment variable for the token.\nAKIA is a prefix.\nghp_short\n"
        self.assertEqual(scan.scan_text(text), [])


class ScanTreeTests(unittest.TestCase):
    def test_tree_scan_flags_outside_tests_and_skips_tests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "fixture.txt").write_text(FAKE_AWS)
            (root / "src.txt").write_text(FAKE_AWS)
            (root / "clean.txt").write_text("nothing here")
            self.assertEqual(scan.scan_tree(root), ["src.txt:1: aws-access-key-id"])

    def test_main_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("clean")
            self.assertEqual(scan.main(["x", str(root)]), 0)
            (root / "b.txt").write_text(FAKE_PEM)
            self.assertEqual(scan.main(["x", str(root)]), 1)

    def test_script_does_not_match_itself(self) -> None:
        self.assertEqual(scan.scan_text(SCRIPT.read_text()), [])


R30 = "aB3dE6gH9jK2mN5pQ8sT1vW4yZ7cF0"
R35 = R30 + "hJ3kL"
R40 = R30 + "hJ3kL6nP9r"
DASHES = "-" * 5


def _names(text: str) -> list[str]:
    return [name for _, name in scan.scan_text(text)]


def _pem(kind: str) -> str:
    return DASHES + "BEGIN " + kind + "PRIVATE" + " KEY" + DASHES


SAMPLES: dict[str, str] = {
    "pgp-private-key": DASHES + "BEGIN PGP PRIVATE" + " KEY BLOCK" + DASHES,
    "putty-private-key": "PuTTY" + "-User-Key" + "-File-3: ssh-rsa",
    "aws-access-key-id": "AS" + "IA" + "ABCDEFGHIJKLMNOP",
    "google-api-key": "AI" + "za" + R35,
    "google-oauth-token": "ya" + "29." + R30,
    "github-token": "gh" + "p_" + R30,
    "github-fine-grained-token": "github" + "_pat_" + R30,
    "gitlab-token": "gl" + "pat-" + R30[:20],
    "slack-token": "xo" + "xb-1234567890-" + R30[:24],
    "stripe-key": "sk" + "_live_" + R30,
    "stripe-restricted-key": "rk" + "_live_" + R30,
    "stripe-webhook-secret": "wh" + "sec_" + R30,
    "model-api-key": "sk" + "-" + R40,
    "anthropic-key": "sk" + "-ant-api03-" + R40,
    "model-project-key": "sk" + "-proj-" + R40,
    "npm-token": "npm" + "_" + R30 + "hJ3kL6",
    "pypi-token": "pypi" + "-AgEI" + R40,
    "huggingface-token": "hf" + "_" + R35,
    "sendgrid-key": "SG" + "." + R30 + "." + R40,
    "digitalocean-token": "dop" + "_v1_" + "ab12" * 10,
    "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0." + "abcDEF123_-xyz456",
    "url-credentials": "https://" + "admin:" + R30[:16] + "@db.internal.test/app",
    "webhook-url-slack": "https://hooks." + "slack.com/services/T01234567/B01234567/" + R30[:24],
    "webhook-url-discord": "https://discord." + "com/api/webhooks/123456789012345678/" + R40,
    "generic-secret-assignment-quoted": 'api_key: "' + R30 + '"',
    "generic-secret-assignment-env": "DB_" + "PASSWORD=" + R30[:24],
    "generic-secret-assignment-single": "secret = '" + R30 + "'",
}


class PatternCoverageTests(unittest.TestCase):
    def test_every_sample_is_reported(self) -> None:
        for label, sample in SAMPLES.items():
            with self.subTest(label=label):
                self.assertTrue(_names(f"x = 1\n{sample}\n"), label)

    def test_private_key_kinds(self) -> None:
        for kind in ("", "RSA ", "EC ", "DSA ", "OPENSSH ", "ENCRYPTED "):
            with self.subTest(kind=kind):
                self.assertIn("pem-private-key", _names(_pem(kind)))

    def test_pgp_and_putty_names(self) -> None:
        self.assertIn("pgp-private-key", _names(SAMPLES["pgp-private-key"]))
        self.assertIn("putty-private-key", _names(SAMPLES["putty-private-key"]))

    def test_github_token_with_thirty_trailing_characters(self) -> None:
        self.assertIn("github-token", _names("gh" + "p_" + R30))

    def test_findings_never_include_values(self) -> None:
        for sample in SAMPLES.values():
            for _, name in scan.scan_text(sample):
                self.assertNotIn(R30[:12], name)


class PlaceholderTests(unittest.TestCase):
    def test_placeholders_are_not_flagged(self) -> None:
        clean = [
            'password = "changeme"',
            'secret = "${SECRET_VALUE_FROM_ENV_1}"',
            "token: <your-token-goes-here-123>",
            'api_key = "xxxxxxxxxxxxxxxxxxxx"',
            'api_key = "example-api-key-1234567890"',
            "url = https://user:password@host/path",
            "url = https://user:${DB_PASS}@host/path",
            'secret = "abc123"',
            'password = "aaaaaaaaaaaaaaaaaaaaaa1"',
            'token = os.environ["API_TOKEN_NAME_X1"]',
            'token_url = "https://example.test/oauth/token"',
        ]
        for line in clean:
            with self.subTest(line=line):
                self.assertEqual(scan.scan_text(line), [])

    def test_entropy_helper(self) -> None:
        self.assertEqual(scan.shannon_entropy("aaaa"), 0.0)
        self.assertGreater(scan.shannon_entropy(R30), 3.5)


class FileHandlingTests(unittest.TestCase):
    def test_walk_fallback_skips_untracked_noise_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for sub in ("a/__pycache__", ".wev", ".remember"):
                (root / sub).mkdir(parents=True)
                (root / sub / "n.txt").write_text(SAMPLES["github-token"])
            self.assertEqual(scan.scan_tree(root), [])

    def test_oversize_file_scans_head_and_tail_and_reports_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = b"abcdefghi\n" * 200_000 + b"\n" + SAMPLES["github-token"].encode()
            (root / "big.txt").write_bytes(body)
            report = scan.scan_report(root)
            self.assertEqual(report.findings, ["big.txt:200002: github-token"])
            self.assertEqual(report.truncated, ["big.txt"])

    def test_utf16_with_bom_is_decoded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, codec in (("le.txt", "utf-16"), ("be.txt", "utf-16-be")):
                data = ("x\n" + SAMPLES["github-token"]).encode(codec)
                if codec == "utf-16-be":
                    data = b"\xfe\xff" + data
                (root / name).write_bytes(data)
            self.assertEqual(
                scan.scan_tree(root), ["be.txt:2: github-token", "le.txt:2: github-token"]
            )

    def test_summary_counts_skipped_tests_and_hides_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "f.txt").write_text(SAMPLES["github-token"])
            (root / "a.txt").write_text(SAMPLES["github-token"])
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = scan.main(["x", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("1 file(s) under tests/ skipped", out.getvalue())
            self.assertNotIn(R30, out.getvalue())


@unittest.skipUnless(shutil.which("git"), "git not available")
class ReviewNineCasesTests(unittest.TestCase):
    def test_planted_cases(self) -> None:
        gh = SAMPLES["github-token"]
        aws = SAMPLES["aws-access-key-id"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files: dict[str, bytes] = {
                "control.txt": gh.encode(),
                "tests/fixtures/token.txt": gh.encode(),
                "src/pkg/__pycache__/notes.txt": gh.encode(),
                "docs/.wev/creds.txt": aws.encode(),
                "docs/.remember/creds.txt": aws.encode(),
                "big.bin.txt": b"abcdefghi\n" * 200_000 + b"\n" + gh.encode(),
                "utf16.txt": ("x\n" + gh).encode("utf-16"),
                "env.txt": SAMPLES["generic-secret-assignment-env"].encode(),
                "ant.txt": SAMPLES["anthropic-key"].encode(),
                "slack.txt": SAMPLES["slack-token"].encode(),
                "gitlab.txt": SAMPLES["gitlab-token"].encode(),
                "pgp.txt": SAMPLES["pgp-private-key"].encode(),
                "short.txt": ("gh" + "p_" + R30).encode(),
            }
            for rel, data in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            report = scan.scan_report(root)
            reported = {line.split(":")[0] for line in report.findings}
            expected = set(files) - {"tests/fixtures/token.txt"}
            self.assertEqual(reported, expected)
            self.assertEqual(report.skipped_tests, 1)


class StagedModeTests(unittest.TestCase):
    def _repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    def _stage(self, root: Path, *names: str) -> None:
        subprocess.run(["git", "add", "--", *names], cwd=root, check=True)

    def test_staged_files_lists_only_added_and_modified_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root)
            (root / "staged.txt").write_text("a")
            (root / "unstaged.txt").write_text("b")
            self._stage(root, "staged.txt")
            self.assertEqual(scan.staged_files(root), ["staged.txt"])

    def test_staged_scan_ignores_secrets_in_files_that_are_not_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root)
            (root / "ok.txt").write_text("clean")
            (root / "later.txt").write_text(FAKE_AWS)
            self._stage(root, "ok.txt")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(scan.main(["x", "--staged", str(root)]), 0)

    def test_staged_scan_fails_on_a_staged_secret_without_printing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo(root)
            (root / "leak.txt").write_text(FAKE_AWS)
            self._stage(root, "leak.txt")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(scan.main(["x", "--staged", str(root)]), 1)
            self.assertIn("leak.txt:1: aws-access-key-id", out.getvalue())
            self.assertNotIn(FAKE_AWS, out.getvalue())

    def test_staged_scan_outside_a_repository_fails_instead_of_passing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(scan.main(["x", "--staged", tmp]), 2)
            self.assertIn("cannot list staged files", err.getvalue())


if __name__ == "__main__":
    unittest.main()
