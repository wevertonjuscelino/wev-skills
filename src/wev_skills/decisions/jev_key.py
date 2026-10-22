"""Where the JEV API key comes from: the environment, the user's env file, the keychain.

The key is never printed: ``ApiKey`` keeps it out of its ``repr``. Only ``write_env_key``
(``wev jev key set``, run by the person) writes it.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wev_skills import i18n
from wev_skills.config import user_config_home
from wev_skills.core.errors import ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.decisions.jev_wire import JevUnavailable

ENV_VAR = "TYPESAFE_API_KEY"
KEYCHAIN_SERVICE = "typesafe-api-key"
ENV_FILE_NAME = ".env"
SECURITY_PROGRAM = "/usr/bin/security"
KEYCHAIN_TIMEOUT_SECONDS = 10
GROUP_OTHER_BITS = 0o077
EXPORT_PREFIX = "export "
MAX_KEY_BYTES = 512


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


def _check_key(key: str) -> None:
    # ASCII: the HTTP header must be latin-1; a quoted key would read back without its quotes.
    readable = key.isascii() and key.isprintable() and _unquote(key) == key
    if not key or len(key) > MAX_KEY_BYTES or not readable or any(ch.isspace() for ch in key):
        raise ValidationError("jev_key_invalid", i18n.t("decisions.jev.key_invalid"))


def _with_key(text: str, key: str) -> str:
    """``text`` with its first ``ENV_VAR`` line set to ``key`` and later ones dropped (or one
    appended); every other line is kept, and so is the replaced line's ending."""
    lines = text.splitlines(keepends=True)
    hits = [i for i, old in enumerate(lines) if (_parse_line(old) or ("", ""))[0] == ENV_VAR]
    if not hits:
        return text + ("\n" if text and not text.endswith("\n") else "") + f"{ENV_VAR}={key}\n"
    first = lines[hits[0]]
    ending = "\r\n" if first.endswith("\r\n") else "\n"
    kept = [old for i, old in enumerate(lines) if i not in hits[1:]]
    kept[hits[0]] = f"{ENV_VAR}={key}{ending}"
    return "".join(kept)


def write_env_key(path: Path, key: str) -> None:
    """Store ``key`` in the env file ``path`` (0600, atomically), keeping every other line."""
    _check_key(key)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValidationError("env_file_refused", i18n.t("decisions.jev.env_file_refused",
                              path=str(path)))  # fmt: skip
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            text = handle.read()
    except FileNotFoundError:
        text = ""
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError("env_file_refused", i18n.t("decisions.jev.env_file_refused",
                              path=str(path))) from exc  # fmt: skip
    atomic_write_text(path, _with_key(text, key))


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
