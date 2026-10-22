"""Docker helpers for the container scenarios: the daemon probe, the e2e image, and a Host that
runs the core checks inside a container with the clone mounted read-only at /src."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Sequence

from tests.e2e._support import ROOT, Done, Tree, mcp_tool_count, run

BUILD_TIMEOUT = 1800.0
DOCKERFILE = ROOT / "docker" / "e2e" / "Dockerfile"


def daemon_problem() -> str | None:
    """None when the Docker daemon answers; else the reason every check is skipped with."""
    try:
        done = run(["docker", "info", "--format", "{{.ServerVersion}}"], 30, os.environ)
    except OSError as exc:
        return f"docker daemon not running ({exc})"
    if done.exit == 0:
        return None
    first = next((line for line in done.output.splitlines() if line.strip()), "no output")
    return f"docker daemon not running ({first.strip()})"


def short_sha() -> str:
    done = subprocess.run(  # noqa: S603, S607 - fixed argv
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return done.stdout.strip() or "unknown"


def build_image() -> str:
    """Build wev-e2e:<short sha> from docker/e2e/Dockerfile; raise when the build fails."""
    tag = f"wev-e2e:{short_sha()}"
    argv = ["docker", "build", "-t", tag, "-f", str(DOCKERFILE), str(DOCKERFILE.parent)]
    done = run(argv, BUILD_TIMEOUT, os.environ)
    if done.exit != 0:
        raise RuntimeError(f"docker build failed ({done.exit}):\n{done.output[-1500:]}")
    return tag


class ContainerHost:
    """A long-running container; each command is a `docker exec` as the non-root user."""

    source = "/src"
    tree: Tree | None = None

    def __init__(self, image: str) -> None:
        self.name = f"wev-e2e-{os.getpid()}"
        argv = ["docker", "run", "-d", "--rm", "--name", self.name, "-v", f"{ROOT}:/src:ro"]
        done = run([*argv, image, "sleep", "infinity"], 120, os.environ)
        if done.exit != 0:
            raise RuntimeError(f"docker run failed ({done.exit}):\n{done.output[-1500:]}")

    def stop(self) -> None:
        run(["docker", "rm", "-f", self.name], 60, os.environ)

    def _exec(self, argv: Sequence[str], timeout: float) -> Done:
        return run(["docker", "exec", self.name, *argv], timeout, os.environ)

    def _sh(self, script: str, timeout: float = 60) -> Done:
        return self._exec(["bash", "-c", script], timeout)

    def run_wev(self, args: Sequence[str], timeout: float) -> Done:
        return self._exec(["python3", "/src/bin/wev", *args], timeout)

    def run_install(self, args: Sequence[str], timeout: float) -> Done:
        return self._exec(["bash", "/src/install.sh", *args], timeout)

    def tool_count(self, timeout: float) -> int:
        argv = ["docker", "exec", "-i", self.name, "python3", "/src/bin/wev", "rea", "serve"]
        return mcp_tool_count(argv, os.environ, timeout)

    def home_entries(self) -> frozenset[str]:
        done = self._sh('cd "$HOME" && find . -mindepth 1')
        return frozenset(line.removeprefix("./") for line in done.output.splitlines() if line)

    def exists(self, what: str) -> bool:
        paths = {"data": ".local/share/wev-skills", "config": ".config/wev-skills"}
        rel = what.removeprefix("home:") if what.startswith("home:") else paths[what]
        return self._sh(f'test -e "$HOME/{rel}"').exit == 0

    def state_file(self) -> str:
        return '"$HOME/.local/share/wev-skills/third-party/state.json"'

    def read_state(self) -> str:
        return self._sh(f"cat {self.state_file()}").output

    def write_state(self, text: str) -> None:
        self._sh(f"printf %s {shlex.quote(text)} > {self.state_file()}")
