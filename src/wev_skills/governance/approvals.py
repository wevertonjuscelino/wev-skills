"""Approvals for risky actions: a record of what the operator decided, kept as JSON.

A grant is bound to the exact argv (token for token), the resolved working directory and the
run it was asked in; for a remote action the host alias is the first token. It is single-use,
it expires (``permissions.approval_ttl_seconds``) and the execution that uses it consumes it.
A denial is final for that action in that run, whatever directory, risk, reason, quoting or
spacing it is asked again with (``approval_identity.denial_key``): asking again returns the
denied record. Only the operator can reopen it (``wev approval request --reopen-denied``).

What this file is not: proof. It lives in the same account as the agent it constrains, and
the agent can write it with its own tools; no key kept in that account would change this.
The store therefore only adds tamper evidence. Every decision is also appended to the audit
log, a grant is honored only when a matching ``approval.granted`` event exists there, and
``verify`` reports mismatches. That catches accidents and naive forgery, not an agent that
rewrites both files. The gate a person can rely on is Claude Code's own permission prompt.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.core import fsutil
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import (
    NotFound,
    PermissionDenied,
    StateConflict,
    ValidationError,
    WevError,
)
from wev_skills.core.ports import Clock, SystemClock
from wev_skills.governance.approval_identity import (
    ID_HASH_CHARS,
    ID_PREFIX,
    Action,
    action_hash,
    approval_id,
    binding_hash,
    denial_key,
    normalize_action,
    resolved_cwd,
)
from wev_skills.governance.audit import AUDIT_FILE_NAME, AuditLog
from wev_skills.security.redact import redact, redact_argv

SCHEMA_VERSION = 2
DEFAULT_TTL_SECONDS = 900.0
EVENT_GRANTED = "approval.granted"
EVENT_DENIED = "approval.denied"
EVENT_CONSUMED = "approval.consumed"
EVENT_EXPIRED = "approval.expired"
EVENT_REOPENED = "approval.reopened"
EVENT_UNVERIFIED = "approval.unverified"
REPLACES_FIELD = "replaces"
"""In ``approval.reopened``: ids of denied records (other spellings) the reopen removed."""

__all__ = [
    "ID_HASH_CHARS", "ID_PREFIX", "Action", "ApprovalRequest", "ApprovalStatus", "ApprovalStore",
    "Mismatch", "action_hash", "approval_id", "binding_hash", "denial_key", "normalize_action",
    "refuse_hidden_text", "resolved_cwd",
]  # fmt: skip

RunLookup = Callable[[], "str | None"]


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    CONSUMED = "consumed"
    EXPIRED = "expired"


OPEN_STATUSES = (ApprovalStatus.PENDING, ApprovalStatus.GRANTED)


@dataclass(frozen=True)
class ApprovalRequest(Serializable):
    id: str
    action: str
    action_hash: str
    risk: RiskLevel
    reason: str
    requested_by: str
    requested_at: float
    status: ApprovalStatus = ApprovalStatus.PENDING
    argv: tuple[str, ...] = ()
    cwd: str = ""
    run_id: str = ""
    generation: int = 1
    binding: str = ""
    decided_by: str = ""
    decided_tty: str = ""
    decided_at: float | None = None
    expires_at: float | None = None
    used_at: float | None = None


@dataclass(frozen=True)
class Mismatch(Serializable):
    """One disagreement between the approvals file and the audit log."""

    id: str
    problem: str


def _error(kind: type[WevError], code: str, **params: object) -> WevError:
    details = {key: str(value) for key, value in params.items()}
    return kind(code, i18n.t(f"security.approval.{code}", **params), details)


def refuse_hidden_text(tokens: Sequence[str]) -> None:
    """The operator must see exactly what will run, so an action redaction would alter is
    refused instead of being shown masked."""
    shown = shlex.join(tokens)
    if tuple(redact_argv(tokens)) != tuple(tokens) or redact(shown) != shown:
        raise _error(PermissionDenied, "secret_in_action")


Records = dict[str, ApprovalRequest]


def _denials(records: Records, tokens: Sequence[str], run_id: str) -> list[ApprovalRequest]:
    """Every denial in ``run_id`` of the same words as ``tokens`` (see ``denial_key``)."""
    wanted = denial_key(tokens)
    return [
        record
        for record in records.values()
        if record.status is ApprovalStatus.DENIED
        and record.run_id == run_id
        and denial_key(record.argv) == wanted
    ]


def _decision_event(record: ApprovalRequest) -> dict[str, Any]:
    fields = ("id", "generation", "binding", "action", "cwd", "run_id", "status")
    decided = ("decided_by", "decided_tty", "decided_at", "expires_at", "used_at")
    return {name: record.to_dict()[name] for name in (*fields, *decided)}


def _matches(event: dict[str, Any], kind: str, record: ApprovalRequest) -> bool:
    data = event.get("data")
    if event.get("type") != kind or not isinstance(data, dict):
        return False
    wanted = (record.id, record.generation, record.binding, record.decided_at)
    return tuple(data.get(k) for k in ("id", "generation", "binding", "decided_at")) == wanted


class ApprovalStore:
    def __init__(
        self,
        path: str | Path,
        clock: Clock | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        audit: AuditLog | None = None,
        run_lookup: RunLookup | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._ttl = float(ttl_seconds)
        self._audit = audit or AuditLog(self._path.with_name(AUDIT_FILE_NAME))
        self._run_lookup = run_lookup if run_lookup is not None else self._active_run

    def _active_run(self) -> str | None:
        """The active run of the state directory this file lives in; ``None`` when unreadable."""
        from wev_skills.state.store import active_run

        try:
            return active_run(self._path.parent) or ""
        except WevError, OSError:
            return None

    def _load(self) -> Records:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _error(ValidationError, "unreadable", path=self._path, detail=exc) from exc
        entries = raw.get("approvals") if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            raise _error(ValidationError, "unreadable", path=self._path, detail="bad layout")
        return {key: ApprovalRequest.from_dict(value) for key, value in entries.items()}

    def _save(self, records: Records) -> None:
        document = {
            "schema_version": SCHEMA_VERSION,
            "approvals": {key: records[key].to_dict() for key in sorted(records)},
        }
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        fsutil.atomic_write_text(self._path, text)

    def _effective(self, record: ApprovalRequest) -> ApprovalRequest:
        """``record`` as it counts now: a grant past its expiry is ``expired``."""
        if record.status is not ApprovalStatus.GRANTED:
            return record
        if record.expires_at is None or self._clock.now() > record.expires_at:
            return replace(record, status=ApprovalStatus.EXPIRED)
        return record

    def _change(
        self, approval_id_: str, event: str, change: Callable[[ApprovalRequest], ApprovalRequest]
    ) -> ApprovalRequest:
        with fsutil.locked(self._path):
            records = self._load()
            if approval_id_ not in records:
                raise _error(NotFound, "not_found", id=approval_id_)
            updated = change(self._effective(records[approval_id_]))
            self._save({**records, approval_id_: updated})
            self._audit.append(event, _decision_event(updated))
            return updated

    def _fresh(
        self, tokens: tuple[str, ...], previous: ApprovalRequest | None, **fields: Any
    ) -> ApprovalRequest:
        generation = previous.generation + 1 if previous is not None else 1
        return ApprovalRequest(
            id=approval_id(tokens),
            action=shlex.join(tokens),
            action_hash=action_hash(tokens),
            argv=tokens,
            generation=generation,
            binding=binding_hash(tokens, fields["cwd"], fields["run_id"], generation),
            requested_at=self._clock.now(),
            **fields,
        )

    def request(
        self,
        action: Action,
        risk: RiskLevel,
        reason: str,
        requested_by: str,
        cwd: str = "",
        reopen_denied: bool = False,
    ) -> ApprovalRequest:
        """Ask for approval of ``action`` in ``cwd``. A pending or granted request is not
        asked twice. A denial of the same words in this run (``denial_key``; the directory,
        risk and reason do not matter) is returned as it is unless ``reopen_denied`` is set;
        a reopen replaces every such denial by one fresh pending request."""
        tokens = normalize_action(action)
        if not isinstance(risk, RiskLevel):
            raise _error(ValidationError, "bad_risk")
        refuse_hidden_text(tokens)
        place, run_id = resolved_cwd(cwd), self._run_lookup() or ""
        with fsutil.locked(self._path):
            records = self._load()
            denials = _denials(records, tokens, run_id)
            if denials and not reopen_denied:
                return denials[0]
            found = records.get(approval_id(tokens))
            current = self._effective(found) if found is not None else None
            waiting = current is not None and current.status in OPEN_STATUSES
            if current is not None and waiting and (current.cwd, current.run_id) == (place, run_id):
                return current
            created = self._fresh(
                tokens,
                current,
                risk=risk,
                reason=redact(reason),
                requested_by=redact(str(requested_by).strip()),
                cwd=place,
                run_id=run_id,
            )
            replaced = [old.id for old in denials if old.id != created.id]
            kept = {key: value for key, value in records.items() if key not in replaced}
            self._save({**kept, created.id: created})
            if denials:
                event = {**_decision_event(created), REPLACES_FIELD: replaced}
                self._audit.append(EVENT_REOPENED, event)
            return created

    def _decider(self, by: str) -> str:
        if not isinstance(by, str) or not by.strip():
            raise _error(ValidationError, "decider_required")
        return redact(by.strip())

    def grant(self, approval_id_: str, by: str, terminal: str = "") -> ApprovalRequest:
        """Grant a pending request. ``by`` is the operating-system user and ``terminal`` the
        device the confirmation was typed on; both are records, not proof of who typed."""
        decider = self._decider(by)

        def change(record: ApprovalRequest) -> ApprovalRequest:
            if record.status is not ApprovalStatus.PENDING:
                raise _error(StateConflict, "not_pending", id=record.id, status=record.status.value)
            now = self._clock.now()
            return replace(
                record,
                status=ApprovalStatus.GRANTED,
                decided_by=decider,
                decided_tty=terminal,
                decided_at=now,
                expires_at=now + self._ttl,
            )

        return self._change(approval_id_, EVENT_GRANTED, change)

    def deny(self, approval_id_: str, by: str, terminal: str = "") -> ApprovalRequest:
        """Deny a pending request or revoke a grant that has not been used up."""
        decider = self._decider(by)

        def change(record: ApprovalRequest) -> ApprovalRequest:
            if record.status not in (ApprovalStatus.PENDING, ApprovalStatus.GRANTED):
                raise _error(StateConflict, "not_pending", id=record.id, status=record.status.value)
            return replace(
                record,
                status=ApprovalStatus.DENIED,
                decided_by=decider,
                decided_tty=terminal,
                decided_at=self._clock.now(),
                expires_at=None,
            )

        return self._change(approval_id_, EVENT_DENIED, change)

    def get(self, approval_id_: str) -> ApprovalRequest:
        records = self._load()
        if approval_id_ not in records:
            raise _error(NotFound, "not_found", id=approval_id_)
        return self._effective(records[approval_id_])

    def list(self, status: ApprovalStatus | None = None) -> tuple[ApprovalRequest, ...]:
        wanted = ApprovalStatus(status) if status is not None else None
        every = [self._effective(record) for record in self._load().values()]
        records = [record for record in every if wanted is None or record.status is wanted]
        return tuple(sorted(records, key=lambda record: (record.requested_at, record.id)))

    def _bound(self, record: ApprovalRequest, tokens: tuple[str, ...], cwd: str) -> bool:
        """The record is for exactly this argv, directory and run, and its fields are intact."""
        run_id = self._run_lookup()
        expected = binding_hash(record.argv, record.cwd, record.run_id, record.generation)
        intact = record.binding == expected and record.action_hash == action_hash(record.argv)
        here = (tokens, resolved_cwd(cwd), run_id)
        return intact and (record.argv, record.cwd, record.run_id) == here

    def _audited(self, record: ApprovalRequest, kind: str = EVENT_GRANTED) -> bool:
        return any(_matches(event, kind, record) for event in self._audit.read())

    def _usable(self, record: ApprovalRequest | None, tokens: tuple[str, ...], cwd: str) -> bool:
        if record is None or self._effective(record).status is not ApprovalStatus.GRANTED:
            return False
        return self._bound(record, tokens, cwd) and self._audited(record)

    def is_granted(self, action: Action, cwd: str = "") -> bool:
        tokens = normalize_action(action)
        return self._usable(self._load().get(approval_id(tokens)), tokens, cwd)

    def is_denied(self, action: Action, cwd: str = "") -> bool:
        """The operator denied these words in this run, so asking again is moot. ``cwd`` is
        accepted for the gate's signature and ignored: a denial is not tied to a directory."""
        tokens = normalize_action(action)
        return bool(_denials(self._load(), tokens, self._run_lookup() or ""))

    def consume(self, action: Action, cwd: str = "") -> bool:
        """Use the grant for one execution of exactly ``action`` in ``cwd``; False without one.

        Check and consume happen under the lock, so two executions cannot share a grant. A
        grant past its expiry becomes ``expired``; one the audit log does not back is left
        alone and reported as ``approval.unverified``.
        """
        tokens = normalize_action(action)
        with fsutil.locked(self._path):
            records = self._load()
            record = records.get(approval_id(tokens))
            if record is None or record.status is not ApprovalStatus.GRANTED:
                return False
            if self._effective(record).status is ApprovalStatus.EXPIRED:
                expired = replace(record, status=ApprovalStatus.EXPIRED)
                self._save({**records, record.id: expired})
                self._audit.append(EVENT_EXPIRED, _decision_event(expired))
                return False
            if not self._usable(record, tokens, cwd):
                self._audit.append(EVENT_UNVERIFIED, _decision_event(record))
                return False
            used = replace(record, status=ApprovalStatus.CONSUMED, used_at=self._clock.now())
            self._save({**records, record.id: used})
            self._audit.append(EVENT_CONSUMED, _decision_event(used))
            return True

    def verify(self) -> tuple[Mismatch, ...]:
        """Disagreements between the approvals file and the audit log (see ``verification``)."""
        from wev_skills.governance.verification import mismatches

        return mismatches(tuple(self._load().values()), self._audit.read())
