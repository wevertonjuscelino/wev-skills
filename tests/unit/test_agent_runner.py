import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.adapters.claude_code.agent_runner import (
    READ_ONLY_TOOLS,
    UNATTENDED_TOOLS,
    ClaudeAgentRunner,
)
from wev_skills.adapters.claude_code.subagent import render_subagent
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry, builtin_directories
from wev_skills.core.errors import ValidationError
from wev_skills.core.ports import SubprocessRunner

FAKE = Path(__file__).resolve().parents[1] / "fixtures" / "fake_claude_agent.py"
_REGISTRY = AgentRegistry().discover(builtin_directories(), False)
SPEC = AgentFactory(_REGISTRY).resolve(_REGISTRY.get("senior-engineer"))
FORBIDDEN = ("--dangerously-skip-permissions", "--bare", "bypassPermissions")


class AgentRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.plugin = self.root / "plugin"
        (self.plugin / ".claude-plugin").mkdir(parents=True)
        (self.plugin / "hooks").mkdir()
        (self.plugin / ".claude-plugin" / "plugin.json").write_text("{}")
        (self.plugin / "hooks" / "hooks.json").write_text("{}")
        self.workspace = self.root / "ws"
        self.workspace.mkdir()
        self.log = self.root / "log"
        env = mock.patch.dict(os.environ, {"FAKE_LOG": str(self.log)})
        env.start()
        self.addCleanup(env.stop)
        self.runner = ClaudeAgentRunner(SubprocessRunner(), self.plugin, program=str(FAKE))

    def calls(self) -> list[dict]:
        return [json.loads(x) for x in self.log.read_text().splitlines()]

    def test_argv_is_pinned(self) -> None:
        tools = ",".join(UNATTENDED_TOOLS)
        rendered = render_subagent(SPEC)
        body = rendered.split("\n---\n", 1)[1].strip("\n")
        result = self.runner.run_agent(self.workspace, SPEC, "do it", 30)
        call = self.calls()[0]
        self.assertEqual(
            call["argv"],
            ["-p", "Task:\ndo it", "--output-format", "json", "--restricted",
             "--strict-mcp-config", "--plugin-dir", str(self.plugin),
             "--tools", tools, "--allowedTools", tools, "--permission-mode", "dontAsk",
             "--no-session-persistence", "--append-system-prompt", body],
        )  # fmt: skip
        self.assertEqual(Path(call["cwd"]).resolve(), self.workspace.resolve())
        self.assertFalse(any(f in a for a in call["argv"] for f in FORBIDDEN))
        self.assertTrue(result.ok)

    def test_runner_passes_read_only_tools(self) -> None:
        self.runner.run_agent(self.workspace, SPEC, "look", 30, tools=READ_ONLY_TOOLS)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep")
        self.assertEqual(argv[argv.index("--allowedTools") + 1], "Read,Glob,Grep")

    def test_runner_default_tools_unchanged(self) -> None:
        self.assertEqual(UNATTENDED_TOOLS, ("Read", "Edit", "Write", "Glob", "Grep", "Bash"))
        self.runner.run_agent(self.workspace, SPEC, "do it", 30)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Edit,Write,Glob,Grep,Bash")

    def test_ask_has_no_tools(self) -> None:
        self.runner.ask("why?", 30)
        call = self.calls()[0]
        self.assertEqual(
            call["argv"],
            ["-p", "Request:\nwhy?", "--output-format", "json", "--restricted",
             "--strict-mcp-config", "--plugin-dir", str(self.plugin),
             "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence"],
        )  # fmt: skip
        self.assertNotIn("--allowedTools", call["argv"])
        self.assertFalse(Path(call["cwd"]).exists())  # fresh scratch dir removed

    def test_result_field_is_output(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_STDOUT": '{"result": "a lesson"}'}):
            result = self.runner.ask("x", 30)
        self.assertEqual((result.ok, result.output), (True, "a lesson"))

    def test_non_json_is_not_ok(self) -> None:
        for out in ("not json", '{"other": 1}', '{"result": 3}', "[]"):
            with mock.patch.dict(os.environ, {"FAKE_CLAUDE_STDOUT": out}):
                self.assertFalse(self.runner.ask("x", 30).ok, out)

    def test_is_error_is_not_ok(self) -> None:
        with mock.patch.dict(
            os.environ, {"FAKE_CLAUDE_STDOUT": '{"result": "x", "is_error": true}'}
        ):
            self.assertFalse(self.runner.ask("x", 30).ok)

    def test_prompt_cannot_be_a_flag_or_subcommand(self) -> None:
        for text in ("--dangerously-skip-permissions", "install"):
            self.log.unlink(missing_ok=True)
            self.runner.run_agent(self.workspace, SPEC, text, 30)
            self.runner.ask(text, 30)
            for call in self.calls():
                argv = call["argv"]
                self.assertNotIn(text, argv)
                self.assertTrue(argv[argv.index("-p") + 1].startswith(("Task:\n", "Request:\n")))

    def test_system_prompt_never_starts_with_a_dash(self) -> None:
        target = "wev_skills.adapters.claude_code.agent_runner.render_subagent"
        with mock.patch(target, return_value="---\nname: x\n---\n--version\n"):
            self.runner.run_agent(self.workspace, SPEC, "x", 30)
        argv = self.calls()[0]["argv"]
        self.assertEqual(argv[argv.index("--append-system-prompt") + 1], " --version")

    def test_the_calling_session_variables_do_not_reach_the_child(self) -> None:
        session = {
            "CLAUDECODE": "1",
            "CLAUDE_PID": "42",
            "CLAUDE_CODE_ENTRYPOINT": "cli",
            "CLAUDE_CODE_SESSION_ID": "s",
            "ANTHROPIC_BASE_URL": "http://example.invalid",
            "CLAUDE_CODE_OAUTH_TOKEN": "example_oauth",
        }
        with mock.patch.dict(os.environ, session):
            self.runner.run_agent(self.workspace, SPEC, "x", 30)
            self.runner.ask("x", 30)
        for call in self.calls():
            env = call["env"]
            session_keys = [k for k in env if k.startswith("CLAUDE_CODE_")]
            self.assertEqual(session_keys, ["CLAUDE_CODE_OAUTH_TOKEN"])  # auth is kept
            self.assertNotIn("CLAUDECODE", env)
            self.assertNotIn("CLAUDE_PID", env)
            self.assertEqual(env["PATH"], os.environ["PATH"])
            self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://example.invalid")

    def test_bad_output_carries_a_cleaned_redacted_stderr_tail(self) -> None:
        noise = "x" * 600 + "\n\x1b[31mapi_key=example_not_a_real_value boom"
        with mock.patch.dict(
            os.environ, {"FAKE_CLAUDE_STDOUT": "not json", "FAKE_CLAUDE_STDERR": noise}
        ):
            result = self.runner.ask("x", 30)
        self.assertFalse(result.ok)
        self.assertIn("boom", result.output)
        self.assertNotIn("\x1b", result.output)
        self.assertNotIn("example_not_a_real_value", result.output)
        self.assertNotIn("x" * 501, result.output)

    def test_a_secret_split_by_escapes_and_cut_by_the_tail_is_not_shown(self) -> None:
        secret = "pass\x1b[0mword=example_not_a_real_value"  # one line once sanitized
        noise = "x" * 600 + "\n" + secret + "\n" + "y" * 484 + "\nboom"  # cut inside it
        with mock.patch.dict(
            os.environ, {"FAKE_CLAUDE_STDOUT": "not json", "FAKE_CLAUDE_STDERR": noise}
        ):
            output = self.runner.ask("x", 30).output
        self.assertIn("boom", output)
        self.assertNotIn("real_value", output)

    def test_a_secret_split_by_an_escape_is_redacted_after_cleaning(self) -> None:
        noise = "pass\x1b[0mword=example_not_a_real_value boom"
        with mock.patch.dict(
            os.environ, {"FAKE_CLAUDE_STDOUT": "not json", "FAKE_CLAUDE_STDERR": noise}
        ):
            output = self.runner.ask("x", 30).output
        self.assertIn("password=", output)
        self.assertNotIn("real_value", output)

    def test_nonzero_exit_is_not_ok(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_EXIT": "1"}):
            self.assertFalse(self.runner.ask("x", 30).ok)

    def test_timeout_is_not_ok(self) -> None:
        with mock.patch.dict(os.environ, {"FAKE_CLAUDE_SLEEP": "5"}):
            result = self.runner.ask("x", 0.3)
        self.assertEqual((result.ok, result.timed_out), (False, True))

    def test_missing_plugin_is_refused(self) -> None:
        (self.plugin / "hooks" / "hooks.json").unlink()
        with self.assertRaises(ValidationError) as caught:
            self.runner.run_agent(self.workspace, SPEC, "x", 30)
        self.assertEqual(caught.exception.code, "plugin_missing")
        with self.assertRaises(ValidationError):
            self.runner.ask("x", 30)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
