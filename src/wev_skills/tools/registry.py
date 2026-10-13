"""Tool declarations: what each tool can do, so the permission policy can gate it."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import NotFound, ValidationError

DEFAULT_DEFINITION_TOKENS = 300
"""Rough size assumed for the definition of a tool that declares none."""


@dataclass(frozen=True)
class ToolSpec(Serializable):
    name: str
    mutating: bool = False
    remote: bool = False
    network: bool = False
    min_risk_for_approval: RiskLevel | None = None
    description: str = ""
    approx_definition_tokens: int = DEFAULT_DEFINITION_TOKENS
    """Rough size of the tool's definition in an agent's context, in tokens.

    An estimate for comparing tool sets with each other only. It is a hand-set constant,
    not a measured value for any particular model or client, and real definitions differ.
    """

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValidationError("invalid_tool", i18n.t("security.error.tool_name_empty"))
        if isinstance(self.approx_definition_tokens, bool) or self.approx_definition_tokens < 0:
            message = i18n.t("decisions.tools.error.tokens", name=self.name)
            raise ValidationError("invalid_tool", message, {"name": self.name})


# The ``approx_definition_tokens`` below are coarse, hand-set estimates of how much context
# each built-in tool's definition takes, for comparison between tool sets only. They were
# not measured for any particular model or client.
_BUILT_IN: tuple[ToolSpec, ...] = (
    ToolSpec("Read", description="Read a file.", approx_definition_tokens=400),
    ToolSpec("Grep", description="Search file contents.", approx_definition_tokens=500),
    ToolSpec("Glob", description="Find files by name pattern.", approx_definition_tokens=250),
    ToolSpec(
        "Edit",
        mutating=True,
        min_risk_for_approval=RiskLevel.HIGH,
        description="Modify an existing file.",
        approx_definition_tokens=450,
    ),
    ToolSpec(
        "Write",
        mutating=True,
        min_risk_for_approval=RiskLevel.HIGH,
        description="Create or overwrite a file.",
        approx_definition_tokens=300,
    ),
    ToolSpec(
        "Bash",
        mutating=True,
        min_risk_for_approval=RiskLevel.HIGH,
        description="Run a command; each command is also checked by the policy.",
        approx_definition_tokens=1200,
    ),
    ToolSpec(
        "WebFetch",
        network=True,
        description="Fetch a URL (read-only).",
        approx_definition_tokens=400,
    ),
    ToolSpec(
        "WebSearch",
        network=True,
        description="Search the web (read-only).",
        approx_definition_tokens=350,
    ),
    ToolSpec(
        "RemoteExec",
        mutating=True,
        remote=True,
        network=True,
        min_risk_for_approval=RiskLevel.MEDIUM,
        description="Run a command on a configured remote host.",
        approx_definition_tokens=350,
    ),
)


@dataclass(frozen=True)
class ToolRegistry:
    """Immutable set of tool specs; ``register`` returns a new registry."""

    specs: tuple[ToolSpec, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        names = [spec.name for spec in self.specs]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            message = i18n.t("security.error.tool_duplicate", name=", ".join(duplicates))
            raise ValidationError("duplicate_tool", message, {"names": duplicates})

    @classmethod
    def default(cls) -> ToolRegistry:
        return cls(_BUILT_IN)

    @classmethod
    def of(cls, specs: Iterable[ToolSpec]) -> ToolRegistry:
        return cls(tuple(specs))

    def register(self, spec: ToolSpec) -> ToolRegistry:
        """Return a new registry that also holds ``spec``; a duplicate name is an error."""
        return ToolRegistry((*self.specs, spec))

    def get(self, name: str) -> ToolSpec:
        for spec in self.specs:
            if spec.name == name:
                return spec
        message = i18n.t("security.error.tool_unknown", name=name)
        raise NotFound("unknown_tool", message, {"name": name})

    def list(self) -> tuple[ToolSpec, ...]:
        return tuple(sorted(self.specs, key=lambda spec: spec.name))
