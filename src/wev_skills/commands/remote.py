"""``wev remote hosts|preflight|start|status|capture|stop``.

The caller is the agent being governed, so what a command may do comes from the active run
(``commands._scope``), not from the command line: its pinned configuration is the host
inventory, its mode and risk judge a start or a stop (``--mode``/``--risk`` may only
restrict them), and the task must be one of its plan whose agent may use remote hosts.
The controller comes from ``core.wiring``: the real permission policy judges the remote
argv, and a command that needs approval (always, on a production host) starts only with
a single-use grant for the exact action ``<alias> <command>``, requested and granted
through ``wev approval``. Text that came from a host is printed as untrusted data.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from wev_skills import i18n
from wev_skills.commands import Subparsers
from wev_skills.commands._scope import Scope, resolve_scope
from wev_skills.core import fsutil, run_budget, wiring
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.core.engine import Engine
from wev_skills.core.errors import PermissionDenied, ValidationError
from wev_skills.core.ports import Runner, SubprocessRunner
from wev_skills.remote import run_scope
from wev_skills.remote.inventory import Inventory
from wev_skills.remote.records import StateRunRecords
from wev_skills.remote.tmux import DEFAULT_CAPTURE_LINES, TmuxController
from wev_skills.security import untrusted
from wev_skills.state.store import StateStore, run_dir


def _default_runner() -> Runner:
    return SubprocessRunner()


def build_controller(scope: Scope) -> TmuxController:
    """The controller for ``scope``: its inventory and policy; during a run, starts are
    recorded in that run's state (without a run nothing is recorded)."""
    controller = wiring.build_remote_controller(scope.config, scope.root, _default_runner())
    if scope.active is None:
        return controller
    store = StateStore(run_dir(scope.state_dir, scope.active.run_id))
    return controller.with_run_records(StateRunRecords(store))


def _with_source(scope: Scope, payload: dict[str, Any]) -> dict[str, Any]:
    return {**payload, "config_source": scope.source}


def _levels(scope: Scope, args: argparse.Namespace) -> tuple[Mode | None, RiskLevel]:
    """Mode and risk for a start or a stop: the run's, which the options may only restrict."""
    mode = Mode(args.mode) if args.mode is not None else None
    risk = RiskLevel(args.risk) if args.risk is not None else None
    return run_scope.resolve_levels(scope.active, mode, risk)


def _task_scope(args: argparse.Namespace, scope: Scope | None = None) -> Scope:
    """The scope of a command about a task; during a run the task must be allowed remote use."""
    found = scope if scope is not None else resolve_scope(args.config)
    if found.active is not None:
        agents = wiring.build_agents(found.config, found.root)
        run_scope.require_remote_task(found.active, agents, args.task)
    return found


def _hosts(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    inventory = Inventory.from_config(scope.config.remote)
    return _with_source(scope, {"hosts": [host.to_dict() for host in inventory.hosts()]})


def _preflight(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    return _with_source(scope, build_controller(scope).preflight(args.host).to_dict())


def _start(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    mode, risk = _levels(scope, args)
    if mode is None:
        raise ValidationError("remote_mode_required", i18n.t("remote.error.mode_required"))
    if mode is Mode.PLAN:
        message = i18n.t("remote.error.plan_mode")
        raise PermissionDenied("remote_plan_mode", message, {"alias": args.host})
    _task_scope(args, scope)
    argv = list(args.argv)
    if argv[:1] == ["--"]:
        argv = argv[1:]
    if scope.active is None:
        run = build_controller(scope).start(args.host, args.task, argv, mode, risk, args.timeout)
        return _with_source(scope, run.to_dict())
    store = StateStore(run_dir(scope.state_dir, scope.active.run_id))
    services = wiring.build_services(scope.config, scope.root)
    engine = Engine(store, services)
    with fsutil.locked(store.run_dir / "execution", scope.config.limits.lock_timeout_seconds):
        state = store.load()
        engine.refuse_tripped(state, args.task)
        run_budget.require(engine, state, units=1)
        run = build_controller(scope).start(args.host, args.task, argv, mode, risk, args.timeout)
    return _with_source(scope, run.to_dict())


def _status(args: argparse.Namespace) -> dict[str, Any]:
    scope = _task_scope(args)
    return _with_source(scope, build_controller(scope).status(args.host, args.task).to_dict())


def _capture(args: argparse.Namespace) -> dict[str, Any]:
    scope = _task_scope(args)
    source = f"remote:{args.host}"
    text = build_controller(scope).capture(args.host, args.task, args.lines)
    fenced = untrusted.wrap(text, source)
    payload = {"untrusted": True, "source": source, "task": args.task, "text": fenced}
    return _with_source(scope, payload)


def _stop(args: argparse.Namespace) -> dict[str, Any]:
    scope = resolve_scope(args.config)
    mode, _ = _levels(scope, args)
    if mode is Mode.PLAN:
        message = i18n.t("remote.error.stop_plan_mode")
        raise PermissionDenied("remote_stop_plan_mode", message, {"alias": args.host})
    _task_scope(args, scope)
    return _with_source(scope, build_controller(scope).stop(args.host, args.task).to_dict())


def _add(actions: Subparsers, name: str, handler: Callable[..., dict[str, Any]], task: bool) -> Any:
    text = i18n.t(f"remote.{name}.help")
    parser = actions.add_parser(name, help=text, description=text)
    parser.add_argument("--host", required=True, help=i18n.t("remote.arg.host"))
    if task:
        parser.add_argument("--task", required=True, help=i18n.t("remote.arg.task"))
    parser.set_defaults(handler=handler)
    return parser


def _add_levels(parser: Any) -> None:
    """``--mode`` and ``--risk`` have no default: unset means "what the run says"."""
    modes, risks = [m.value for m in Mode], [r.value for r in RiskLevel]
    parser.add_argument("--mode", choices=modes, default=None, help=i18n.t("remote.arg.mode"))
    parser.add_argument("--risk", choices=risks, default=None, help=i18n.t("remote.arg.risk"))


def register(subparsers: Subparsers) -> None:
    remote = subparsers.add_parser(
        "remote", help=i18n.t("remote.help"), description=i18n.t("remote.help")
    )
    actions = remote.add_subparsers(dest="remote_command", metavar="<command>", required=True)
    text = i18n.t("remote.hosts.help")
    actions.add_parser("hosts", help=text, description=text).set_defaults(handler=_hosts)
    _add(actions, "preflight", _preflight, task=False)
    start = _add(actions, "start", _start, task=True)
    _add_levels(start)
    start.add_argument("--timeout", type=int, default=None, help=i18n.t("remote.arg.timeout"))
    start.add_argument("argv", nargs=argparse.REMAINDER, help=i18n.t("remote.arg.argv"))
    _add(actions, "status", _status, task=True)
    capture = _add(actions, "capture", _capture, task=True)
    capture.add_argument(
        "--lines", type=int, default=DEFAULT_CAPTURE_LINES, help=i18n.t("remote.arg.lines")
    )
    _add_levels(_add(actions, "stop", _stop, task=True))
