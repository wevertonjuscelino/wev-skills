from __future__ import annotations

import dataclasses
import unittest

from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.tools.registry import ToolRegistry, ToolSpec


class ToolSpecTests(unittest.TestCase):
    def test_defaults_describe_a_read_only_local_tool(self) -> None:
        spec = ToolSpec("Peek")
        self.assertEqual((spec.mutating, spec.remote, spec.network), (False, False, False))
        self.assertEqual((spec.min_risk_for_approval, spec.description), (None, ""))

    def test_round_trips_through_dicts(self) -> None:
        for spec in (ToolSpec("Peek"), ToolSpec("Ship", True, True, True, RiskLevel.MEDIUM, "d")):
            with self.subTest(spec=spec.name):
                self.assertEqual(ToolSpec.from_dict(spec.to_dict()), spec)
        self.assertEqual(
            ToolSpec("Ship", min_risk_for_approval=RiskLevel.HIGH).to_dict()[
                "min_risk_for_approval"
            ],
            "high",
        )

    def test_is_frozen_and_needs_a_name(self) -> None:
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ToolSpec("Peek").mutating = True  # type: ignore[misc]
        for name in ("", "  "):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                ToolSpec(name)


class ToolRegistryTests(unittest.TestCase):
    def test_default_set_declares_the_built_in_tools(self) -> None:
        registry = ToolRegistry.default()
        by_name = {spec.name: spec for spec in registry.list()}
        self.assertEqual(
            sorted(by_name),
            [
                "Bash",
                "Edit",
                "Glob",
                "Grep",
                "Read",
                "RemoteExec",
                "WebFetch",
                "WebSearch",
                "Write",
            ],
        )
        for name in ("Read", "Grep", "Glob"):
            spec = by_name[name]
            self.assertFalse(spec.mutating or spec.remote or spec.network, name)
            self.assertIsNone(spec.min_risk_for_approval)
        for name in ("Edit", "Write", "Bash"):
            self.assertTrue(by_name[name].mutating, name)
            self.assertFalse(by_name[name].remote, name)
        for name in ("WebFetch", "WebSearch"):
            self.assertTrue(by_name[name].network, name)
            self.assertFalse(by_name[name].mutating, name)
        remote = by_name["RemoteExec"]
        self.assertTrue(remote.remote and remote.mutating)
        self.assertEqual(remote.min_risk_for_approval, RiskLevel.MEDIUM)
        self.assertTrue(all(spec.description for spec in by_name.values()))

    def test_get_returns_the_spec_or_raises_not_found(self) -> None:
        registry = ToolRegistry.default()
        self.assertEqual(registry.get("Read").name, "Read")
        for name in ("read", "Nope", ""):
            with self.subTest(name=name), self.assertRaises(NotFound) as caught:
                registry.get(name)
            self.assertEqual(caught.exception.code, "unknown_tool")

    def test_register_returns_a_new_registry_and_keeps_the_original(self) -> None:
        base = ToolRegistry()
        extended = base.register(ToolSpec("Deploy", mutating=True))
        self.assertEqual(base.list(), ())
        self.assertEqual([spec.name for spec in extended.list()], ["Deploy"])
        self.assertIsNot(base, extended)
        with self.assertRaises(NotFound):
            base.get("Deploy")

    def test_default_registry_is_not_changed_by_registering(self) -> None:
        ToolRegistry.default().register(ToolSpec("Deploy"))
        self.assertEqual(len(ToolRegistry.default().list()), 9)

    def test_duplicate_names_are_rejected(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            ToolRegistry.default().register(ToolSpec("Read", mutating=True))
        self.assertEqual(caught.exception.code, "duplicate_tool")
        with self.assertRaises(ValidationError):
            ToolRegistry.of([ToolSpec("A"), ToolSpec("A")])

    def test_registry_is_immutable_and_list_is_sorted(self) -> None:
        registry = ToolRegistry.of([ToolSpec("Zed"), ToolSpec("Alpha")])
        self.assertEqual([spec.name for spec in registry.list()], ["Alpha", "Zed"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            registry.specs = ()  # type: ignore[misc]
        self.assertIsInstance(registry.list(), tuple)


if __name__ == "__main__":
    unittest.main()
