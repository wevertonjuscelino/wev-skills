from __future__ import annotations

from dataclasses import replace

from tests.unit._agent_helpers import make
from tests.unit._orchestrator_helpers import DOER, OrchestratorCase, catalog
from wev_skills.agents.factory import AgentFactory
from wev_skills.config import ModelsConfig
from wev_skills.core import planning, wiring
from wev_skills.core.contracts import Mode, PlanTask, RiskLevel, TaskSignals
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError
from wev_skills.models.router import ModelRouter
from wev_skills.state.store import list_runs


class PlanFileTests(OrchestratorCase):
    def test_valid_plan_loads(self) -> None:
        plan = planning.load_plan(self.plan_file({"id": "a"}, {"id": "b", "depends_on": ["a"]}))
        self.assertEqual([t.id for t in plan.tasks], ["a", "b"])

    def test_schema_and_structure_errors_are_validation_errors(self) -> None:
        for tasks in ([{"id": "bad id"}], [{"id": "a", "risk": "extreme"}], []):
            with self.subTest(tasks=tasks), self.assertRaises(ValidationError):
                planning.load_plan(self.plan_file(*tasks))
        with self.assertRaises(NotFound):
            planning.load_plan(str(self.root / "missing.json"))


class OverlapTests(OrchestratorCase):
    def test_overlap_rules(self) -> None:
        cases = (
            (["a.py"], ["a.py"], True),
            (["./src/a.py"], ["src/a.py"], True),
            (["src"], ["src/a.py"], True),
            (["src/a.py"], ["src/"], True),
            (["src/a.py"], ["src/b.py"], False),
            (["src"], ["srcs/a.py"], False),
            ([], ["a.py"], True),
            (["a.py"], [], True),
        )
        for first, second, expected in cases:
            with self.subTest(first=first, second=second):
                self.assertIs(planning.files_overlap(first, second), expected)


class ModelSettingsTests(OrchestratorCase):
    def test_tier_name_is_a_floor_and_a_model_id_is_pinned(self) -> None:
        tier = make("t", model="standard", model_policy={"max_tier": "premium"})
        self.assertEqual(planning.model_settings(tier), (None, ("standard", "premium")))
        capped = make("c", model="premium", model_policy={"max_tier": "standard"})
        self.assertEqual(planning.model_settings(capped), (None, ("standard", "standard")))
        pinned = make("p", model="vendor/model-x")
        self.assertEqual(planning.model_settings(pinned), ("vendor/model-x", None))
        self.assertEqual(planning.model_settings(make("n")), (None, None))

    def test_escalation_moves_one_tier_up_unless_pinned_or_disabled(self) -> None:
        self.start()
        self.set_plan({"id": "a"})
        state, models = self.state(), ModelsConfig()
        router, task = ModelRouter(models), self.state().plan.tasks[0]

        def after(spec_fields: dict[str, object], current: str) -> str:
            spec = make("x", **spec_fields)
            return planning.escalated_model(router, models, state, task, spec, current, 2).model

        self.assertEqual(after({}, "claude-haiku-5-5"), "claude-sonnet-5-5")
        self.assertEqual(after({}, "claude-sonnet-5-5"), "claude-opus-5-5")
        self.assertEqual(after({}, "claude-opus-5-5"), "claude-opus-5-5")
        capped = {"model_policy": {"max_tier": "standard"}}
        self.assertEqual(after(capped, "claude-sonnet-5-5"), "claude-sonnet-5-5")
        frozen = {"model_policy": {"escalate_on_failure": False}}
        self.assertEqual(after(frozen, "claude-haiku-5-5"), "claude-haiku-5-5")
        self.assertEqual(after({"model": "vendor/model-x"}, "vendor/model-x"), "vendor/model-x")


class CandidateTests(OrchestratorCase):
    def test_executing_runs_prefer_agents_that_may_change_files(self) -> None:
        self.start()
        task = PlanTask("a", "a", "a")
        ids = [s.id for s in planning.candidates(self.state(), task, catalog())]
        self.assertEqual(ids, ["builder", "fixer"])

    def test_plan_mode_keeps_read_only_agents(self) -> None:
        self.start(mode=Mode.PLAN)
        ids = [s.id for s in planning.candidates(self.state(), PlanTask("a", "a", "a"), catalog())]
        self.assertEqual(ids, ["builder", "fixer", "reviewer"])

    def test_an_agent_is_never_given_a_task_above_its_risk_ceiling(self) -> None:
        self.start()
        low = make(
            "careful", permissions={"modes": ["execute"], "max_risk": "low", "may_mutate": True}
        )
        agents = catalog()
        registry = agents.registry.register(low)
        wider = type(agents)(registry, type(agents.factory)(registry), frozenset())
        risky = PlanTask("a", "a", "a", risk=RiskLevel.HIGH)
        self.assertNotIn("careful", [s.id for s in planning.candidates(self.state(), risky, wider)])
        only = type(agents)(
            type(registry)([low]), type(agents.factory)(type(registry)([low])), frozenset()
        )
        with self.assertRaises(ValidationError) as caught:
            planning.candidates(self.state(), risky, only)
        self.assertEqual(caught.exception.code, "no_eligible_agent")
        self.assertIn("risk high", caught.exception.message)

    def test_an_agent_is_not_routed_outside_its_modes(self) -> None:
        self.start()
        planner = make(
            "planner", permissions={"modes": ["plan"], "max_risk": "high", "may_mutate": True}
        )
        agents = catalog()
        registry = agents.registry.register(planner)
        wider = type(agents)(registry, type(agents.factory)(registry), frozenset())
        ids = [s.id for s in planning.candidates(self.state(), PlanTask("a", "a", "a"), wider)]
        self.assertNotIn("planner", ids)

    def test_a_hint_to_an_agent_that_may_not_take_the_task_is_refused(self) -> None:
        self.start()
        specs = {
            "careful": {"modes": ["execute"], "max_risk": "low", "may_mutate": True},
            "planner": {"modes": ["plan"], "max_risk": "high", "may_mutate": True},
        }
        agents = catalog()
        registry = agents.registry
        for agent_id, permissions in specs.items():
            registry = registry.register(make(agent_id, permissions=permissions))
        wider = type(agents)(registry, type(agents.factory)(registry), frozenset())
        services = self.services()
        cases = (
            (PlanTask("a", "a", "a", risk=RiskLevel.HIGH, agent_hint="careful"), "risk"),
            (PlanTask("b", "b", "b", agent_hint="planner"), "mode"),
        )
        for task, word in cases:
            with self.subTest(agent=task.agent_hint), self.assertRaises(PermissionDenied) as caught:
                planning.assign(self.state(), task, wider, services.provider, services.router)
            self.assertEqual(caught.exception.code, "agent_not_permitted")
            self.assertIn(word, caught.exception.message)

    def test_a_remote_task_keeps_agents_allowed_to_use_remote_systems(self) -> None:
        self.start()
        remote = make(
            "remote-ops",
            specialties=["remote", "ssh"],
            permissions={
                "modes": ["plan", "execute"],
                "max_risk": "high",
                "may_mutate": False,
                "may_use_remote": True,
            },
        )
        agents = catalog()
        registry = agents.registry.register(remote)
        wider = type(agents)(registry, type(agents.factory)(registry), frozenset())
        services = self.services()
        task = PlanTask("a", "Check disk usage on the server", "look at the logs over ssh")
        chosen = planning.assign(self.state(), task, wider, services.provider, services.router)
        self.assertEqual(chosen.agent_id, "remote-ops")
        plain = PlanTask("b", "Add a greeting", "edit the file")
        ids = [s.id for s in planning.candidates(self.state(), plain, wider)]
        self.assertNotIn("remote-ops", ids)


class SynthesisTests(OrchestratorCase):
    def test_single_task_from_the_objective_with_the_discovered_check(self) -> None:
        (self.root / "Makefile").write_text("test:\n\ttrue\n", encoding="utf-8")
        self.start(objective="Fix the login bug\nand tidy up")
        plan = planning.synthesize_plan(self.state())
        task = plan.tasks[0]
        self.assertEqual((task.id, task.title), ("task-1", "Fix the login bug"))
        self.assertEqual(task.checks, ("make test",))
        self.assertEqual(len(task.acceptance_criteria), 1)

    def test_contract_permissions_follow_the_tool_profile(self) -> None:
        self.start()
        self.orch().next_tasks()
        state = self.state()
        task = state.plan.tasks[0]
        wide = make(
            "wide",
            permissions={"modes": ["plan", "execute"], "max_risk": "high", "may_mutate": True},
            tools={
                "allow": ["Read", "Grep", "Glob", "Edit", "Write", "Bash"],
                "deny": ["WebFetch"],
            },
        )
        full = planning.build_contract(state, task, wide)
        lean = planning.build_contract(state, task, wide, tool_profile="lean")
        self.assertEqual(full.permissions, ("Read", "Grep", "Glob", "Edit", "Write", "Bash"))
        self.assertEqual(lean.permissions, ("Read", "Edit", "Bash"))
        self.assertEqual(
            planning.build_contract(state, task, wide, tool_profile="structured"), full
        )

    def test_contract_always_has_a_criterion_so_verified_needs_evidence(self) -> None:
        (self.root / "Makefile").unlink()
        self.start()
        self.set_plan({"id": "a"})
        contract = self.orch().contract(self.state(), "a")
        self.assertEqual(len(contract.acceptance_criteria), 1)
        self.assertEqual(contract.checks, ())


class ToolProfileThreadingTests(OrchestratorCase):
    """The profile in a contract comes from the configuration and the task's model tier."""

    WIDE = ("Read", "Grep", "Glob", "Edit", "Write", "Bash")

    def services(self) -> wiring.Services:
        built = super().services()
        wide = make(
            "builder",
            specialties=["implementation"],
            permissions=DOER,
            tools={"allow": list(self.WIDE)},
        )
        registry = built.agents.registry.register(wide)
        agents = wiring.AgentCatalog(registry, AgentFactory(registry), frozenset())
        return replace(built, agents=agents)

    def permissions(self, profile: str, files: int) -> tuple[str, tuple[str, ...]]:
        self.overrides = {
            "harness": {"tool_profile": profile, "planning": "never"},
            "agents": {"default_agent": "builder"},
        }
        run_id = f"run-{profile}-{files}"
        for old in list_runs(self.services().state_dir):
            self.orch(old).finish()
        self.orch(run_id).start(
            "Implement it", Mode.AUTO, TaskSignals("Implement it", files), run_id
        )
        contract = self.orch(run_id).next_tasks()["tasks"][0]
        self.assertEqual(contract["agent_id"], "builder")
        return contract["model"], tuple(contract["permissions"])

    def test_structured_is_the_default_and_keeps_every_allowed_tool(self) -> None:
        self.assertEqual(self.permissions("structured", 20)[1], self.WIDE)

    def test_lean_applies_whatever_the_tier(self) -> None:
        self.assertEqual(self.permissions("lean", 1)[1], ("Read", "Edit", "Bash"))

    def test_auto_is_lean_only_when_the_task_runs_on_the_premium_tier(self) -> None:
        model, tools = self.permissions("auto", 20)
        self.assertEqual((model, tools), ("claude-opus-5-5", ("Read", "Edit", "Bash")))
        model, tools = self.permissions("auto", 2)
        self.assertEqual((model, tools), ("claude-sonnet-5-5", self.WIDE))
