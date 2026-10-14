"""Error hierarchy. The CLI maps each error to a JSON payload and an exit code."""

from __future__ import annotations

from typing import Any


class WevError(Exception):
    """Base error carrying a machine-readable code and structured details."""

    exit_code: int = 1

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details) if details else {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": dict(self.details)}


class ValidationError(WevError):
    exit_code = 2


class PermissionDenied(WevError):
    exit_code = 3


class ApprovalRequired(WevError):
    exit_code = 4


class StateConflict(WevError):
    exit_code = 5


class GuardTripped(WevError):
    exit_code = 6


class NotFound(WevError):
    exit_code = 7


class RemoteError(WevError):
    exit_code = 8


class ProviderError(WevError):
    exit_code = 8


class BudgetExhausted(WevError):
    """The run spent its budget: new work is refused and the run is delivered as it is."""

    exit_code = 9
