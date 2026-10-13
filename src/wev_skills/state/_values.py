"""Small value helpers of the run state: timestamps, run ids and plain-JSON checking."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from wev_skills.core.errors import ValidationError

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENV_KEYS = frozenset({"env", "environ", "environment"})
_ENV_MARKERS = frozenset({"PATH", "HOME", "USER", "SHELL", "PWD"})


def invalid(code: str, message: str, path: str = "") -> ValidationError:
    return ValidationError(code, message, {"path": path or "/"})


def iso_utc(seconds: float) -> str:
    """Format epoch seconds (as returned by a ``Clock``) as an ISO-8601 UTC timestamp."""
    return datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def validate_run_id(run_id: object) -> str:
    """Return ``run_id`` when it is safe as a single directory name; raise otherwise."""
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise invalid("invalid_run_id", f"invalid run id {run_id!r}: use letters, digits, . _ -")
    return run_id


def plain_json(value: Any, path: str = "") -> Any:
    """Return a deep copy of ``value`` as plain JSON data; reject environment mappings."""
    here = path or "/"
    if isinstance(value, Mapping):
        if isinstance(value, type(os.environ)) or len(_ENV_MARKERS & set(value)) >= 2:
            raise invalid("environment_rejected", f"{here}: environment mapping refused", path)
        for key, item in value.items():
            if not isinstance(key, str):
                raise invalid("invalid_value", f"{here}: object keys must be strings", path)
            if key.lower() in _ENV_KEYS and isinstance(item, Mapping):
                raise invalid("environment_rejected", f"{here}: environment in {key!r}", path)
        return {key: plain_json(item, f"{path}/{key}") for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain_json(item, f"{path}/{i}") for i, item in enumerate(value)]
    if isinstance(value, float) and not math.isfinite(value):
        raise invalid("invalid_value", f"{here}: non-finite numbers are not JSON", path)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise invalid("invalid_value", f"{here}: {type(value).__name__} is not JSON data", path)
