"""docker/e2e/Dockerfile: a stock Python 3.14 image, no pipe-to-shell installs, a non-root user."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

TEXT = (Path(__file__).resolve().parents[2] / "docker" / "e2e" / "Dockerfile").read_text()
LINES = [line.strip() for line in TEXT.splitlines() if not line.strip().startswith("#")]


class E2eDockerfileTests(unittest.TestCase):
    def test_it_starts_from_python_3_14_slim(self) -> None:
        self.assertEqual(
            next(line for line in LINES if line.startswith("FROM")), "FROM python:3.14-slim"
        )

    def test_nothing_is_piped_into_a_shell(self) -> None:
        self.assertIsNone(re.search(r"\|\s*(ba|z)?sh\b", TEXT))
        self.assertNotIn("ADD http", TEXT)

    def test_the_last_user_is_not_root(self) -> None:
        users = [line.split()[1] for line in LINES if line.startswith("USER ")]
        self.assertTrue(users)
        self.assertNotIn(users[-1], ("root", "0"))

    def test_it_installs_the_stock_dependencies_and_holds_no_secret(self) -> None:
        for package in ("git", "curl", "nodejs", "npm"):
            self.assertRegex(TEXT, rf"\b{package}\b")
        self.assertIsNone(re.search(r"(?i)\b(ARG|ENV)\s+\w*(KEY|TOKEN|SECRET|PASSWORD)", TEXT))


if __name__ == "__main__":
    unittest.main()
