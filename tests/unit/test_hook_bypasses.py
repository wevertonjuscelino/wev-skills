"""The Bash pre-check against each bypass class an independent review reproduced."""

from __future__ import annotations

import json
import os
import time

from tests.unit.test_hooks import RUN, WEV, HookCase
from wev_skills.state.store import STATE_FILE

DOT_ENV = "." + "env"
ASK, DENY = "ask", "deny"


class ExecuteModeCase(HookCase):
    def setUp(self) -> None:
        super().setUp()
        self.start()


class ExpansionTests(ExecuteModeCase):
    def test_words_the_hook_cannot_resolve_go_to_the_human(self) -> None:
        for line in (
            "F=-rf; rm $F src",
            "rm $'-rf' src",
            "H=--hard; git reset $H",
            "git reset {--hard,HEAD}",
            "cat .e*",
            "cat .en?",
            f"E={DOT_ENV}; cat $E",
            "P=.wev/approvals.json; cp /tmp/forged.json $P",
            "cp /tmp/forged.json .we*/approvals.json",
            "cat ~root/x",
            "X='rm -rf src'; eval $X",
            "X='rm -rf src'; sh -c \"$X\"",
        ):
            with self.subTest(line=line):
                self.assertIn(self.decision(line), (ASK, DENY))

    def test_abbreviated_git_options_are_destructive(self) -> None:
        for line in ("git reset --har", "git clean --forc -d", "git push --forc"):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), ASK)

    def test_unanalyzable_programs_go_to_the_human(self) -> None:
        for line in (
            "eval ls",
            "source ./x.sh",
            ". ./x.sh",
            "exec ls",
            "command ls",
            "builtin cd",
            "env -S 'rm -rf src'",
            "script -q /dev/null rm -rf src",
            "expect x.exp",
            "xargs ls",
            "arch -arm64 rm -rf src",
            "gtimeout 5 rm -rf src",
            "find . -exec ls {} ;",
            "find . -execdir ls {} ;",
            "find . -ok ls {} ;",
            "find . -delete",
            "git -c alias.x='!rm -rf src' x",
            "git -c core.fsmonitor='rm -rf src' status",
            "git --exec-path=/tmp/evil status",
            "git --config-env=core.pager=X log",
            "git -c clean.requireForce=false clean -d",
            "git rebase --exec 'rm -rf src' HEAD~1",
            "git submodule foreach 'rm -rf .'",
            "git switch --discard-changes main",
            "git checkout HEAD~5 src",
            "tmux send-keys 'ls | head'",
            "./wev",
            "bash x.sh --flag 'a; b'",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), ASK)


class EnvironmentTests(HookCase):
    LINES = (
        "GIT_EXTERNAL_DIFF=/tmp/evil.sh git diff",
        "PATH=/tmp/evil:/usr/bin ls",
        "DYLD_INSERT_LIBRARIES=/tmp/x.dylib ls",
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.fsmonitor GIT_CONFIG_VALUE_0=x git status",
        "env GIT_EXTERNAL_DIFF=/tmp/evil.sh git diff",
        "env -i ls",
        "export PATH=/tmp/evil",
        "export GIT_EXTERNAL_DIFF=/tmp/x; git diff",
        "PATH=/tmp/evil; ls",
        "PYTHONPATH=/tmp/evil python3 -m wev_skills run status",
        f"PATH=/tmp/evil:/usr/bin {WEV} exec -- ls",
    )

    def test_every_assignment_is_an_ask_in_execute_mode(self) -> None:
        self.start()
        for line in self.LINES:
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), ASK)

    def test_every_assignment_is_a_deny_in_plan_mode(self) -> None:
        self.start(mode="plan")
        for line in self.LINES:
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), DENY)


class EngineCommandTests(HookCase):
    def test_a_program_merely_named_wev_is_not_the_engine(self) -> None:
        self.start(mode="plan")
        evil = self.work.parent / "evil"
        evil.mkdir()
        fake = evil / "wev"
        fake.write_text("#!/bin/sh\nrm -rf src\n")
        fake.chmod(0o755)
        for line in (f"{fake} run status", f"{fake} exec -- ls", "./wev run status", "wev-x"):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), DENY)

    def test_a_fake_engine_gets_the_ordinary_policy_in_execute_mode(self) -> None:
        self.start()
        self.assertEqual(self.decision("./wev"), ASK)
        self.assertEqual(self.decision("/tmp/evil/wev rm -rf /"), None)
        self.assertEqual(self.decision("/tmp/evil/wev sudo rm -rf /"), None)

    def test_a_shadowed_module_in_the_working_directory_is_not_the_engine(self) -> None:
        self.start(mode="plan")
        (self.work / "wev_skills").mkdir()
        self.assertEqual(self.decision(f"{os.sys.executable} -m wev_skills run status"), DENY)

    def test_human_operator_and_run_changing_commands_ask(self) -> None:
        self.start(mode="plan")
        for args in (
            "approval grant apr-0123456789abcdef",
            "approval deny apr-0123456789abcdef",
            "approval request --risk low --reason r --reopen-denied -- rm -rf x",
            "approval request --risk low --reason r --reopen -- rm -rf x",
            "guard acknowledge --run r1 --reason x",
            "task reopen t1 --reason x",
            "specialists accept project-test lesson-0123",
            "specialists retire project-test lesson-0123",
            "run start --objective x --mode execute",
            "run finish",
            "agent create --template base --id z1 --out a.json",
            "agent export --out agents",
            "remote start --host h --task t --mode execute -- rm -rf /",
            "remote stop --host h --task t",
            "--config /tmp/agent.json run status",
            "--config=/tmp/agent.json check-command -- ls",
            "--conf /tmp/agent.json run status",
            "--lang en --config /tmp/agent.json approval list",
        ):
            for program in (str(WEV), f"{os.sys.executable} -m wev_skills"):
                with self.subTest(args=args, program=program[-12:]):
                    self.assertEqual(self.decision(f"{program} {args}"), ASK)

    def test_read_only_engine_commands_are_left_alone(self) -> None:
        self.start(mode="plan")
        for args in (
            "run status",
            "run brief",
            "run report --format md",
            "state show",
            "approval list",
            "approval show apr-1",
            "approval verify",
            "check-command -- rm -rf x",
            "classify --objective x",
            "agent list",
            "--lang en run status",
            "exec -- ls",
        ):
            with self.subTest(args=args):
                self.assertIsNone(self.decision(f"{WEV} {args}"))


class GrantTests(ExecuteModeCase):
    def test_a_destructive_command_asks_every_time_whatever_the_store_says(self) -> None:
        from tests.fixtures.operator_prompt import at_terminal

        with at_terminal():
            request = self.wev(
                "approval", "request", "--risk", "high", "--reason", "x", "--", "rm", "-rf", "build"
            )
            self.wev("approval", "grant", request["id"])
        for _ in range(3):
            self.assertEqual(self.decision("rm -rf build"), ASK)
        self.assertEqual(self.wev("approval", "show", request["id"])["status"], "granted")


class ScopeTests(ExecuteModeCase):
    def test_a_nested_repository_does_not_hide_the_run(self) -> None:
        scratch = self.work / "scratch"
        (scratch / ".git").mkdir(parents=True)
        self.assertEqual(self.decision("rm -rf ../src", scratch), ASK)

    def test_a_command_from_elsewhere_that_targets_the_run_root_is_judged(self) -> None:
        elsewhere = self.work.parent / "elsewhere"
        elsewhere.mkdir()
        self.assertEqual(self.decision(f"rm -rf {self.work}/src", elsewhere), ASK)
        self.assertEqual(self.decision(f"cat {self.work}/{DOT_ENV}", elsewhere), DENY)
        self.assertEqual(self.decision(f"cd {self.work} && rm -rf src", elsewhere), ASK)
        self.assertEqual(self.decision(f"git -C {self.work} reset --hard", elsewhere), ASK)
        self.assertIsNone(self.decision("rm -rf build", elsewhere))

    def test_changing_directory_is_followed(self) -> None:
        self.assertEqual(self.decision("cd .wev && cp /tmp/forged.json approvals.json"), DENY)
        self.assertEqual(self.decision("cd .wev; echo x > approvals.json"), DENY)
        self.assertEqual(self.decision("cd src && cat ../.git/config"), DENY)
        self.assertEqual(self.decision("cd - && rm x"), ASK)
        self.assertEqual(self.decision("git -C /tmp status"), ASK)

    def test_the_pinned_configuration_is_the_policy(self) -> None:
        self.wev("run", "finish")
        owner = self.work.parent / "owner.json"
        owner.write_text(json.dumps({"permissions": {"denied_commands": ["make deploy"]}}))
        self.wev("--config", str(owner), "run", "start", "--objective", "o", "--run-id", "r2")
        self.assertEqual(self.decision("make deploy"), DENY)
        agent = self.work.parent / "agent.json"
        agent.write_text(json.dumps({"permissions": {"protected_paths": []}}))
        payload = {
            "cwd": str(self.work),
            "tool_name": "Bash",
            "tool_input": {"command": "make deploy"},
        }
        code, out, _ = self.hook("pre-tool-use", payload, "--config", str(agent))
        self.assertEqual(code, 0)
        decision = json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        self.assertEqual(decision, DENY)


class FailSafeTests(ExecuteModeCase):
    def payload(self, command: str = "rm -rf src", **extra: object) -> dict[str, object]:
        tool_input = {"command": command, **extra}
        return {"cwd": str(self.work), "tool_name": "Bash", "tool_input": tool_input}

    def ask_reason(self, payload: object) -> str:
        code, out, _ = self.hook("pre-tool-use", payload)
        self.assertEqual(code, 0)
        specific = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(specific["permissionDecision"], ASK)
        return str(specific["permissionDecisionReason"])

    def test_a_corrupt_or_forged_state_asks_instead_of_going_silent(self) -> None:
        forged = self.work / ".wev" / "runs" / "20990101T000000Z-aaaaaa"
        forged.mkdir(parents=True)
        (forged / STATE_FILE).write_text("")
        self.assertEqual(self.decision("rm -rf src"), ASK)
        self.assertEqual(self.decision(f"cat {DOT_ENV}"), DENY)

    def test_a_corrupt_only_state_asks(self) -> None:
        state = self.work / ".wev" / "runs" / RUN / STATE_FILE
        state.write_text("{not json")
        for command in ("rm -rf src", "ls"):
            with self.subTest(command=command):
                self.assertIn("state", self.ask_reason(self.payload(command)))

    def test_an_oversized_payload_asks_when_the_directory_has_a_run(self) -> None:
        big = self.payload(description="x" * 1_100_000)
        self.ask_reason(big)

    def test_malformed_input_asks_when_the_directory_has_a_run(self) -> None:
        truncated = '{"cwd": "' + str(self.work) + '", "tool_name": "Bash", "tool_input": {"comm'
        self.ask_reason(truncated)
        self.ask_reason("not json at all")

    def test_malformed_input_is_silent_without_a_run(self) -> None:
        self.wev("run", "finish")
        code, out, _ = self.hook("pre-tool-use", "not json at all")
        self.assertEqual((code, out), (0, ""))

    def test_an_internal_error_after_the_run_is_known_asks(self) -> None:
        from unittest import mock

        from wev_skills.adapters.claude_code import bash_guard

        with mock.patch.object(bash_guard, "decide_command", side_effect=RuntimeError("boom")):
            reason = self.ask_reason(self.payload("ls"))
        self.assertIn("RuntimeError", reason)
        self.assertNotIn("boom", reason)

    def test_sixty_thousand_arguments_ask_in_well_under_a_second(self) -> None:
        many = "echo " + " ".join(f"a{i}" for i in range(60_000)) + "; rm -rf src"
        started = time.perf_counter()
        self.ask_reason(self.payload(many))
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_too_many_words_ask(self) -> None:
        self.ask_reason(self.payload("echo " + "a " * 2500))

    def test_the_reason_never_carries_control_characters_or_secrets(self) -> None:
        secret = "example_" + "Hunter2" * 3
        for line in (
            f"echo hi && rm -rf / --password {secret} # \x1b[2J",
            f"rm $X '\x1b[2J' --password {secret}",
            f"env '\x1b]0;t\x07' --password {secret}",
        ):
            found = self.bash(line)
            assert found is not None
            self.assertNotIn("\x1b", found["reason"])
            self.assertNotIn("\x07", found["reason"])
            self.assertNotIn(secret, found["reason"])


class ProtectedPathTests(ExecuteModeCase):
    def test_literal_protected_paths_are_denied(self) -> None:
        for line in (f"cat {DOT_ENV}", "cat .wev/approvals.json", "cat .git/config"):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), DENY)


def load_tests(loader, tests, pattern):  # type: ignore[no-untyped-def]
    """Only the classes defined here; the imported base case is not run twice."""
    del pattern, tests
    suite = loader.suiteClass()
    for case in (
        ExpansionTests,
        EnvironmentTests,
        EngineCommandTests,
        GrantTests,
        ScopeTests,
        FailSafeTests,
        ProtectedPathTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite
