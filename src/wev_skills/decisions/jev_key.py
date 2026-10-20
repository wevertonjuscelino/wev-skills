"""Where the JEV API key comes from: the environment, the user's env file, the keychain.

The key is read, never written, and never printed: ``ApiKey`` keeps it out of its ``repr``.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import user_config_home
from wev_skills.decisions.jev_wire import JevUnavailable

ENV_VAR = "TYPESAFE_API_KEY"
KEYCHAIN_SERVICE = "typesafe-api-key"
ENV_FILE_NAME = ".env"
SECURITY_PROGRAM = "/usr/bin/security"
KEYCHAIN_TIMEOUT_SECONDS = 10
GROUP_OTHER_BITS = 0o077
EXPORT_PREFIX = "export "


@dataclass(frozen=True)
class ApiKey:
    value: str = field(repr=False)
    source: str
    """``env``, ``env_file`` or ``keychain``."""


def env_file_path() -> Path:
    return user_config_home() / ENV_FILE_NAME


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    name, _, value = text.partition("=")
    name = name.strip().removeprefix(EXPORT_PREFIX).strip()
    return name, _unquote(value.strip())


def read_env_file(path: Path) -> dict[str, str]:
    """The ``NAME=value`` pairs of ``path``; refuses a file other users can read."""
    try:
        if path.stat().st_mode & GROUP_OTHER_BITS:
            raise JevUnavailable(
                "env_file_insecure", i18n.t("decisions.jev.why.env_file_insecure", path=str(path))
            )
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise JevUnavailable(
            "env_file_unreadable", i18n.t("decisions.jev.why.env_file_unreadable", path=str(path))
        ) from exc
    pairs = (_parse_line(line) for line in text.splitlines())
    return dict(pair for pair in pairs if pair is not None)


def macos_keychain() -> str | None:
    if sys.platform != "darwin":
        return None
    command = [SECURITY_PROGRAM, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=KEYCHAIN_TIMEOUT_SECONDS,
        )
    except OSError, subprocess.SubprocessError:
        return None
    if done.returncode != 0:
        return None
    return done.stdout.rstrip("\r\n") or None


def resolve_api_key(
    env: Mapping[str, str], env_file: Path, keychain: Callable[[], str | None]
) -> ApiKey | None:
    if env.get(ENV_VAR):
        return ApiKey(env[ENV_VAR], "env")
    try:
        from_file = read_env_file(env_file).get(ENV_VAR)
    except FileNotFoundError:
        from_file = None
    if from_file:
        return ApiKey(from_file, "env_file")
    from_keychain = keychain()
    return ApiKey(from_keychain, "keychain") if from_keychain else None
