"""Building and probing the ``wev-rea`` image through a fake Runner."""

from __future__ import annotations

import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path

from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import RemoteError, ValidationError
from wev_skills.rea import image


class FakeRunner:
    def __init__(self, code: int | None = 0, stderr: str = "") -> None:
        self.code, self.stderr = code, stderr
        self.calls: list[tuple[tuple[str, ...], float | None]] = []

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None,
        timeout: float | None,
        env: Mapping[str, str] | None,
    ) -> RawCommandResult:
        self.calls.append((tuple(argv), timeout))
        return RawCommandResult(tuple(argv), self.code, "", self.stderr, 1)


class ImageTests(unittest.TestCase):
    def test_tag(self) -> None:
        self.assertEqual(image.image_tag("6.7.0"), "wev-rea:6.7.0")
        for bad in ("latest", "6.7", "6.7.0 && x", ""):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                image.image_tag(bad)

    def test_build_argv_is_exact(self) -> None:
        runner = FakeRunner()
        root = Path("/repo")
        tag = image.build_image("6.7.0", runner, "/bin/docker", root)
        self.assertEqual(tag, "wev-rea:6.7.0")
        argv, timeout = runner.calls[0]
        self.assertEqual(
            argv,
            (
                "/bin/docker", "build", "--build-arg", "REA_VERSION=6.7.0", "-t", "wev-rea:6.7.0",
                "-f", "/repo/docker/rea/Dockerfile", "/repo/docker/rea",
            ),
        )  # fmt: skip
        self.assertEqual(timeout, image.BUILD_TIMEOUT)

    def test_build_failure_carries_redacted_stderr(self) -> None:
        secret = "ghp_" + "a" * 36
        lines = [f"line {n}" for n in range(30)]
        runner = FakeRunner(1, "\n".join([*lines, f"token {secret}"]))
        with self.assertRaises(RemoteError) as ctx:
            image.build_image("6.7.0", runner, "docker", Path("/repo"))
        self.assertEqual(ctx.exception.code, "rea_image_build_failed")
        message = ctx.exception.message
        self.assertNotIn(secret, message)
        self.assertIn("line 29", message)
        self.assertNotIn("line 0\n", message)

    def test_build_timeout_is_a_failure(self) -> None:
        with self.assertRaises(RemoteError):
            image.build_image("6.7.0", FakeRunner(None), "docker", Path("/repo"))

    def test_build_refuses_a_bad_version_without_running(self) -> None:
        runner = FakeRunner()
        with self.assertRaises(ValidationError):
            image.build_image("latest", runner, "docker", Path("/repo"))
        self.assertEqual(runner.calls, [])

    def test_probes(self) -> None:
        for code, expected in ((0, True), (1, False), (None, False)):
            with self.subTest(code=code):
                present = FakeRunner(code)
                self.assertIs(image.image_present("wev-rea:6.7.0", present, "d"), expected)
                self.assertEqual(present.calls[0][0], ("d", "image", "inspect", "wev-rea:6.7.0"))
                self.assertEqual(present.calls[0][1], 10.0)
                up = FakeRunner(code)
                self.assertIs(image.docker_available(up, "d"), expected)
                self.assertEqual(up.calls[0], (("d", "info"), 10.0))


if __name__ == "__main__":
    unittest.main()
