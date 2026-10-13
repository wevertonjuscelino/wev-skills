from __future__ import annotations

import unittest

from tests.unit._agent_helpers import data, factory_for, make
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.core.errors import NotFound, ValidationError

CEILING = {
    "modes": ["plan"],
    "max_risk": "medium",
    "may_mutate": False,
    "may_use_remote": False,
    "ceiling": True,
}
WIDE = {"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True}


def chain(**child_fields: object) -> tuple[AgentFactory, object]:
    """root -> parent (sets ``ceiling: true``) -> child."""
    root = make(
        "root",
        permissions={
            "modes": ["plan", "execute"],
            "max_risk": "high",
            "may_mutate": True,
            "may_use_remote": True,
        },
    )
    parent = make("parent", extends="root", permissions=CEILING)
    child = make("child", extends="parent", **child_fields)
    return factory_for(root, parent, child), child


class ResolveTests(unittest.TestCase):
    def test_scalars_are_overridden_and_lists_concatenate_without_duplicates(self) -> None:
        parent = make(
            "p",
            specialties=["a", "b"],
            model="standard",
            timeout_seconds=10,
            required_checks=["x"],
            skills=["s1"],
            max_attempts=2,
        )
        child = make(
            "c",
            extends="p",
            specialties=["b", "c"],
            model="premium",
            required_checks=["y", "x"],
            skills=["s2"],
        )
        got = factory_for(parent, child).resolve(child)
        self.assertEqual(got.specialties, ("a", "b", "c"))
        self.assertEqual(got.required_checks, ("x", "y"))
        self.assertEqual(got.skills, ("s1", "s2"))
        self.assertEqual((got.model, got.timeout_seconds, got.max_attempts), ("premium", 10, 2))
        self.assertIsNone(got.extends)

    def test_child_instructions_replace_parent_but_unset_inherits(self) -> None:
        parent = make("p", instructions="parent text", output_format="fmt")
        child = make("c", extends="p", instructions="child text")
        got = factory_for(parent, child).resolve(child)
        self.assertEqual((str(got.instructions), str(got.output_format)), ("child text", "fmt"))

    def test_nested_objects_merge_field_wise(self) -> None:
        parent = make(
            "p",
            model_policy={"min_tier": "economy", "max_tier": "premium"},
            escalation={"on_failure": "ask_human", "to": "boss"},
        )
        child = make(
            "c",
            extends="p",
            model_policy={"max_tier": "standard"},
            escalation={"on_failure": "stop"},
        )
        got = factory_for(parent, child).resolve(child)
        self.assertEqual(
            (got.model_policy.min_tier, got.model_policy.max_tier), ("economy", "standard")
        )
        self.assertEqual((got.escalation.on_failure.value, got.escalation.to), ("stop", "boss"))

    def test_resolve_is_idempotent(self) -> None:
        factory, child = chain()
        once = factory.resolve(child)
        self.assertEqual(factory.resolve(once), once)

    def test_unknown_parent_names_extends(self) -> None:
        child = make("c", extends="ghost")
        with self.assertRaises(ValidationError) as ctx:
            factory_for(child).resolve(child)
        self.assertEqual(ctx.exception.details["field"], "extends")
        self.assertEqual(ctx.exception.code, "unknown_parent")

    def test_cycle_is_detected(self) -> None:
        a, b = make("a", extends="b"), make("b", extends="a")
        with self.assertRaises(ValidationError) as ctx:
            factory_for(a, b).resolve(a)
        self.assertEqual(ctx.exception.code, "agent_cycle")

    def test_defaults_are_conservative_when_nothing_declares_permissions(self) -> None:
        got = factory_for(make("a")).resolve(make("a"))
        self.assertEqual(got.permissions.modes, (Mode.PLAN,))
        self.assertEqual(got.permissions.max_risk, RiskLevel.LOW)
        self.assertFalse(got.permissions.may_mutate)
        self.assertFalse(got.permissions.may_use_remote)


class ToolConflictTests(unittest.TestCase):
    def test_tool_in_allow_and_deny_is_denied(self) -> None:
        spec = make("a", tools={"allow": ["Read", "Bash"], "deny": ["Bash"]})
        got = factory_for(spec).resolve(spec)
        self.assertEqual(got.tools.allow, ("Read",))
        self.assertEqual(got.tools.deny, ("Bash",))

    def test_bare_deny_also_denies_scoped_tool_pattern(self) -> None:
        spec = make("a", tools={"allow": ["Read", "Bash(git:*)"], "deny": ["Bash"]})
        self.assertEqual(factory_for(spec).resolve(spec).tools.allow, ("Read",))

    def test_parent_deny_is_inherited_and_child_cannot_remove_it(self) -> None:
        parent = make("p", tools={"allow": ["Read"], "deny": ["WebFetch"]})
        child = make("c", extends="p", tools={"allow": ["WebFetch", "Grep"], "deny": []})
        got = factory_for(parent, child).resolve(child)
        self.assertIn("WebFetch", got.tools.deny)
        self.assertEqual(got.tools.allow, ("Read", "Grep"))

    def test_mutating_tool_requires_may_mutate(self) -> None:
        spec = make("a", tools={"allow": ["Edit"]})
        with self.assertRaises(ValidationError) as ctx:
            factory_for(spec).resolve(spec)
        self.assertEqual(ctx.exception.details["field"], "tools.allow")

    def test_scoped_and_multi_edit_forms_also_require_may_mutate(self) -> None:
        for tool in ("Write(*)", "Edit(src/**)", "MultiEdit", "NotebookEdit(x)", "Edit "):
            spec = make("a", tools={"allow": ["Read", tool]})
            with self.subTest(tool=tool), self.assertRaises(ValidationError) as ctx:
                factory_for(spec).resolve(spec)
            self.assertEqual(ctx.exception.code, "mutating_tool_without_permission")

    def test_a_scoped_mutating_tool_is_fine_when_the_agent_may_mutate(self) -> None:
        spec = make("a", tools={"allow": ["Edit(src/**)"]}, permissions={"may_mutate": True})
        self.assertEqual(factory_for(spec).resolve(spec).tools.allow, ("Edit(src/**)",))

    def test_a_denied_base_tool_removes_every_scoped_form_through_inheritance(self) -> None:
        parent = make("p", tools={"allow": ["Read"], "deny": ["Edit", "Write"]})
        child = make("c", extends="p", tools={"allow": ["Write(*)", "Edit(src/**)", "Grep"]})
        got = factory_for(parent, child).resolve(child)
        self.assertEqual(got.tools.allow, ("Read", "Grep"))

    def test_model_policy_tier_order_is_checked_after_merge(self) -> None:
        parent = make("p", model_policy={"min_tier": "premium"})
        child = make("c", extends="p", model_policy={"max_tier": "economy"})
        with self.assertRaises(ValidationError) as ctx:
            factory_for(parent, child).resolve(child)
        self.assertEqual(ctx.exception.details["field"], "model_policy")


class PermissionRuleTests(unittest.TestCase):
    def assert_widening(self, field: str, **permissions: object) -> None:
        factory, child = chain(permissions=permissions)
        with self.assertRaises(ValidationError) as ctx:
            factory.resolve(child)  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.details["field"], field)
        self.assertEqual(ctx.exception.code, "permission_widening")

    def test_max_risk_cannot_rise(self) -> None:
        self.assert_widening("permissions.max_risk", max_risk="high")

    def test_may_mutate_cannot_go_from_false_to_true(self) -> None:
        self.assert_widening("permissions.may_mutate", may_mutate=True)

    def test_may_use_remote_cannot_go_from_false_to_true(self) -> None:
        self.assert_widening("permissions.may_use_remote", may_use_remote=True)

    def test_modes_cannot_gain_entries(self) -> None:
        self.assert_widening("permissions.modes", modes=["plan", "execute"])

    def test_child_may_narrow(self) -> None:
        factory, child = chain(permissions={"max_risk": "low"})
        got = factory.resolve(child)  # type: ignore[arg-type]
        self.assertEqual(got.permissions.max_risk, RiskLevel.LOW)
        self.assertEqual(got.permissions.modes, (Mode.PLAN,))

    def test_unset_child_permissions_inherit(self) -> None:
        factory, child = chain()
        self.assertEqual(factory.resolve(child).permissions.max_risk, RiskLevel.MEDIUM)  # type: ignore[arg-type]

    def test_without_a_ceiling_inheritance_is_plain_at_every_depth(self) -> None:
        root = make("root")
        middle = make("middle", extends="root", permissions={"max_risk": "medium"})
        leaf = make("leaf", extends="middle", permissions=WIDE)
        got = factory_for(root, middle, leaf).resolve(leaf)
        self.assertEqual(got.permissions.max_risk, RiskLevel.HIGH)
        self.assertTrue(got.permissions.may_mutate)
        self.assertEqual(got.permissions.modes, (Mode.PLAN, Mode.EXECUTE))
        self.assertIsNone(got.permissions.ceiling)

    def test_a_ceiling_on_a_root_binds_its_direct_children(self) -> None:
        root = make("root", permissions={"max_risk": "low", "ceiling": True})
        child = make("child", extends="root", permissions={"max_risk": "medium"})
        with self.assertRaises(ValidationError) as ctx:
            factory_for(root, child).resolve(child)
        self.assertEqual(ctx.exception.code, "permission_widening")
        self.assertEqual(ctx.exception.details["ancestor"], "root")
        self.assertIn("root", ctx.exception.message)

    def test_descendants_inherit_the_ceiling_and_cannot_unset_it(self) -> None:
        factory, child = chain()
        self.assertIs(factory.resolve(child).permissions.ceiling, True)  # type: ignore[arg-type]
        factory, unset = chain(permissions={"ceiling": False})
        with self.assertRaises(ValidationError) as ctx:
            factory.resolve(unset)  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "ceiling_unset")
        self.assertEqual(ctx.exception.details["field"], "permissions.ceiling")

    def test_the_bound_is_the_ancestor_that_set_the_ceiling(self) -> None:
        top = make("top", permissions={**WIDE, "max_risk": "medium", "ceiling": True})
        narrow = make("narrow", extends="top", permissions={"max_risk": "low", "may_mutate": False})
        back = make(
            "back", extends="narrow", permissions={"max_risk": "medium", "may_mutate": True}
        )
        beyond = make("beyond", extends="narrow", permissions={"max_risk": "high"})
        factory = factory_for(top, narrow, back, beyond)
        got = factory.resolve(back)
        self.assertEqual(
            (got.permissions.max_risk, got.permissions.may_mutate), (RiskLevel.MEDIUM, True)
        )
        with self.assertRaises(ValidationError) as ctx:
            factory.resolve(beyond)
        self.assertEqual(ctx.exception.details["ancestor"], "top")

    def test_a_lower_ceiling_further_down_replaces_the_bound(self) -> None:
        top = make("top", permissions={**WIDE, "ceiling": True})
        lower = make("lower", extends="top", permissions={"max_risk": "low", "ceiling": True})
        leaf = make("leaf", extends="lower", permissions={"max_risk": "medium"})
        with self.assertRaises(ValidationError) as ctx:
            factory_for(top, lower, leaf).resolve(leaf)
        self.assertEqual(ctx.exception.details["ancestor"], "lower")

    def test_a_ceiling_cannot_itself_widen_past_an_earlier_one(self) -> None:
        top = make("top", permissions={"max_risk": "low", "ceiling": True})
        lower = make("lower", extends="top", permissions={"max_risk": "high", "ceiling": True})
        with self.assertRaises(ValidationError) as ctx:
            factory_for(top, lower).resolve(lower)
        self.assertEqual(ctx.exception.details["ancestor"], "top")

    def test_ceiling_false_without_an_inherited_ceiling_is_plain_inheritance(self) -> None:
        root = make("root", permissions={"ceiling": False})
        child = make("child", extends="root", permissions=WIDE)
        self.assertTrue(factory_for(root, child).resolve(child).permissions.may_mutate)

    def test_a_descendant_cannot_add_a_tool_the_ceiling_owner_did_not_allow(self) -> None:
        owner = make("owner", tools={"allow": ["Read", "Grep"]}, permissions={"ceiling": True})
        for tool in ("WebFetch", "Task", "mcp__x__y", "Bash", "Bash(git status:*)"):
            child = make("child", extends="owner", tools={"allow": [tool]})
            with self.subTest(tool=tool), self.assertRaises(ValidationError) as ctx:
                factory_for(owner, child).resolve(child)
            self.assertEqual(ctx.exception.code, "tool_widening")
            self.assertEqual(ctx.exception.details["field"], "tools.allow")
            self.assertEqual(ctx.exception.details["ancestor"], "owner")
            self.assertEqual(ctx.exception.details["tool"], tool)

    def test_the_tool_ceiling_binds_every_depth_below_its_owner(self) -> None:
        owner = make("owner", tools={"allow": ["Read"]}, permissions={"ceiling": True})
        middle = make("middle", extends="owner")
        leaf = make("leaf", extends="middle", tools={"allow": ["WebFetch"]})
        with self.assertRaises(ValidationError) as ctx:
            factory_for(owner, middle, leaf).resolve(leaf)
        self.assertEqual(ctx.exception.code, "tool_widening")

    def test_a_descendant_may_narrow_an_allowed_tool_but_not_widen_a_scoped_one(self) -> None:
        owner = make("owner", tools={"allow": ["Read", "Bash"]}, permissions={"ceiling": True})
        narrow = make("narrow", extends="owner", tools={"allow": ["Bash(git status:*)"]})
        got = factory_for(owner, narrow).resolve(narrow)
        self.assertEqual(got.tools.allow, ("Read", "Bash", "Bash(git status:*)"))
        scoped = make(
            "scoped", tools={"allow": ["Bash(git status:*)"]}, permissions={"ceiling": True}
        )
        for tool in ("Bash", "Bash(rm:*)"):
            wide = make("wide", extends="scoped", tools={"allow": [tool]})
            with self.subTest(tool=tool), self.assertRaises(ValidationError) as ctx:
                factory_for(scoped, wide).resolve(wide)
            self.assertEqual(ctx.exception.code, "tool_widening")

    def test_a_tool_the_ancestors_deny_is_dropped_before_the_ceiling_is_checked(self) -> None:
        owner = make(
            "owner", tools={"allow": ["Read"], "deny": ["Edit"]}, permissions={"ceiling": True}
        )
        child = make("child", extends="owner", tools={"allow": ["Edit(src/**)"]})
        self.assertEqual(factory_for(owner, child).resolve(child).tools.allow, ("Read",))

    def test_without_a_ceiling_a_child_may_add_tools(self) -> None:
        parent = make("parent", tools={"allow": ["Read"]})
        child = make("child", extends="parent", tools={"allow": ["WebFetch"]})
        got = factory_for(parent, child).resolve(child)
        self.assertEqual(got.tools.allow, ("Read", "WebFetch"))

    def test_a_read_only_ceiling_cannot_be_bypassed_with_scoped_write_tools(self) -> None:
        owner = make(
            "owner",
            tools={"allow": ["Read", "WebFetch"]},
            permissions={"modes": ["plan", "execute"], "ceiling": True},
        )
        child = make("child", extends="owner", tools={"allow": ["Write(*)", "Edit(src/**)"]})
        with self.assertRaises(ValidationError):
            factory_for(owner, child).resolve(child)

    def test_ceiling_must_be_a_boolean(self) -> None:
        errors = factory_for().validate(data("a", permissions={"ceiling": "yes"}))
        self.assertTrue(errors and "/permissions/ceiling" in errors[0])

    def test_root_parent_supplies_defaults_and_may_be_specialized(self) -> None:
        base = make("base")  # root with implicit conservative defaults
        engineer = make(
            "eng", extends="base", permissions={"modes": ["plan", "execute"], "may_mutate": True}
        )
        got = factory_for(base, engineer).resolve(engineer)
        self.assertTrue(got.permissions.may_mutate)


class CreateComposeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = make(
            "tpl",
            specialties=["t"],
            tools={"allow": ["Read"]},
            permissions=CEILING,
            model="standard",
        )
        self.factory = factory_for(self.template)

    def test_create_builds_resolved_spec_from_template_and_overrides(self) -> None:
        got = self.factory.create("tpl", {"id": "mine", "specialties": ["x"], "model": "premium"})
        self.assertEqual((got.id, got.model, got.specialties), ("mine", "premium", ("t", "x")))
        self.assertIsNone(got.extends)
        self.assertEqual(got.permissions.max_risk, RiskLevel.MEDIUM)

    def test_create_defaults_name_and_description_from_template(self) -> None:
        got = self.factory.create("tpl", {"id": "mine"})
        self.assertEqual(got.name, self.template.name)

    def test_create_validates_overrides(self) -> None:
        with self.assertRaises(ValidationError):
            self.factory.create("tpl", {"id": "mine", "max_attempts": 0})
        with self.assertRaises(ValidationError):
            self.factory.create("tpl", {"id": "Bad Id"})

    def test_create_cannot_widen_a_non_root_template(self) -> None:
        derived = make("derived", extends="tpl")
        factory = factory_for(self.template, derived)
        with self.assertRaises(ValidationError):
            factory.create("derived", {"id": "n", "permissions": {"max_risk": "high"}})

    def test_create_requires_id_and_refuses_extends_override(self) -> None:
        with self.assertRaises(ValidationError):
            self.factory.create("tpl", {})
        with self.assertRaises(ValidationError):
            self.factory.create("tpl", {"id": "n", "extends": "other"})

    def test_create_unknown_template_raises_not_found(self) -> None:
        with self.assertRaises(NotFound):
            self.factory.create("ghost", {"id": "n"})

    def test_validate_returns_error_strings(self) -> None:
        self.assertEqual(self.factory.validate(data("ok")), [])
        errors = self.factory.validate(data("ok", nope=1))
        self.assertTrue(errors and "/nope" in errors[0])

    def test_compose_returns_resolved_team_in_order(self) -> None:
        other = make("other", extends="tpl")
        team = factory_for(self.template, other).compose(["other", "tpl"])
        self.assertEqual([s.id for s in team], ["other", "tpl"])
        self.assertTrue(all(s.extends is None for s in team))

    def test_compose_rejects_duplicates(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            self.factory.compose(["tpl", "tpl"])
        self.assertEqual(ctx.exception.code, "duplicate_team_member")

    def test_compose_unknown_id_raises_not_found(self) -> None:
        with self.assertRaises(NotFound):
            AgentFactory(AgentRegistry()).compose(["ghost"])


if __name__ == "__main__":
    unittest.main()
