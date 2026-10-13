"""Choose a decision provider from configuration."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from wev_skills import i18n
from wev_skills.config import Config
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import Runner
from wev_skills.decisions import DecisionProvider
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.jev_program import resolve_jev_program
from wev_skills.decisions.local import LocalPolicyProvider


def build_provider(
    config: Config, runner: Runner, redactor: Callable[[str], str], root: str | None = None
) -> DecisionProvider:
    """``config.decision.provider`` is ``local`` or ``jev``; JEV always wraps a local policy.

    The JEV program is resolved on ``permissions.exec_path`` (or taken as an absolute path
    outside ``root``, default the working directory) each time it is asked.
    """
    local = LocalPolicyProvider(config.limits, config.harness)
    name = config.decision.provider
    if name == "local":
        return local
    if name == "jev":
        jev = config.decision.jev
        resolver = partial(resolve_jev_program, exec_path=config.permissions.exec_path, root=root)
        return JevProvider(
            runner,
            local,
            jev.command,
            jev.timeout_seconds,
            redactor=redactor,
            program_resolver=resolver,
        )
    raise ValidationError(
        "unknown_provider",
        i18n.t("decisions.error.unknown_provider", name=name),
        {"provider": name},
    )
