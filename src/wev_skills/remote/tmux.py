"""tmux session lifecycle on an inventory host. Permission and approval are injected.

Every command is a fixed argv sent through the transport. Only sessions carrying this
module's owner marker are ever modified; a session it did not create is left alone.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Callable, Sequence

from wev_skills import i18n
from wev_skills.config import RemoteHost
from wev_skills.core.contracts import (
    Mode,
    PermissionOutcome,
    RawCommandResult,
    RiskLevel,
    RunStatus,
)
from wev_skills.core.errors import (
    ApprovalRequired,
    NotFound,
    PermissionDenied,
    RemoteError,
    WevError,
)
from wev_skills.core.ports import Clock, CommandGate
from wev_skills.core.textsafe import clean_text
from wev_skills.remote.inventory import Inventory, is_production
from wev_skills.remote.session import (
    META_OPTION,
    OWNER_OPTION,
    PreflightReport,
    RemoteRun,
    RemoteStatus,
    RunPaths,
    RunRecords,
    action_string,
    build_wrapper_script,
    derive_status,
    is_owner_token,
    launch_line,
    owner_token,
    parse_meta,
    remote_path,
    run_paths,
    session_name,
    validate_argv,
    validate_base_dir,
    validate_timeout,
)
from wev_skills.remote.transport import Transport

DEFAULT_CAPTURE_LINES = 200
MAX_CAPTURE_LINES = 2000
MAX_FIELD_CHARS = 200
LIST_FORMAT = "#{session_name}|#{" + OWNER_OPTION + "}"
PREPARE_SCRIPT = (
    'umask 077 && mkdir -p -- "$1" && rm -f -- "$2" "$3" && : >> "$4" '
    '&& printf \'%s\\n\' "$6" > "$5"'
)


ApprovalRequester = Callable[[str, RiskLevel, str], str]
"""Files an approval request for ``(action, risk, reason)`` and returns its id."""


class TmuxController:
    def __init__(
        self,
        transport: Transport,
        inventory: Inventory,
        gate: CommandGate,
        approval_check: Callable[[str], bool],
        redactor: Callable[[str], str],
        clock: Clock,
        base_dir: str = "~/.wev/remote",
        command_timeout: float = 30.0,
        approval_request: ApprovalRequester | None = None,
        run_records: RunRecords | None = None,
    ) -> None:
        self._transport = transport
        self._inventory = inventory
        self._gate = gate
        self._approval_check = approval_check
        self._approval_request = approval_request
        self._run_records = run_records
        self._redactor = redactor
        self._clock = clock
        self._base_dir = validate_base_dir(base_dir)
        self._command_timeout = command_timeout

    def with_run_records(self, run_records: RunRecords) -> TmuxController:
        """A copy of this controller that records each start in ``run_records``."""
        clone = copy.copy(self)
        clone._run_records = run_records
        return clone

    # -- public API ---------------------------------------------------------

    def preflight(self, alias: str) -> PreflightReport:
        """Read-only report. A missing tmux is reported, never installed."""
        self._inventory.get(alias)
        base = remote_path(self._base_dir)
        tmux = self._run(alias, ("tmux", "-V"))
        return PreflightReport(
            alias=alias,
            hostname=self._field(self._run(alias, ("hostname",))),
            user=self._field(self._run(alias, ("id", "-un"))),
            tmux_available=tmux.exit_code == 0,
            tmux_version=self._field(tmux),
            timeout_available=self._has_timeout(alias),
            base_dir=self._base_dir,
            base_dir_exists=self._run(alias, ("test", "-d", base)).exit_code == 0,
            base_dir_writable=self._run(alias, ("test", "-w", base)).exit_code == 0,
        )

    def start(
        self,
        alias: str,
        task_id: str,
        argv: Sequence[str],
        mode: Mode,
        risk: RiskLevel,
        timeout_seconds: int | None = None,
    ) -> RemoteRun:
        host = self._inventory.get(alias)
        if mode is Mode.PLAN:
            raise PermissionDenied(
                "remote_plan_mode", i18n.t("remote.error.plan_mode"), {"alias": alias}
            )
        command = validate_argv(argv)
        timeout = validate_timeout(timeout_seconds)
        name = session_name(task_id, alias)
        self._authorize(host, command, mode, risk)
        exists, owner = self._session_state(alias, name)
        if exists:
            return self._existing_run(alias, task_id, name, owner)
        if timeout is not None and not self._has_timeout(alias):
            raise RemoteError(
                "remote_timeout_unavailable",
                i18n.t("remote.error.timeout_unavailable"),
                {"alias": alias},
            )
        if self._run_records is not None:
            # Unreadable records stop the start here, before anything runs on the host.
            self._run_records.find(task_id, alias)
        paths = run_paths(self._base_dir, task_id, alias)
        run = RemoteRun(
            task_id=task_id,
            alias=alias,
            session=name,
            argv=command,
            started_at=float(self._clock.now()),
            log_path=paths.log_path,
            exit_path=paths.exit_path,
            owner_token=owner_token(task_id, alias),
        )
        self._launch(run, paths, build_wrapper_script(command, paths, timeout))
        if self._run_records is not None:
            self._run_records.record(run)
        return run

    def status(self, alias: str, task_id: str) -> RemoteStatus:
        """What the evidence supports. An exit file counts only for a session this task
        owns or, once the session is gone, for a start found in the run records."""
        return self._status(alias, task_id, was_owned=False)

    def _status(self, alias: str, task_id: str, was_owned: bool) -> RemoteStatus:
        """``was_owned``: this call saw the task's own session just before ending it."""
        self._inventory.get(alias)
        name = session_name(task_id, alias)
        paths = run_paths(self._base_dir, task_id, alias)
        try:
            exists, owner = self._session_state(alias, name)
            exit_text = self._read_exit(alias, paths)
        except RemoteError as exc:
            reason = i18n.t("remote.status.check_failed", reason=exc.message)
            return RemoteStatus(RunStatus.UNKNOWN, None, False, False, reason)
        owned = exists and owner == owner_token(task_id, alias)
        try:
            lookup = exit_text is not None and not exists and not was_owned
            recorded = was_owned or (lookup and self._is_recorded(alias, task_id))
        except WevError as exc:
            reason = i18n.t("remote.status.records_unreadable", reason=exc.message)
            return RemoteStatus(RunStatus.UNKNOWN, None, exists, owned, reason)
        return derive_status(exists, owned, exit_text, recorded)

    def _is_recorded(self, alias: str, task_id: str) -> bool:
        """Whether the run records hold a start of this exact task on this host."""
        if self._run_records is None:
            return False
        run = self._run_records.find(task_id, alias)
        return run is not None and run.owner_token == owner_token(task_id, alias)

    def capture(self, alias: str, task_id: str, lines: int = DEFAULT_CAPTURE_LINES) -> str:
        """Redacted tail of the run log. It is remote data: wrap it as untrusted."""
        self._inventory.get(alias)
        count = lines if isinstance(lines, int) and not isinstance(lines, bool) else 0
        count = max(1, min(count, MAX_CAPTURE_LINES))
        paths = run_paths(self._base_dir, task_id, alias)
        result = self._run(alias, ("tail", "-n", str(count), "--", remote_path(paths.log_path)))
        if result.exit_code != 0:
            raise NotFound(
                "remote_log_missing",
                i18n.t("remote.error.log_missing"),
                {"alias": alias, "log_path": paths.log_path},
            )
        return self._redactor(result.stdout)

    def stop(self, alias: str, task_id: str) -> RemoteStatus:
        self._inventory.get(alias)
        name = session_name(task_id, alias)
        exists, owner = self._session_state(alias, name)
        if not exists:
            return self.status(alias, task_id)
        if owner != owner_token(task_id, alias):
            raise RemoteError(
                "remote_session_not_owned",
                i18n.t("remote.error.session_not_owned"),
                {"alias": alias, "session": name},
            )
        self._expect_ok(alias, ("tmux", "kill-session", "-t", f"={name}"), "kill-session")
        after = self._status(alias, task_id, was_owned=True)
        if after.reason == i18n.t("remote.status.gone"):
            return dataclasses.replace(after, reason=i18n.t("remote.status.stopped"))
        return after

    def list_owned(self, alias: str) -> tuple[str, ...]:
        self._inventory.get(alias)
        result = self._run(alias, ("tmux", "list-sessions", "-F", LIST_FORMAT))
        if result.exit_code == 1:  # no tmux server running: no sessions at all
            return ()
        if result.exit_code != 0:
            raise self._command_error(alias, "list-sessions", result)
        owned = []
        for line in result.stdout.splitlines():
            name, _, marker = line.rpartition("|")
            if name and is_owner_token(marker.strip()):
                owned.append(name)
        return tuple(owned)

    # -- authorization ------------------------------------------------------

    def _authorize(
        self, host: RemoteHost, argv: tuple[str, ...], mode: Mode, risk: RiskLevel
    ) -> None:
        """Gate, read-only host rule, then the grant: a refused command never asks for one."""
        action = action_string(host.alias, argv)
        details = {"alias": host.alias, "action": self._redactor(action)}
        decision = self._gate.check_command(argv, None, mode, risk)
        if decision.outcome is PermissionOutcome.DENY:
            raise PermissionDenied(
                "remote_command_denied",
                i18n.t("remote.error.command_denied"),
                {**details, "reason": decision.reason},
            )
        if not host.allow_mutating:
            read_only = self._gate.check_command(argv, None, Mode.PLAN, risk)
            if read_only.outcome is not PermissionOutcome.ALLOW:
                raise PermissionDenied(
                    "remote_read_only_host",
                    i18n.t("remote.error.read_only_host"),
                    {**details, "reason": read_only.reason},
                )
        needs_approval = decision.outcome is not PermissionOutcome.ALLOW or is_production(host)
        if needs_approval and self._approval_check(action) is not True:
            context = {**details, "reason": decision.reason, "environment": host.environment}
            raise self._approval_required(host, action, risk, context)

    def _approval_required(
        self, host: RemoteHost, action: str, risk: RiskLevel, details: dict[str, str]
    ) -> ApprovalRequired:
        """The error for a start that waits for a human, with the request filed when possible.

        The request is for the exact host-qualified action, so it can never be mistaken for
        (or satisfied by) an approval of the same command run locally.
        """
        if self._approval_request is None:
            message = i18n.t("remote.error.approval_required")
            return ApprovalRequired("remote_approval_required", message, details)
        why = i18n.t("remote.approval.reason", alias=host.alias, environment=host.environment)
        level = RiskLevel.HIGH if is_production(host) else risk
        request_id = self._approval_request(action, level, why)
        step = i18n.t("orch.step.approval", id=request_id)
        message = i18n.t("remote.error.approval_requested", id=request_id, action=details["action"])
        extra = {"approval_id": request_id, "approval_ids": [request_id], "next_step": step}
        return ApprovalRequired("remote_approval_required", message, {**details, **extra})

    # -- remote primitives --------------------------------------------------

    def _run(self, alias: str, argv: Sequence[str]) -> RawCommandResult:
        return self._transport.run(alias, tuple(argv), self._command_timeout)

    def _field(self, result: RawCommandResult) -> str:
        if result.exit_code != 0:
            return ""
        lines = result.stdout.strip().splitlines()
        return self._host_text(lines[0]) if lines else ""

    def _host_text(self, text: str) -> str:
        """Text a host sent, for a report or an error: no control characters or escape
        sequences (removed first, so they cannot split a secret), redacted, bounded."""
        return self._redactor(clean_text(text, 0))[:MAX_FIELD_CHARS]

    def _has_timeout(self, alias: str) -> bool:
        return self._run(alias, ("timeout", "--version")).exit_code == 0

    def _command_error(self, alias: str, step: str, result: RawCommandResult) -> RemoteError:
        return RemoteError(
            "remote_command_failed",
            i18n.t("remote.error.command_failed", step=step),
            {
                "alias": alias,
                "step": step,
                "exit_code": result.exit_code,
                "stderr": self._host_text(result.stderr),
            },
        )

    def _expect_ok(self, alias: str, argv: Sequence[str], step: str) -> RawCommandResult:
        result = self._run(alias, argv)
        if result.exit_code != 0:
            raise self._command_error(alias, step, result)
        return result

    def _option(self, alias: str, name: str, option: str) -> str:
        argv = ("tmux", "show-options", "-qv", "-t", f"={name}:", option)
        return self._expect_ok(alias, argv, "show-options").stdout.strip()

    def _session_state(self, alias: str, name: str) -> tuple[bool, str]:
        """``(exists, owner marker)``. Exit 1 means no such session; anything else is an error."""
        result = self._run(alias, ("tmux", "has-session", "-t", f"={name}"))
        if result.exit_code == 1:
            return False, ""
        if result.exit_code != 0:
            raise self._command_error(alias, "has-session", result)
        return True, self._option(alias, name, OWNER_OPTION)

    def _read_exit(self, alias: str, paths: RunPaths) -> str | None:
        result = self._run(alias, ("cat", "--", remote_path(paths.exit_path)))
        return result.stdout if result.exit_code == 0 else None

    # -- start helpers ------------------------------------------------------

    def _existing_run(self, alias: str, task_id: str, name: str, owner: str) -> RemoteRun:
        token = owner_token(task_id, alias)
        if owner != token:
            raise RemoteError(
                "remote_session_not_owned",
                i18n.t("remote.error.session_not_owned"),
                {"alias": alias, "session": name},
            )
        argv, started_at = parse_meta(self._option(alias, name, META_OPTION))
        paths = run_paths(self._base_dir, task_id, alias)
        return RemoteRun(
            task_id, alias, name, argv, started_at, paths.log_path, paths.exit_path, token
        )

    def _launch(self, run: RemoteRun, paths: RunPaths, script: str) -> None:
        alias, target = run.alias, f"={run.session}:"
        files = (paths.exit_path, paths.exit_tmp_path, paths.log_path, paths.script_path)
        prepare: tuple[str, ...] = ("sh", "-c", PREPARE_SCRIPT, "wev", remote_path(paths.base_dir))
        prepare = (*prepare, *(remote_path(path) for path in files), script)
        self._expect_ok(alias, prepare, "prepare")
        self._expect_ok(alias, ("tmux", "new-session", "-d", "-s", run.session), "new-session")
        # Marker first: until it is set the session is not provably ours and is left alone.
        marker = ("tmux", "set-option", "-t", target, OWNER_OPTION, run.owner_token)
        self._expect_ok(alias, marker, "set-owner")
        meta = json.dumps({"argv": list(run.argv), "started_at": run.started_at})
        try:
            self._expect_ok(alias, ("tmux", "set-option", "-t", target, META_OPTION, meta), "meta")
            keys = ("tmux", "send-keys", "-t", target, launch_line(paths), "Enter")
            self._expect_ok(alias, keys, "send-keys")
        except RemoteError as exc:
            removed = self._discard(alias, run.session)
            details = {**exc.details, "session_removed": removed}
            raise RemoteError(exc.code, exc.message, details) from exc

    def _discard(self, alias: str, name: str) -> bool:
        """Remove a session this call created and marked but could not launch."""
        try:
            result = self._run(alias, ("tmux", "kill-session", "-t", f"={name}"))
        except RemoteError:
            return False
        return result.exit_code == 0
