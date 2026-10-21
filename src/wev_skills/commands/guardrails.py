"""``wev check-command``, ``wev approval ...``, ``wev redact`` and ``wev scan-untrusted``.

Every command here resolves its configuration and state directory through
``commands._scope``: an active run's pinned configuration wins, and the JSON output names the
source that was used. ``approval grant``, ``approval deny`` and ``approval request
--reopen-denied`` are human-operator commands (see ``commands._human`` for what that means
and for what it does not).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from wev_skills import i18n
from wev_skills.cli import CommandResult
from wev_skills.commands import Subparsers
from wev_skills.commands._human import Confirmation, confirm_human, summary_lines
from wev_skills.commands._scope import Scope, resolve_scope
from wev_skills.core import wiring
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel
from wev_skills.core.errors import ApprovalRequired, NotFound, PermissionDenied, ValidationError
from wev_skills.governance.approvals import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
    approval_id,
)
from wev_skills.governance.audit import AuditLog
from wev_skills.security import commands, untrusted
from wev_skills.security.redact import redact, redact_argv

APPROVALS_FILE = wiring.APPROVALS_FILE
AUDIT_FILE = wiring.AUDIT_FILE
EXIT_MISMATCH = 1


def _t(key: str, **params: object) -> str:
    return i18n.t(f"security.cli.{key}", **params)


def _store(scope: Scope) -> ApprovalStore:
    ttl = scope.config.permissions.approval_ttl_seconds
    return ApprovalStore(scope.state_dir / APPROVALS_FILE, ttl_seconds=ttl)


def _audit(scope: Scope) -> AuditLog:
    return AuditLog(scope.state_dir / AUDIT_FILE)


def _argv(args: argparse.Namespace) -> tuple[str, ...]:
    """The command after an optional leading ``--`` separator."""
    raw = list(args.argv)
    tokens = raw[1:] if raw[:1] == ["--"] else raw
    if not tokens:
        raise ValidationError("missing_command", _t("error.missing_command"))
    return tuple(tokens)


OUTCOME_EXIT_CODES = {
    PermissionOutcome.ALLOW: 0,
    PermissionOutcome.DENY: PermissionDenied.exit_code,
    PermissionOutcome.NEEDS_APPROVAL: ApprovalRequired.exit_code,
}


def _filed(scope: Scope, argv: tuple[str, ...]) -> dict[str, Any]:
    """The approval already filed for ``argv``, if any. An id nobody filed is never printed."""
    try:
        record = _store(scope).get(approval_id(argv))
    except NotFound:
        return {}
    return {"approval": {"id": record.id, "status": record.status.value, "cwd": record.cwd}}


def _check_command(args: argparse.Namespace) -> CommandResult:
    """Print the decision on stdout; the exit code is 0 allow, 3 deny, 4 needs approval."""
    scope = resolve_scope(args.config)
    policy = wiring.build_policy(scope.config, scope.root, _store(scope))
    mode, risk = Mode(args.mode), RiskLevel(args.risk)
    argv = commands.parse(_argv(args))
    decision = policy.check_command(argv, os.getcwd(), mode, risk, consume=False)
    result = {
        "argv": list(redact_argv(argv)),
        "mode": mode.value,
        "risk": risk.value,
        "classification": commands.classify(argv).to_dict(),
        "decision": decision.to_dict(),
        "config_source": scope.source,
        **_filed(scope, argv),
    }
    return CommandResult(result, OUTCOME_EXIT_CODES[decision.outcome])


def _shown(record: ApprovalRequest, title: str) -> str:
    """What the operator reads before confirming: the whole action, never a shortened one."""
    fields = {
        "id": record.id,
        "action": record.action,
        "directory": record.cwd or "-",
        "run": record.run_id or "-",
        "risk": record.risk.value,
        "reason": record.reason,
        "requested by": record.requested_by,
    }
    return summary_lines(title, fields)


def _confirm(scope: Scope, record: ApprovalRequest, verb: str) -> Confirmation:
    return confirm_human(
        _audit(scope),
        f"approval.{verb}_refused",
        {"id": record.id},
        _t("error.human_required", id=record.id),
        _shown(record, _t(f"confirm.{verb}")),
    )


def _request_directory(args: argparse.Namespace, scope: Scope, argv: tuple[str, ...]) -> str:
    """Where the action will run: nowhere local for a remote action (its first token is a
    configured host alias), else ``--cwd``, the run's root, or the working directory."""
    if argv[0] in {host.alias for host in scope.config.remote.hosts}:
        return ""
    if args.cwd:
        return str(args.cwd)
    return str(scope.root) if scope.active is not None else os.getcwd()


def _approval_request(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    store, argv = _store(scope), _argv(args)
    cwd = _request_directory(args, scope, argv)
    risk = RiskLevel(args.risk)
    if args.reopen_denied:
        current = store.request(argv, risk, args.reason, args.requested_by, cwd=cwd)
        if current.status is ApprovalStatus.DENIED:
            _confirm(scope, current, "reopen")
    record = store.request(
        argv, risk, args.reason, args.requested_by, cwd=cwd, reopen_denied=args.reopen_denied
    )
    _audit(scope).append("approval.requested", record.to_dict())
    return {**record.to_dict(), "config_source": scope.source}


def _decide(args: argparse.Namespace, verb: str) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    store = _store(scope)
    confirmed = _confirm(scope, store.get(args.id), verb)
    decide = store.grant if verb == "grant" else store.deny
    record = decide(args.id, confirmed.os_user, confirmed.terminal)
    return {**record.to_dict(), "confirmation": confirmed.to_dict(), "config_source": scope.source}


def _approval_grant(args: argparse.Namespace) -> dict[str, Any]:
    return _decide(args, "grant")


def _approval_deny(args: argparse.Namespace) -> dict[str, Any]:
    return _decide(args, "deny")


def _approval_list(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config, reads=True)
    status = ApprovalStatus(args.status) if args.status else None
    records = [record.to_dict() for record in _store(scope).list(status)]
    return {"approvals": records, "config_source": scope.source}


def _approval_show(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config, reads=True)
    return {**_store(scope).get(args.id).to_dict(), "config_source": scope.source}


def _approval_verify(args: argparse.Namespace) -> CommandResult:
    """Exit 0 when the approvals file and the audit log agree, 1 when they do not."""
    scope = resolve_scope(args.config, reads=True)
    found = [item.to_dict() for item in _store(scope).verify()]
    payload = {
        "ok": not found,
        "mismatches": found,
        "note": _t("verify.note"),
        "config_source": scope.source,
    }
    return CommandResult(payload, EXIT_MISMATCH if found else 0)


def _redact(args: argparse.Namespace) -> dict[str, Any]:
    return {"text": redact(sys.stdin.read())}


def _scan_untrusted(args: argparse.Namespace) -> dict[str, Any]:
    text = sys.stdin.read()
    findings = untrusted.scan(text)
    result: dict[str, Any] = {
        "source": args.source,
        "count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
        "note": _t("scan.note"),
    }
    if args.wrap:
        result["wrapped"] = untrusted.wrap(redact(text), args.source)
    return result


def _add_risk(parser: argparse.ArgumentParser, default: str | None) -> None:
    levels = [level.value for level in RiskLevel]
    parser.add_argument(
        "--risk", choices=levels, default=default, required=default is None, help=_t("help.risk")
    )


def _add_argv(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("argv", nargs=argparse.REMAINDER, help=_t("help.argv"))


def _register_decisions(actions: Subparsers) -> None:
    for name, handler in (("grant", _approval_grant), ("deny", _approval_deny)):
        human_only = _t(f"help.approval.{name}")
        parser = actions.add_parser(name, help=human_only, description=human_only)
        parser.add_argument("id", help=_t("help.id"))
        parser.set_defaults(handler=handler)


def _register_approval(subparsers: Subparsers) -> None:
    approval = subparsers.add_parser("approval", help=_t("help.approval"))
    actions = approval.add_subparsers(dest="approval_command", metavar="<command>", required=True)
    request = actions.add_parser("request", help=_t("help.approval.request"))
    _add_risk(request, None)
    request.add_argument("--reason", required=True, help=_t("help.reason"))
    request.add_argument("--requested-by", default="agent", help=_t("help.requested_by"))
    request.add_argument("--cwd", default=None, help=_t("help.cwd"))
    request.add_argument("--reopen-denied", action="store_true", help=_t("help.reopen_denied"))
    _add_argv(request)
    request.set_defaults(handler=_approval_request)
    _register_decisions(actions)
    listing = actions.add_parser("list", help=_t("help.approval.list"))
    statuses = [status.value for status in ApprovalStatus]
    listing.add_argument("--status", choices=statuses, default=None, help=_t("help.status"))
    listing.set_defaults(handler=_approval_list)
    show = actions.add_parser("show", help=_t("help.approval.show"))
    show.add_argument("id", help=_t("help.id"))
    show.set_defaults(handler=_approval_show)
    verify = actions.add_parser("verify", help=_t("help.approval.verify"))
    verify.set_defaults(handler=_approval_verify)


def register(subparsers: Subparsers) -> None:
    check = subparsers.add_parser("check-command", help=_t("help.check"))
    modes = [mode.value for mode in Mode]
    check.add_argument("--mode", choices=modes, default=Mode.EXECUTE.value, help=_t("help.mode"))
    _add_risk(check, RiskLevel.LOW.value)
    _add_argv(check)
    check.set_defaults(handler=_check_command)
    _register_approval(subparsers)
    redactor = subparsers.add_parser("redact", help=_t("help.redact"))
    redactor.set_defaults(handler=_redact)
    scan = subparsers.add_parser("scan-untrusted", help=_t("help.scan"))
    scan.add_argument("--source", required=True, help=_t("help.source"))
    scan.add_argument("--wrap", action="store_true", help=_t("help.wrap"))
    scan.set_defaults(handler=_scan_untrusted)
