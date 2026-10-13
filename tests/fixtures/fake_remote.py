"""In-memory stand-in for ``ssh <alias> <command>`` against a host that has tmux.

``FakeRemoteHost`` implements the ``Runner`` port. It simulates only the handful of
commands the remote controller sends (a few tmux subcommands, ``cat``, ``tail``,
``test``, ``hostname``, ``id``, ``timeout --version`` and one fixed ``sh -c`` prepare
script) over plain dictionaries. It is NOT evidence that those commands behave the same
way on a real tmux, a real sshd or a real shell: it only checks that the controller
sends what it intends to send and reacts correctly to the answers it expects.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field

from wev_skills.config import RemoteHost
from wev_skills.core.contracts import (
    Mode,
    PermissionDecision,
    PermissionOutcome,
    RawCommandResult,
    RiskLevel,
)
from wev_skills.remote.inventory import Inventory
from wev_skills.remote.session import RemoteRun, RunRecords
from wev_skills.remote.tmux import TmuxController
from wev_skills.remote.transport import SshTransport

SSH_PREFIX = ("ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o")
# Kept as an independent literal on purpose: the fake must not import it from the module.
PREPARE_SCRIPT = (
    'umask 077 && mkdir -p -- "$1" && rm -f -- "$2" "$3" && : >> "$4" '
    '&& printf \'%s\\n\' "$6" > "$5"'
)
Reply = tuple[int, str, str]


@dataclass
class FakeSession:
    name: str
    options: dict[str, str] = field(default_factory=dict)
    keys: list[tuple[str, ...]] = field(default_factory=list)
    launched_script: str | None = None


class FakeRemoteHost:
    def __init__(
        self,
        hostname: str = "fake-host",
        user: str = "deploy",
        tmux_installed: bool = True,
        tmux_version: str = "tmux 3.4",
        has_timeout: bool = True,
    ) -> None:
        self.hostname = hostname
        self.user = user
        self.tmux_installed = tmux_installed
        self.tmux_version = tmux_version
        self.has_timeout = has_timeout
        self.sessions: dict[str, FakeSession] = {}
        self.files: dict[str, str] = {}
        self.dirs: set[str] = set()
        self.local_argvs: list[tuple[str, ...]] = []
        self.aliases: list[str] = []
        self.remote_strings: list[str] = []
        self.commands: list[tuple[str, ...]] = []
        self.unknown: list[tuple[str, ...]] = []
        self.fail_steps: dict[str, Reply] = {}
        self._drop: tuple[str, int | None] | None = None

    # -- scenario controls ----------------------------------------------------

    def drop_connection(
        self, stderr: str = "ssh: connect: timed out", times: int | None = None
    ) -> None:
        """Make the next ``times`` ssh calls (all of them when None) fail with exit 255."""
        self._drop = (stderr, times)

    def restore_connection(self) -> None:
        self._drop = None

    def add_foreign_session(self, name: str, options: Mapping[str, str] | None = None) -> None:
        self.sessions[name] = FakeSession(name, dict(options or {}))

    def reboot(self, keep_files: bool = True) -> None:
        self.sessions = {}
        if not keep_files:
            self.files, self.dirs = {}, set()

    def fail(self, prefix: str, exit_code: int = 1, stderr: str = "simulated failure") -> None:
        """Make any remote command whose text starts with ``prefix`` fail."""
        self.fail_steps[prefix] = (exit_code, "", stderr)

    def finish_run(self, session: str, exit_code: int, output: str = "") -> None:
        """Emulate the wrapper finishing: append output to the log, write the exit file."""
        script_path = self.sessions[session].launched_script if session in self.sessions else None
        if script_path is None:
            script_path = next((p for p in self.files if p.endswith(".sh") and session in p), None)
        assert script_path is not None, f"no launched wrapper for session {session}"
        lines = self.files[script_path].strip().splitlines()
        first, last = shlex.split(lines[0]), shlex.split(lines[-1])
        log_path = first[first.index(">>") + 1]
        self.files[log_path] = self.files.get(log_path, "") + output
        self.files[last[-1]] = f"{exit_code}\n"

    def commands_text(self) -> list[str]:
        return [" ".join(command) for command in self.commands]

    # -- Runner port ----------------------------------------------------------

    def run(
        self,
        argv: Sequence[str],
        cwd: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
    ) -> RawCommandResult:
        local = tuple(argv)
        self.local_argvs.append(local)
        assert local[:6] == SSH_PREFIX, f"unexpected ssh options: {local}"
        assert local[6].startswith("ConnectTimeout=") and local[7] == "--", local
        assert len(local) == 10, f"expected exactly alias and one command string: {local}"
        assert cwd is None and env is None, "the transport must not set cwd or env"
        alias, remote = local[8], local[9]
        remote_argv = tuple(shlex.split(remote))
        self.aliases.append(alias)
        self.remote_strings.append(remote)
        self.commands.append(remote_argv)
        if self._drop is not None:
            stderr, times = self._drop
            self._drop = None if times == 1 else (stderr, None if times is None else times - 1)
            return RawCommandResult(local, 255, "", stderr, 1)
        code, out, err = self._dispatch(remote_argv, remote)
        return RawCommandResult(local, code, out, err, 1)

    # -- emulation ------------------------------------------------------------

    def _dispatch(self, argv: tuple[str, ...], remote: str) -> Reply:
        for prefix, reply in self.fail_steps.items():
            if remote.startswith(prefix):
                return reply
        head = argv[0]
        if head == "tmux":
            return self._tmux(argv[1:]) if self.tmux_installed else self._missing(head)
        simple: dict[tuple[str, ...], Reply] = {
            ("hostname",): (0, self.hostname + "\n", ""),
            ("id", "-un"): (0, self.user + "\n", ""),
        }
        if argv in simple:
            return simple[argv]
        if argv == ("timeout", "--version"):
            return (0, "timeout (fake) 9.0\n", "") if self.has_timeout else self._missing(head)
        if head == "test" and len(argv) == 3 and argv[1] in ("-d", "-w"):
            return (0 if argv[2] in self.dirs else 1, "", "")
        if len(argv) == 3 and argv[:2] == ("cat", "--"):
            return self._read(argv[2], None)
        if len(argv) == 5 and argv[:2] == ("tail", "-n") and argv[3] == "--":
            return self._read(argv[4], int(argv[2]))
        if argv[:2] == ("sh", "-c"):
            return self._prepare(argv)
        self.unknown.append(argv)
        return self._missing(head)

    @staticmethod
    def _missing(name: str) -> Reply:
        return (127, "", f"sh: {name}: command not found\n")

    def _read(self, path: str, tail: int | None) -> Reply:
        if path not in self.files:
            return (1, "", f"{path}: No such file or directory\n")
        text = self.files[path]
        if tail is None:
            return (0, text, "")
        return (0, "".join(text.splitlines(keepends=True)[-tail:]), "")

    def _prepare(self, argv: tuple[str, ...]) -> Reply:
        if len(argv) != 10 or argv[2] != PREPARE_SCRIPT or argv[3] != "wev":
            self.unknown.append(argv)
            return (2, "", "sh: unsupported script in fake\n")
        base, exit_path, tmp_path, log_path, script_path, content = argv[4:]
        self.dirs.add(base)
        self.files.pop(exit_path, None)
        self.files.pop(tmp_path, None)
        self.files.setdefault(log_path, "")
        self.files[script_path] = content + "\n"
        return (0, "", "")

    def _session(self, target: str, suffix: str) -> FakeSession | None:
        """Only the exact-match target forms the controller is allowed to use."""
        assert target.startswith("=") and target.endswith(suffix), f"inexact target {target}"
        name = target[1 : len(target) - len(suffix)] if suffix else target[1:]
        return self.sessions.get(name)

    def _tmux(self, args: tuple[str, ...]) -> Reply:
        if args == ("-V",):
            return (0, self.tmux_version + "\n", "")
        sub = args[0] if args else ""
        if sub == "new-session" and len(args) == 4 and args[1:3] == ("-d", "-s"):
            if args[3] in self.sessions:
                return (1, "", f"duplicate session: {args[3]}\n")
            self.sessions[args[3]] = FakeSession(args[3])
            return (0, "", "")
        if sub == "list-sessions" and len(args) == 3 and args[1] == "-F":
            return self._list(args[2])
        if sub in ("has-session", "kill-session") and len(args) == 3 and args[1] == "-t":
            return self._has_or_kill(sub, args[2])
        if len(args) >= 3 and args[1] == "-t" or len(args) >= 4 and args[2] == "-t":
            return self._targeted(sub, args)
        self.unknown.append(("tmux", *args))
        return (1, "", f"unknown command: {sub}\n")

    def _list(self, fmt: str) -> Reply:
        if not self.sessions:
            return (1, "", "no server running on /tmp/tmux-1000/default\n")
        assert fmt == "#{session_name}|#{@wev_owner}", fmt
        rows = [f"{s.name}|{s.options.get('@wev_owner', '')}\n" for s in self.sessions.values()]
        return (0, "".join(rows), "")

    def _has_or_kill(self, sub: str, target: str) -> Reply:
        session = self._session(target, "")
        if session is None:
            return (1, "", f"can't find session: {target[1:]}\n")
        if sub == "kill-session":
            del self.sessions[session.name]
        return (0, "", "")

    def _targeted(self, sub: str, args: tuple[str, ...]) -> Reply:
        if sub == "show-options" and len(args) == 5 and args[1] == "-qv":
            session = self._session(args[3], ":")
            if session is None:
                return (1, "", "no such session\n")
            value = session.options.get(args[4])
            return (0, "" if value is None else value + "\n", "")
        session = self._session(args[2], ":")
        if session is None:
            return (1, "", "no such session\n")
        if sub == "set-option" and len(args) == 5:
            session.options[args[3]] = args[4]
            return (0, "", "")
        if sub == "send-keys" and len(args) == 5 and args[4] == "Enter":
            session.keys.append(args[3:])
            words = shlex.split(args[3])
            if words[:3] == ["cd", "&&", "sh"] and len(words) == 4 and words[3] in self.files:
                session.launched_script = words[3]
            return (0, "", "")
        self.unknown.append(("tmux", *args))
        return (1, "", f"unknown command: {sub}\n")


class FakeGate:
    """Scripted ``CommandGate``: one outcome for plan mode, one for every other mode."""

    def __init__(
        self,
        outcome: PermissionOutcome = PermissionOutcome.ALLOW,
        plan_outcome: PermissionOutcome = PermissionOutcome.ALLOW,
    ) -> None:
        self.outcome = outcome
        self.plan_outcome = plan_outcome
        self.calls: list[tuple[tuple[str, ...], Mode, RiskLevel]] = []

    def check_command(
        self, argv: Sequence[str], cwd: str | None, mode: Mode, risk: RiskLevel
    ) -> PermissionDecision:
        self.calls.append((tuple(argv), mode, risk))
        outcome = self.plan_outcome if mode is Mode.PLAN else self.outcome
        return PermissionDecision(outcome, f"fake gate: {outcome.value}")


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.value = now

    def now(self) -> float:
        return self.value


def mask_secret(text: str) -> str:
    """Test redactor: masks the literal marker ``SECRET``."""
    return text.replace("SECRET", "[REDACTED]")


class MemoryRunRecords:
    """In-memory ``RunRecords``: what a start recorded, keyed by task and host."""

    def __init__(self) -> None:
        self.runs: dict[tuple[str, str], RemoteRun] = {}

    def record(self, run: RemoteRun) -> None:
        self.runs[(run.task_id, run.alias)] = run

    def find(self, task_id: str, alias: str) -> RemoteRun | None:
        return self.runs.get((task_id, alias))


def make_controller(
    host: FakeRemoteHost,
    hosts: Sequence[RemoteHost],
    gate: FakeGate | None = None,
    approved: Collection[str] = (),
    redactor: Callable[[str], str] = mask_secret,
    records: RunRecords | None = None,
) -> TmuxController:
    """Controller wired to the fake host, a scripted gate and a fixed set of approvals.

    Without ``records`` nothing remembers a start, as in a controller used on its own.
    """
    return TmuxController(
        SshTransport(host, redactor=redactor),
        Inventory(hosts),
        gate if gate is not None else FakeGate(),
        lambda action: action in approved,
        redactor,
        FakeClock(),
        run_records=records,
    )
