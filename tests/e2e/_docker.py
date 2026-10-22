"""Docker helpers for the container scenarios: the daemon probe, the e2e image, and a Host that
runs the core checks inside a container with the clone mounted read-only at /src."""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence

from tests.e2e._support import ROOT, Done, Tree, mcp_tool_count, run

BUILD_TIMEOUT = 1800.0
DOCKERFILE = ROOT / "docker" / "e2e" / "Dockerfile"
CONTEXT_HOST = '{{(index .Endpoints "docker").Host}}'
XDG = {  # outside HOME, the same layout as the isolated tree on the Mac
    "XDG_CONFIG_HOME": "/tmp/wev-xdg/config",
    "XDG_DATA_HOME": "/tmp/wev-xdg/data",
    "XDG_STATE_HOME": "/tmp/wev-xdg/state",
}
EXEC_GRACE = 30.0  # the client waits this much longer than the in-container `timeout`


def docker_env(env: Mapping[str, str]) -> dict[str, str]:
    """`env` plus DOCKER_HOST from the account's current Docker context. An isolated HOME hides
    ~/.docker, and with it the Docker Desktop socket; this puts the endpoint back (and only it)."""
    if "DOCKER_HOST" in env:
        return dict(env)
    done = run(["docker", "context", "inspect", "--format", CONTEXT_HOST], 30, os.environ)
    host = done.output.strip()
    return {**env, "DOCKER_HOST": host} if done.exit == 0 and "://" in host else dict(env)


def daemon_problem(env: Mapping[str, str] | None = None) -> str | None:
    """None when the Docker daemon answers (probed with `env`, the one the checks use); else
    the reason every check is skipped with."""
    try:
        done = run(["docker", "info", "--format", "{{.ServerVersion}}"], 30, env or os.environ)
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


def _env_flags() -> list[str]:
    return [flag for k, v in XDG.items() for flag in ("-e", f"{k}={v}")]


class ContainerHost:
    """A long-running container; each command is a `docker exec` as the non-root user, under
    `timeout` inside the container so a hung command does not outlive the client."""

    source = "/src"
    tree: Tree | None = None

    def __init__(self, image: str) -> None:
        self.name = f"wev-e2e-{os.getpid()}"
        mount = f"type=bind,src={ROOT},dst=/src,readonly"
        argv = ["docker", "run", "-d", "--rm", "--name", self.name, "--mount", mount]
        argv += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
        done = run([*argv, image, "sleep", "7200"], 120, os.environ)
        if done.exit != 0:
            raise RuntimeError(f"docker run failed ({done.exit}):\n{done.output[-1500:]}")
        made = self._sh("mkdir -p " + " ".join(shlex.quote(v) for v in XDG.values()))
        if made.exit != 0:
            self.stop()
            raise RuntimeError(f"could not create the XDG directories:\n{made.output}")

    def stop(self) -> None:
        run(["docker", "rm", "-f", self.name], 60, os.environ)

    def _wrapped(self, argv: Sequence[str], timeout: float, stdin: bool = False) -> list[str]:
        front = ["docker", "exec", *(["-i"] if stdin else []), *_env_flags(), self.name]
        return [*front, "timeout", "--kill-after=5", str(int(timeout)), *argv]

    def _exec(self, argv: Sequence[str], timeout: float) -> Done:
        return run(self._wrapped(argv, timeout), timeout + EXEC_GRACE, os.environ)

    def _sh(self, script: str, timeout: float = 60) -> Done:
        return self._exec(["bash", "-c", script], timeout)

    def run_wev(self, args: Sequence[str], timeout: float) -> Done:
        return self._exec(["python3", "/src/bin/wev", *args], timeout)

    def run_install(self, args: Sequence[str], timeout: float) -> Done:
        return self._exec(["bash", "/src/install.sh", *args], timeout)

    def tool_count(self, timeout: float) -> int:
        argv = self._wrapped(["python3", "/src/bin/wev", "rea", "serve"], timeout, stdin=True)
        return mcp_tool_count(argv, os.environ, timeout)

    def home_entries(self) -> frozenset[str]:
        done = self._sh('cd "$HOME" && find . -mindepth 1')
        return frozenset(line.removeprefix("./") for line in done.output.splitlines() if line)

    def exists(self, what: str) -> bool:
        if what.startswith("home:"):
            quoted = '"$HOME"/' + shlex.quote(what.removeprefix("home:"))
        else:
            base = XDG["XDG_DATA_HOME" if what == "data" else "XDG_CONFIG_HOME"]
            quoted = shlex.quote(f"{base}/wev-skills")
        return self._sh(f"test -e {quoted}").exit == 0

    def state_file(self) -> str:
        return shlex.quote(f"{XDG['XDG_DATA_HOME']}/wev-skills/third-party/state.json")

    def read_state(self) -> str:
        return self._sh(f"cat {self.state_file()}").output

    def write_state(self, text: str) -> None:
        done = self._sh(f"printf %s {shlex.quote(text)} > {self.state_file()}")
        if done.exit != 0:
            raise RuntimeError(f"could not write the state file:\n{done.output}")
