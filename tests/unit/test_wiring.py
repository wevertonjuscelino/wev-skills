from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures.fake_remote import FakeRemoteHost
from wev_skills.config import Config, DecisionConfig, RemoteConfig, RemoteHost, load_config
from wev_skills.core import wiring
from wev_skills.core.contracts import Mode, PermissionOutcome, RiskLevel
from wev_skills.core.errors import ApprovalRequired, PermissionDenied
from wev_skills.decisions.jev import JevProvider
from wev_skills.decisions.local import LocalPolicyProvider
from wev_skills.governance.approvals import approval_id
from wev_skills.security.redact import redact

HOSTS = (RemoteHost("staging-1", "staging", True), RemoteHost("prod-1", "production", False))


class WiringCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.config = Config(remote=RemoteConfig(HOSTS))


class LocalWiringTests(WiringCase):
    def test_state_files_live_under_the_root(self) -> None:
        self.assertEqual(wiring.state_dir(self.config, self.root), self.root / ".wev")
        absolute = Config(state_dir=str(self.root / "elsewhere"))
        self.assertEqual(wiring.state_dir(absolute, "/ignored"), self.root / "elsewhere")
        store = wiring.build_approval_store(self.config, self.root)
        request = store.request(("git", "push"), RiskLevel.HIGH, "release", "agent")
        self.assertTrue((self.root / ".wev" / wiring.APPROVALS_FILE).is_file())
        wiring.build_audit_log(self.config, self.root).append("x", {"id": request.id})
        self.assertTrue((self.root / ".wev" / wiring.AUDIT_FILE).is_file())

    def test_policy_spends_grants_from_the_same_store(self) -> None:
        store = wiring.build_approval_store(self.config, self.root)
        policy = wiring.build_policy(self.config, self.root)
        push = ("git", "push", "origin", "main")
        check = lambda: policy.check_command(push, str(self.root), Mode.EXECUTE, RiskLevel.LOW)  # noqa: E731
        self.assertIs(check().outcome, PermissionOutcome.NEEDS_APPROVAL)
        store.grant(
            store.request(push, RiskLevel.HIGH, "release", "agent", str(self.root)).id, "ana"
        )
        self.assertIs(check().outcome, PermissionOutcome.ALLOW)
        self.assertIs(check().outcome, PermissionOutcome.NEEDS_APPROVAL)

    def test_executor_redacts_output_and_obeys_the_policy(self) -> None:
        host = mock.Mock()
        host.run.return_value = mock.Mock(
            exit_code=0,
            stdout="password=hunter2hunter2",
            stderr="",
            duration_ms=1,
            timed_out=False,
        )
        executor = wiring.build_executor(self.config, self.root, self.root / "logs", host)
        record = executor.run(
            ("printenv",), str(self.root), Mode.EXECUTE, RiskLevel.LOW, track_changes=False
        )
        self.assertNotIn("hunter2", record.stdout_tail)
        with self.assertRaises(PermissionDenied):
            executor.run(("touch", "x"), str(self.root), Mode.PLAN, RiskLevel.LOW)

    def test_provider_follows_the_configuration(self) -> None:
        self.assertIsInstance(wiring.build_provider(self.config), LocalPolicyProvider)
        jev = wiring.build_provider(Config(decision=DecisionConfig(provider="jev")), mock.Mock())
        self.assertIsInstance(jev, JevProvider)
        self.assertIs(jev._redactor, redact)

    def test_router_and_agent_catalog(self) -> None:
        router = wiring.build_model_router(self.config)
        self.assertEqual(router._config, self.config.models)
        agents = wiring.build_agents(self.config, self.root)
        ids = [spec.id for spec in agents.routable()]
        self.assertIn("senior-engineer", ids)
        self.assertNotIn("base-engineer", ids)
        self.assertIn("base-engineer", agents.registry)
        self.assertTrue(agents.resolved("senior-engineer").permissions.may_mutate)

    def test_configured_agent_directories_are_relative_to_the_root(self) -> None:
        extra = self.root / "my-agents"
        extra.mkdir()
        (extra / "mine.json").write_text(
            '{"schema_version": 1, "id": "mine", "name": "Mine", "description": "Custom."}',
            encoding="utf-8",
        )
        config = load_config(None, {"agents": {"directories": ["my-agents", "missing"]}})
        self.assertIn("mine", wiring.build_agents(config, self.root).registry)

    def test_services_share_one_store_and_protect_the_state_directory(self) -> None:
        services = wiring.build_services(self.config, self.root)
        self.assertEqual(services.state_dir, self.root / ".wev")
        self.assertIn(str(self.root / ".wev"), services.config.permissions.protected_paths)
        decision = services.policy.check_command(
            ("tee", ".wev/approvals.json"), str(self.root), Mode.EXECUTE, RiskLevel.LOW
        )
        self.assertIs(decision.outcome, PermissionOutcome.DENY)


class RemoteWiringTests(WiringCase):
    def setUp(self) -> None:
        super().setUp()
        self.host = FakeRemoteHost()
        self.store = wiring.build_approval_store(self.config, self.root)
        self.controller = wiring.build_remote_controller(self.config, self.root, self.host)

    def start(self, alias: str, *argv: str, mode: Mode = Mode.EXECUTE) -> object:
        return self.controller.start(alias, "T-1", argv, mode, RiskLevel.MEDIUM)

    def grant(self, *action: str) -> None:
        self.store.grant(self.store.request(action, RiskLevel.HIGH, "ok", "agent").id, "ana")

    def test_local_ssh_needs_approval_but_the_transport_is_not_a_local_command(self) -> None:
        policy = wiring.build_policy(self.config, self.root)
        for argv in (
            ("ssh", "staging-1", "ls"),
            ("scp", "a", "staging-1:b"),
            ("sftp", "staging-1"),
        ):
            decision = policy.check_command(argv, str(self.root), Mode.EXECUTE, RiskLevel.LOW)
            self.assertIs(decision.outcome, PermissionOutcome.NEEDS_APPROVAL, argv)
        self.start("staging-1", "ls")
        self.assertTrue(self.host.local_argvs)
        self.assertTrue(all(argv[0] == "ssh" for argv in self.host.local_argvs))
        self.assertEqual(self.store.list(), ())

    def test_remote_argv_is_judged_by_the_real_policy(self) -> None:
        with self.assertRaises(ApprovalRequired):
            self.start("staging-1", "ssh", "another-host", "ls")
        with self.assertRaises(PermissionDenied) as denied:
            self.start("staging-1", "cat", ".git/config")
        self.assertEqual(denied.exception.code, "remote_command_denied")
        with self.assertRaises(PermissionDenied) as plan:
            self.start("staging-1", "ls", mode=Mode.PLAN)
        self.assertEqual(plan.exception.code, "remote_plan_mode")
        with self.assertRaises(PermissionDenied) as unlisted:
            self.start("elsewhere", "ls")
        self.assertEqual(unlisted.exception.code, "remote_host_not_listed")
        self.assertEqual(self.host.commands, [])

    def test_a_local_grant_never_authorizes_the_remote_action(self) -> None:
        self.grant("rm", "-rf", "build")
        with self.assertRaises(ApprovalRequired):
            self.start("staging-1", "rm", "-rf", "build")
        self.assertEqual(self.host.commands, [])
        self.assertTrue(self.store.is_granted(("rm", "-rf", "build")))
        self.grant("staging-1", "rm", "-rf", "build")
        self.start("staging-1", "rm", "-rf", "build")
        self.assertFalse(self.store.is_granted(("staging-1", "rm", "-rf", "build")))

    def test_a_start_that_needs_approval_files_the_request_and_says_who_grants_it(self) -> None:
        with self.assertRaises(ApprovalRequired) as caught:
            self.start("prod-1", "uptime")
        details = caught.exception.details
        (pending,) = self.store.list()
        self.assertEqual((pending.id, pending.action), (details["approval_id"], "prod-1 uptime"))
        self.assertEqual((pending.status.value, pending.risk), ("pending", RiskLevel.HIGH))
        self.assertEqual(details["approval_ids"], [pending.id])
        self.assertNotEqual(pending.id, approval_id(("uptime",)))
        for text in (details["next_step"], caught.exception.message):
            self.assertIn(f"'wev approval grant {pending.id}' themselves", text)
            self.assertIn("ask the human operator", text)
            self.assertNotIn("--i-am-human", text)
        with self.assertRaises(ApprovalRequired) as again:
            self.start("prod-1", "uptime")
        self.assertEqual(again.exception.details["approval_id"], pending.id)
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.host.commands, [])
        self.store.grant(pending.id, "ana")
        self.start("prod-1", "uptime")
        self.assertEqual(self.store.get(pending.id).status.value, "consumed")

    def test_a_refused_command_files_no_request(self) -> None:
        for argv in (("cat", ".git/config"), ("rm", "-rf", "build")):
            with self.subTest(argv=argv), self.assertRaises(PermissionDenied):
                self.start("prod-1", *argv)
        self.assertEqual(self.store.list(), ())

    def test_production_always_needs_its_own_grant(self) -> None:
        with self.assertRaises(ApprovalRequired):
            self.start("prod-1", "ls")
        self.grant("staging-1", "ls")
        with self.assertRaises(ApprovalRequired):
            self.start("prod-1", "ls")
        self.grant("prod-1", "ls")
        self.start("prod-1", "ls")


if __name__ == "__main__":
    unittest.main()
