"""Wrappers and inline shells must not silence the hook on the engine's own commands.

Regression for the second independent pass: ``nohup wev run finish``, ``nice``, ``timeout``,
``sh -c '...'`` and a script handed the engine's path all got no opinion in execute mode.
"""

from __future__ import annotations

import os
import sys
import time

from tests.unit.test_hooks import WEV, HookCase
from wev_skills.adapters.claude_code import bash_guard

ASK = "ask"
MODULE = f"{sys.executable} -m wev_skills"
SENSITIVE = (
    "approval grant apr-0123456789abcdef",
    "approval deny apr-0123456789abcdef",
    "approval request --risk low --reason x -- rm -rf build",
    "approval request --cwd /tmp --risk low --reason x -- rm -rf build",
    "guard acknowledge --reason x",
    "task reopen t1 --reason x",
    "run start --mode execute --objective x",
    "run finish",
    "agent create --template base --id z1 --out a.json",
    "agent export --out agents",
    "remote start --host h --task t -- uptime",
    "remote stop --host h --task t",
    "--config agent.json run status",
)
WRAPPERS = (
    "nohup {}",
    "nice {}",
    "nice -n 5 {}",
    "timeout 5 {}",
    "gtimeout 5 {}",
    "time {}",
    "stdbuf -oL {}",
    "setsid {}",
    "caffeinate -i {}",
    "nohup nice timeout 5 {}",
    "sh -c '{}'",
    "bash -c '{}'",
    "zsh -c '{}'",
    "bash -lc '{}'",
    "nohup sh -c '{}'",
    'sh -c "{}"',
)


class WrapperCase(HookCase):
    def setUp(self) -> None:
        super().setUp()
        self.start()
        path = f"{WEV.parent}{os.pathsep}{os.environ.get('PATH', '')}"
        previous = os.environ.get("PATH", "")
        os.environ["PATH"] = path
        self.addCleanup(os.environ.__setitem__, "PATH", previous)


class WrappedEngineTests(WrapperCase):
    def test_the_reported_lines_ask(self) -> None:
        for line in (
            "nohup wev run finish",
            "nohup wev --config agent.json run start --mode execute --objective x",
            "nice wev --config agent.json run start --mode execute --objective x",
            "nice wev run finish",
            "timeout 5 wev run finish",
            "sh -c 'wev run finish'",
            f"python3 pty_type.py {WEV} approval grant x",
            "python3 pty_type.py wev approval grant x",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), ASK)

    def test_every_wrapper_around_every_sensitive_command_asks(self) -> None:
        for program in ("wev", str(WEV), MODULE):
            for wrapper in WRAPPERS:
                for args in SENSITIVE:
                    line = wrapper.format(f"{program} {args}")
                    with self.subTest(line=line):
                        self.assertEqual(self.decision(line), ASK)

    def test_the_bare_sensitive_commands_ask(self) -> None:
        for program in ("wev", str(WEV), MODULE):
            for args in SENSITIVE:
                with self.subTest(program=program[-12:], args=args):
                    self.assertEqual(self.decision(f"{program} {args}"), ASK)

    def test_a_sensitive_command_inside_a_longer_line_asks(self) -> None:
        for line in (
            "ls && nohup wev run finish",
            "cd src; nice wev run finish",
            "true || sh -c 'wev approval grant apr-1'",
            f"xargs {WEV} approval grant",
            f"env X=1 {WEV} run finish",
            f"script -q /dev/null {WEV} approval grant apr-1",
            f"expect -c 'spawn {WEV} approval grant apr-1'",
        ):
            with self.subTest(line=line):
                self.assertEqual(self.decision(line), ASK)

    def test_the_reason_names_the_engine_command(self) -> None:
        found = self.bash("nohup wev run finish")
        assert found is not None
        self.assertIn("wev command", found["reason"])

    def test_plan_mode_asks_or_denies_too(self) -> None:
        self.wev("run", "finish")
        self.wev("run", "start", "--objective", "x", "--mode", "plan", "--run-id", "r2")
        for line in ("nohup wev run finish", "sh -c 'wev run finish'", "nice wev run finish"):
            with self.subTest(line=line):
                self.assertIn(self.decision(line), (ASK, "deny"))


class LongLineTests(WrapperCase):
    """Word scanning must stay inside the hook's timeout on the longest lines it reads
    in full (under ``MAX_COMMAND_CHARS`` and ``MAX_WORDS``; longer ones are an ``ask``).

    The budget is half of the PreToolUse timeout in ``hooks/hooks.json`` (10 seconds). A
    tighter wall-clock bound failed on a shared CI runner, where the worst case took 2.1 s.
    """

    BUDGET_SECONDS = 5.0
    WORDS = " ".join(f"d/{index}" for index in range(1900))

    def timed(self, line: str) -> tuple[dict[str, str] | None, float]:
        self.assertLess(len(line), bash_guard.MAX_COMMAND_CHARS)
        started = time.monotonic()
        found = self.bash(line)
        return found, time.monotonic() - started

    def test_a_long_wrapped_line_is_judged_quickly(self) -> None:
        for line in (f"nohup ls {self.WORDS}", f"nice nohup timeout 5 ls {self.WORDS}"):
            with self.subTest(line=line[:24]):
                found, spent = self.timed(line)
                self.assertIsNone(found)
                self.assertLess(spent, self.BUDGET_SECONDS)

    def test_a_long_inline_script_is_judged_quickly(self) -> None:
        found, spent = self.timed(f"sh -c 'nohup ls {self.WORDS}'")
        self.assertIsNone(found)
        self.assertLess(spent, self.BUDGET_SECONDS)

    def test_a_sensitive_command_at_the_end_of_a_long_line_still_asks(self) -> None:
        for line in (
            f"nohup env {self.WORDS} wev approval grant apr-1",
            f"sh -c 'nohup ls {self.WORDS} wev run finish'",
        ):
            with self.subTest(line=line[:24]):
                found, spent = self.timed(line)
                assert found is not None
                self.assertEqual(found["decision"], ASK)
                self.assertIn("wev command", found["reason"])
                self.assertLess(spent, self.BUDGET_SECONDS)

    def test_many_engine_references_are_judged_quickly(self) -> None:
        found, spent = self.timed("nohup " + "wev " * 1500 + "--lang en " * 200 + "run finish")
        assert found is not None
        self.assertEqual(found["decision"], ASK)
        self.assertIn("wev command", found["reason"])
        self.assertLess(spent, self.BUDGET_SECONDS)


class OrdinaryCommandTests(WrapperCase):
    def test_read_only_engine_commands_stay_unasked(self) -> None:
        for line in (
            "wev run status",
            "wev approval list",
            "wev approval show apr-1",
            "wev approval verify",
            "wev exec -- ls",
            "nohup wev run status",
            "wev task check task-1",
        ):
            with self.subTest(line=line):
                self.assertIsNone(self.decision(line))

    def test_text_that_only_mentions_the_engine_is_not_a_call(self) -> None:
        for line in (
            "grep -rn 'wev run finish' docs",
            "git commit -m 'document wev approval grant'",
            "echo 'ask the operator to run: wev approval grant apr-1'",
            "ls wev",
        ):
            with self.subTest(line=line):
                self.assertIsNone(self.decision(line))
