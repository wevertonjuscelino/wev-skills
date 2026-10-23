"""The ``review`` configuration section: layered review depth and its limits."""

from __future__ import annotations

from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import RiskLevel

DEPTH_OFF = "off"
DEPTH_QUICK = "quick"
DEPTH_STANDARD = "standard"
PRESETS: dict[str, tuple[int, int, int]] = {
    DEPTH_QUICK: (1, 1, 1),
    DEPTH_STANDARD: (3, 3, 2),
    "deep": (5, 5, 3),
}
"""Finders, verifiers and quorum of each depth."""


@dataclass(frozen=True)
class ReviewConfig(Serializable):
    agent: str = ""
    """Agent that runs the finders and verifiers; required when ``depth`` is not ``off``."""
    depth: str = DEPTH_OFF
    finders: int = 0
    """Finders per round; 0 takes the preset of ``depth``."""
    verifiers: int = 0
    """Verifiers per finding; 0 takes the preset."""
    quorum: int = 0
    """Verifier votes that keep a finding; 0 takes the preset."""
    max_rounds: int = 3
    full_rounds: int = 2
    """Rounds that run every finder; later ones narrow to what is still open."""
    max_runs_per_round: int = 12
    timeout_seconds: float = 600.0
    """Time one finder or verifier run may take."""


@dataclass(frozen=True)
class ReviewShape:
    finders: int
    verifiers: int
    quorum: int


def review_shape(config: ReviewConfig, risk: RiskLevel) -> ReviewShape:
    """The size of a review round. ``off`` gives (0, 0, 0): neither a high risk nor an
    explicit key turns review on. Otherwise the preset of ``depth`` (at least ``standard``
    for a high-risk run), then each non-zero key overrides its preset value."""
    if config.depth == DEPTH_OFF:
        return ReviewShape(0, 0, 0)
    quick_raised = risk is RiskLevel.HIGH and config.depth == DEPTH_QUICK
    finders, verifiers, quorum = PRESETS[DEPTH_STANDARD if quick_raised else config.depth]
    return ReviewShape(
        config.finders or finders, config.verifiers or verifiers, config.quorum or quorum
    )


def review_errors(config: ReviewConfig) -> list[str]:
    """Cross-field problems the schema cannot express."""
    errors: list[str] = []
    if config.depth != DEPTH_OFF and not config.agent:
        errors.append(i18n.t("review.config.agent_required"))
    if config.depth == DEPTH_OFF:
        shapes = [ReviewShape(config.finders, config.verifiers, config.quorum)]
    else:
        shapes = [review_shape(config, risk) for risk in (RiskLevel.LOW, RiskLevel.HIGH)]
    for shape in shapes:
        if shape.quorum > shape.verifiers and (shape.verifiers or config.depth != DEPTH_OFF):
            errors.append(
                i18n.t(
                    "review.config.quorum_above_verifiers",
                    quorum=shape.quorum,
                    verifiers=shape.verifiers,
                )
            )
            break
    return errors
