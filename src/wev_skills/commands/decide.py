"""``wev classify``, ``wev strategy``, ``wev route-model`` and ``wev select-tools``."""

from __future__ import annotations

import argparse
from typing import Any

from wev_skills import i18n
from wev_skills.agents.tool_profile import tier_of
from wev_skills.commands import Subparsers
from wev_skills.commands._orchestration import config_for, locate
from wev_skills.config import Config, read_json_object
from wev_skills.core import wiring
from wev_skills.core.contracts import Classification, Mode, PlanTask, TaskSignals
from wev_skills.core.errors import ValidationError
from wev_skills.decisions import DecisionProvider
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.models.router import executor_tier

TIER_CHOICES = ("economy", "standard", "premium")
PROVIDER_MODE = "provider"

_COUNT_FLAGS = (
    ("--files", "files_touched_estimate", "decide.files.help"),
    ("--unknowns", "unknowns", "decide.unknowns.help"),
    ("--subtasks", "independent_subtasks", "decide.subtasks.help"),
)
_BOOL_FLAGS = (
    ("--remote", "touches_remote", True, "decide.remote.help"),
    ("--production", "touches_production", True, "decide.production.help"),
    ("--destructive", "destructive", True, "decide.destructive.help"),
    ("--external", "external_side_effects", True, "decide.external.help"),
    ("--no-tests", "has_tests", False, "decide.no_tests.help"),
    ("--irreversible", "reversible", False, "decide.irreversible.help"),
)


def add_signal_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--signals-file", default=None, help=i18n.t("decide.signals.help"))
    parser.add_argument("--objective", default=None, help=i18n.t("decide.objective.help"))
    for flag, field_name, help_key in _COUNT_FLAGS:
        parser.add_argument(
            flag, dest=f"sig_{field_name}", type=int, default=None, help=i18n.t(help_key)
        )
    for flag, field_name, value, help_key in _BOOL_FLAGS:
        parser.add_argument(
            flag,
            dest=f"sig_{field_name}",
            action="store_const",
            const=value,
            default=None,
            help=i18n.t(help_key),
        )


def signals_from(args: argparse.Namespace) -> TaskSignals:
    """File values first, then any flag given explicitly on the command line."""
    data: dict[str, Any] = read_json_object(args.signals_file) if args.signals_file else {}
    if args.objective is not None:
        data = {**data, "objective": args.objective}
    overrides = {
        name[len("sig_") :]: value
        for name, value in vars(args).items()
        if name.startswith("sig_") and value is not None
    }
    merged = {**data, **overrides}
    if not merged.get("objective"):
        raise ValidationError("missing_objective", i18n.t("decide.error.no_objective"))
    return TaskSignals.from_dict(merged)


def _classify(args: argparse.Namespace) -> tuple[Config, DecisionProvider, Classification]:
    config = config_for(args)
    provider = wiring.build_provider(config)
    return config, provider, provider.classify_task(signals_from(args))


def _run_classify(args: argparse.Namespace) -> dict[str, Any]:
    _, _, classification = _classify(args)
    return classification.to_dict()


def _run_strategy(args: argparse.Namespace) -> dict[str, Any]:
    config, provider, classification = _classify(args)
    routed = wiring.build_model_router(config).select(classification)
    tier = executor_tier(args.executor_tier or config.harness.executor_tier, routed)
    strategy = provider.select_strategy(classification, Mode(args.mode), tier)
    return {
        "classification": classification.to_dict(),
        "executor_tier": tier,
        "strategy": strategy.to_dict(),
    }


def _run_route_model(args: argparse.Namespace) -> dict[str, Any]:
    config, _, classification = _classify(args)
    if (args.min_tier is None) != (args.max_tier is None):
        raise ValidationError("invalid_tier_bounds", i18n.t("decide.error.tier_pair"))
    bounds = (args.min_tier, args.max_tier) if args.min_tier else None
    choice = wiring.build_model_router(config).select(
        classification,
        agent_model=args.agent_model,
        agent_tier_bounds=bounds,
        attempt=args.attempt,
        unavailable=tuple(args.unavailable),
    )
    return {"classification": classification.to_dict(), "model_choice": choice.to_dict()}


def _plan_task(path: str) -> PlanTask:
    """One plan task read from a JSON file; a file that is not one is refused."""
    try:
        return PlanTask.from_dict(read_json_object(path))
    except ValidationError as exc:
        if exc.code in ("file_unreadable", "invalid_json"):
            raise
        message = i18n.t("decide.error.task_file", path=path, error=exc.message)
        raise ValidationError("invalid_task_file", message, {"path": path}) from exc


def _tool_provider(config: Config) -> DecisionProvider:
    """The configured provider in ``provider`` mode, else the local policy (also for ``off``)."""
    if config.harness.tool_selection == PROVIDER_MODE:
        return wiring.build_provider(config)
    return LocalPolicyProvider(config.limits, config.harness)


def _run_select_tools(args: argparse.Namespace) -> dict[str, Any]:
    """Print the tool selection for one task and one agent; nothing is stored."""
    location = locate(args)
    config = location.resolved.config
    spec = wiring.build_agents(config, location.root).resolved(args.agent)
    provider = _tool_provider(config)
    tier = args.tier or tier_of(spec.model, config.models)
    available = wiring.build_tool_registry().list()
    selection = provider.select_tools(_plan_task(args.task_file), spec, available, tier)
    return {
        "agent_id": spec.id,
        "tier": tier,
        "mode": config.harness.tool_selection,
        "provider": provider.provider_id,
        "estimate_label": i18n.t("decisions.tools.report.estimate_label"),
        "selection": selection.to_dict(),
    }


def _register_select_tools(subparsers: Subparsers) -> None:
    select = subparsers.add_parser("select-tools", help=i18n.t("decide.select_tools.help"))
    select.add_argument("--task-file", required=True, help=i18n.t("decide.task_file.help"))
    select.add_argument("--agent", required=True, help=i18n.t("decide.agent.help"))
    select.add_argument(
        "--tier", choices=TIER_CHOICES, default=None, help=i18n.t("decide.tier.help")
    )
    select.set_defaults(handler=_run_select_tools)


def register(subparsers: Subparsers) -> None:
    _register_select_tools(subparsers)
    classify = subparsers.add_parser("classify", help=i18n.t("decide.classify.help"))
    add_signal_args(classify)
    classify.set_defaults(handler=_run_classify)

    strategy = subparsers.add_parser("strategy", help=i18n.t("decide.strategy.help"))
    add_signal_args(strategy)
    strategy.add_argument(
        "--mode",
        choices=[mode.value for mode in Mode],
        default=Mode.AUTO.value,
        help=i18n.t("decide.strategy.mode"),
    )
    strategy.add_argument(
        "--executor-tier",
        choices=TIER_CHOICES,
        default=None,
        help=i18n.t("decide.executor_tier.help"),
    )
    strategy.set_defaults(handler=_run_strategy)

    route = subparsers.add_parser("route-model", help=i18n.t("decide.route_model.help"))
    add_signal_args(route)
    route.add_argument("--attempt", type=int, default=0, help=i18n.t("decide.attempt.help"))
    route.add_argument(
        "--unavailable", action="append", default=[], help=i18n.t("decide.unavailable.help")
    )
    route.add_argument("--agent-model", default=None, help=i18n.t("decide.agent_model.help"))
    route.add_argument("--min-tier", choices=TIER_CHOICES, help=i18n.t("decide.min_tier.help"))
    route.add_argument("--max-tier", choices=TIER_CHOICES, help=i18n.t("decide.max_tier.help"))
    route.set_defaults(handler=_run_route_model)
