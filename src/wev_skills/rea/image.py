"""Building and probing the ``wev-rea:<version>`` image. Docker runs through a ``Runner``."""

from __future__ import annotations

from pathlib import Path

from wev_skills import i18n
from wev_skills.core.errors import RemoteError
from wev_skills.core.ports import Runner
from wev_skills.rea.launch import IMAGE_PREFIX, checked_version
from wev_skills.security.redact import redact

BUILD_TIMEOUT = 1800.0
INFO_TIMEOUT = 10.0
PROBE_TIMEOUT = 10.0
DOCKERFILE_DIR = Path("docker") / "rea"
STDERR_LINES = 15


def image_tag(version: str) -> str:
    return f"{IMAGE_PREFIX}:{checked_version(version)}"


def build_image(version: str, runner: Runner, docker: str, repo_root: Path) -> str:
    tag = image_tag(version)
    context = repo_root / DOCKERFILE_DIR
    argv = [
        docker, "build", "--build-arg", f"REA_VERSION={version}", "-t", tag,
        "-f", str(context / "Dockerfile"), str(context),
    ]  # fmt: skip
    result = runner.run(argv, None, BUILD_TIMEOUT, None)
    if result.exit_code != 0:
        tail = "\n".join(result.stderr.splitlines()[-STDERR_LINES:])
        raise RemoteError(
            "rea_image_build_failed", i18n.t("rea.error.build_failed", tag=tag, stderr=redact(tail))
        )
    return tag


def image_present(tag: str, runner: Runner, docker: str) -> bool:
    result = runner.run([docker, "image", "inspect", tag], None, PROBE_TIMEOUT, None)
    return result.exit_code == 0


def docker_available(runner: Runner, docker: str) -> bool:
    return runner.run([docker, "info"], None, INFO_TIMEOUT, None).exit_code == 0
