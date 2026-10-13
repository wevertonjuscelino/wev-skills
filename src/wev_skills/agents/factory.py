"""Resolve ``extends`` chains, apply conflict rules, create and compose agents."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from wev_skills import i18n
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import (
    AgentSpec,
    Permissions,
    Tools,
    tier_order_violation,
    validate_data,
)
from wev_skills.agents.toolnames import covers, is_mutating
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.core.errors import NotFound, ValidationError

_RISK_ORDER = (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)
_DEFAULT_PERMISSIONS = Permissions(
    modes=(Mode.PLAN,), max_risk=RiskLevel.LOW, may_mutate=False, may_use_remote=False
)
if TYPE_CHECKING:
    from _typeshed import DataclassInstance


def _fail(code: str, key: str, field: str, **params: object) -> ValidationError:
    return ValidationError(code, i18n.t(key, field=field, **params), {"field": field, **params})


def _union[T](parent: Iterable[T], child: Iterable[T]) -> tuple[T, ...]:
    """Concatenate without duplicates, parent entries first."""
    out: list[T] = []
    for item in (*parent, *child):
        if item not in out:
            out.append(item)
    return tuple(out)


def _merge_sparse[D: "DataclassInstance"](parent: D | None, child: D | None) -> D | None:
    """Field-wise: the child's value when set, otherwise the parent's."""
    if parent is None or child is None:
        return child if child is not None else parent
    values = {
        f.name: getattr(child, f.name)
        if getattr(child, f.name) is not None
        else getattr(parent, f.name)
        for f in dataclasses.fields(child)
    }
    return dataclasses.replace(child, **values)


def _merge_over[D: "DataclassInstance"](parent: D, child: D | None) -> D:
    """Like ``_merge_sparse`` when the parent is known to be set, so the result always is."""
    return _merge_sparse(parent, child) or parent


def _merge_tools(parent: Tools | None, child: Tools | None) -> Tools:
    p, c = parent or Tools(), child or Tools()
    deny = _union(p.deny, c.deny)
    allow = tuple(t for t in _union(p.allow, c.allow) if not covers(deny, t))
    return Tools(allow=allow, deny=deny)


@dataclass(frozen=True)
class _Ceiling:
    """The resolved permissions and tools of the nearest ancestor that set ``ceiling: true``."""

    owner: str
    permissions: Permissions
    tools: Tools


def _risk_index(level: RiskLevel | None) -> int:
    return _RISK_ORDER.index(level or RiskLevel.LOW)


def _check_tools_within(ceiling: _Ceiling, tools: Tools) -> None:
    """Raise when a resolved allow list offers a tool the ceiling owner did not allow.

    A scoped form of a tool the owner allows whole is a narrowing and passes; the unscoped
    tool, or another scope, of a tool the owner allowed only in scoped form does not.
    """
    for tool in tools.allow:
        if not covers(ceiling.tools.allow, tool):
            raise _fail(
                "tool_widening",
                "agents.error.widen_tool",
                "tools.allow",
                ancestor=ceiling.owner,
                tool=tool,
            )


def _check_within(ceiling: _Ceiling, got: Permissions) -> None:
    """Raise when resolved permissions ``got`` go beyond the ceiling in any dimension."""
    bound = ceiling.permissions
    widened = [
        ("modes", not set(got.modes or ()) <= set(bound.modes or ())),
        ("max_risk", _risk_index(got.max_risk) > _risk_index(bound.max_risk)),
        ("may_mutate", bool(got.may_mutate) and not bound.may_mutate),
        ("may_use_remote", bool(got.may_use_remote) and not bound.may_use_remote),
    ]
    for name, beyond in widened:
        if beyond:
            field = f"permissions.{name}"
            raise _fail("permission_widening", "agents.error.widen", field, ancestor=ceiling.owner)


def _apply_ceiling(
    spec: AgentSpec, declared: Permissions | None, inherited: _Ceiling | None
) -> tuple[AgentSpec, _Ceiling | None]:
    """Enforce the inherited ceiling on a finalized ``spec`` and return the one it passes on.

    Without a ceiling anywhere above, permissions are plain inheritance: the child's value
    wins. Once an ancestor sets ``ceiling: true`` every descendant stays within that
    ancestor's permissions and tools and cannot switch the ceiling off; a descendant that
    sets ``ceiling: true`` again becomes the (equal or lower) bound for its own descendants.
    """
    permissions, tools = spec.permissions or Permissions(), spec.tools or Tools()
    wants = declared.ceiling if declared is not None else None
    if inherited is None and not wants:
        return spec, None
    if inherited is not None:
        if wants is False:
            field = "permissions.ceiling"
            raise _fail(
                "ceiling_unset", "agents.error.ceiling_unset", field, ancestor=inherited.owner
            )
        _check_within(inherited, permissions)
        _check_tools_within(inherited, tools)
    marked = dataclasses.replace(spec, permissions=dataclasses.replace(permissions, ceiling=True))
    own = _Ceiling(spec.id, marked.permissions or permissions, tools)
    return marked, own if wants else inherited


def _finalize(spec: AgentSpec) -> AgentSpec:
    """Fill conservative permission defaults and enforce rules that hold for any resolved spec."""
    permissions = _merge_over(_DEFAULT_PERMISSIONS, spec.permissions)
    tools = _merge_tools(None, spec.tools)
    if not permissions.may_mutate and any(is_mutating(tool) for tool in tools.allow):
        raise _fail("mutating_tool_without_permission", "agents.error.mutating_tool", "tools.allow")
    policy = spec.model_policy
    if policy is not None and tier_order_violation(policy.min_tier, policy.max_tier):
        raise _fail("invalid_tier_order", "agents.error.tier_order_field", "model_policy")
    return dataclasses.replace(spec, permissions=permissions, tools=tools, extends=None)


def _merge(parent: AgentSpec, child: AgentSpec) -> AgentSpec:
    """Child over parent. ``parent`` is already resolved."""
    return dataclasses.replace(
        child,
        specialties=_union(parent.specialties, child.specialties),
        instructions=child.instructions or parent.instructions,
        responsibilities=_union(parent.responsibilities, child.responsibilities),
        model=child.model or parent.model,
        model_policy=_merge_sparse(parent.model_policy, child.model_policy),
        tools=_merge_tools(parent.tools, child.tools),
        skills=_union(parent.skills, child.skills),
        permissions=_merge_over(parent.permissions or Permissions(), child.permissions),
        budget=_merge_sparse(parent.budget, child.budget),
        timeout_seconds=_first_set(child.timeout_seconds, parent.timeout_seconds),
        max_attempts=_first_set(child.max_attempts, parent.max_attempts),
        success_criteria=_union(parent.success_criteria, child.success_criteria),
        escalation=_merge_sparse(parent.escalation, child.escalation),
        required_checks=_union(parent.required_checks, child.required_checks),
        output_format=child.output_format or parent.output_format,
        stop_conditions=_union(parent.stop_conditions, child.stop_conditions),
    )


def _first_set[T](child: T | None, parent: T | None) -> T | None:
    return child if child is not None else parent


class AgentFactory:
    """Builds fully resolved agents from a registry of specs and templates."""

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    def validate(self, data: Any) -> list[str]:
        """Schema and cross-field errors for a raw spec document; empty when valid."""
        return validate_data(data)

    def resolve(self, spec: AgentSpec) -> AgentSpec:
        """Apply the ``extends`` chain (child over parent). Idempotent."""
        return self._resolve(spec, ())[0]

    def _resolve(
        self, spec: AgentSpec, trail: tuple[str, ...]
    ) -> tuple[AgentSpec, _Ceiling | None]:
        """The resolved spec and the permission ceiling it hands to its descendants."""
        if spec.id in trail:
            chain = " -> ".join((*trail, spec.id))
            raise _fail("agent_cycle", "agents.error.cycle", "extends", chain=chain)
        if spec.extends is None:
            return _apply_ceiling(_finalize(spec), spec.permissions, None)
        try:
            parent_spec = self._registry.get(spec.extends)
        except NotFound as exc:
            raise _fail(
                "unknown_parent", "agents.error.unknown_parent", "extends", parent=spec.extends
            ) from exc
        parent, ceiling = self._resolve(parent_spec, (*trail, spec.id))
        return _apply_ceiling(_finalize(_merge(parent, spec)), spec.permissions, ceiling)

    def child_data(self, template_id: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
        """The raw spec document for a new agent that extends ``template_id``."""
        template = self._registry.get(template_id)
        if "id" not in overrides:
            raise _fail("missing_id", "agents.error.override_id", "id")
        if "extends" in overrides:
            raise _fail("extends_override", "agents.error.override_extends", "extends")
        data: dict[str, Any] = {
            "schema_version": 1,
            "name": template.name.to_json(),
            "description": template.description.to_json(),
        }
        data.update(overrides)
        data["extends"] = template_id
        return data

    def create(self, template_id: str, overrides: Mapping[str, Any]) -> AgentSpec:
        """A new resolved spec: ``template_id`` plus ``overrides``, validated."""
        data = self.child_data(template_id, overrides)
        return self.resolve(AgentSpec.from_dict(data))

    def compose(self, ids: Sequence[str]) -> list[AgentSpec]:
        """A team of resolved specs, in the order given; duplicate ids are rejected."""
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise _fail(
                "duplicate_team_member", "agents.error.team_duplicate", "ids", ids=duplicates
            )
        return [self.resolve(self._registry.get(agent_id)) for agent_id in ids]
