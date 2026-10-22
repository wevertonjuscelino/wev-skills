"""Text checks on ``docker/rea/Dockerfile``: the image carries Node and rea only."""

from __future__ import annotations

import unittest
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[2] / "docker" / "rea" / "Dockerfile"


class DockerfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = [
            line.strip()
            for line in DOCKERFILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_base_version_and_install(self) -> None:
        self.assertEqual(self.lines[0], "FROM node:24-slim")
        self.assertIn("ARG REA_VERSION", self.lines)
        self.assertIn("RUN npm install -g rea-agents@${REA_VERSION}", self.lines)

    def test_runs_as_a_non_root_user_with_the_mounted_home(self) -> None:
        users = [line for line in self.lines if line.startswith("USER ")]
        self.assertEqual(users, ["USER rea"])
        self.assertIn("ENV HOME=/opt/rea-home", self.lines)
        self.assertLess(self.lines.index("USER rea"), self.lines.index('ENTRYPOINT ["rea","mcp"]'))

    def test_entrypoint_is_the_mcp_server(self) -> None:
        self.assertEqual(self.lines[-1], 'ENTRYPOINT ["rea","mcp"]')

    def test_no_downloads_shells_or_secrets(self) -> None:
        text = DOCKERFILE.read_text(encoding="utf-8").lower()
        for banned in (
            "curl",
            "wget",
            "sh -c",
            "| sh",
            "| bash",
            "\nadd ",
            "apt-get",
            "token",
            "password",
        ):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, text)

    def test_only_the_expected_instructions(self) -> None:
        kinds = {line.split()[0] for line in self.lines}
        self.assertLessEqual(kinds, {"FROM", "ARG", "RUN", "ENV", "USER", "ENTRYPOINT"})


if __name__ == "__main__":
    unittest.main()
