"""``wev jev status|ask|batch``, run in-process so the real keychain can never be reached.

``cli.main`` runs here with ``HOME``/``XDG_CONFIG_HOME`` in temporary directories, the
environment cleared of JEV variables and the keychain lookups patched to find nothing.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import time
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

from tests.fixtures.fake_jev_server import fake_jev
from wev_skills import cli
from wev_skills.decisions import jev_http

SECRET = "sk-test-0123456789"
ANSWERS = json.dumps({"answers": {"q": {"answer": True}}}).encode()
QUESTIONS = {"q": {"type": "noul", "instructions": "Is it ok?"}}


def run_main(*argv: str) -> tuple[int, dict[str, Any], str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["--lang", "en", *argv])
    text = out.getvalue()
    return code, json.loads(text) if text.strip() else {}, out.getvalue() + err.getvalue()


class JevCliCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.work = self.dir / "repo"
        self.work.mkdir()
        self.cfg_home = self.dir / "cfg"
        env = {"HOME": str(self.dir), "XDG_CONFIG_HOME": str(self.cfg_home)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("TYPESAFE_API_KEY", "JEV_API_URL"):
            os.environ.pop(name, None)
        for target in (
            mock.patch.object(jev_http, "macos_keychain", lambda: None),
            mock.patch("wev_skills.commands.jev.macos_keychain", lambda: None),
        ):
            target.start()
            self.addCleanup(target.stop)
        previous = Path.cwd()
        os.chdir(self.work)
        self.addCleanup(os.chdir, previous)

    def use_jev(self) -> None:
        config = {"decision": {"provider": "jev"}}
        (self.work / "wev.config.json").write_text(json.dumps(config), encoding="utf-8")

    def write(self, name: str, content: object) -> str:
        path = self.dir / name
        text = content if isinstance(content, str) else json.dumps(content)
        path.write_text(text, encoding="utf-8")
        return str(path)

    @contextlib.contextmanager
    def server(self, *script: tuple[int, bytes, float]) -> Iterator[None]:
        with fake_jev(script) as fake:
            os.environ["JEV_API_URL"] = fake.url
            yield


class StatusTests(JevCliCase):
    def test_status_local_by_default(self) -> None:
        code, data, _ = run_main("jev", "status")
        self.assertEqual(code, 0)
        self.assertEqual(data["provider"], "local")
        self.assertEqual(data["orchestration"], "harness")

    def test_status_jev_with_env_file_key(self) -> None:
        self.use_jev()
        env_file = self.cfg_home / "wev-skills" / ".env"
        env_file.parent.mkdir(parents=True)
        env_file.write_text(f"TYPESAFE_API_KEY={SECRET}\n", encoding="utf-8")
        env_file.chmod(0o600)
        code, data, output = run_main("jev", "status")
        self.assertEqual(code, 0)
        self.assertEqual(data["client"], "builtin")
        self.assertEqual(data["key_source"], "env_file")
        self.assertIsNone(data["key_error"])
        self.assertEqual(data["orchestration"], "wev")
        self.assertNotIn(SECRET, output)

    def test_status_jev_without_key_is_harness(self) -> None:
        self.use_jev()
        code, data, _ = run_main("jev", "status")
        self.assertEqual(code, 0)
        self.assertEqual(data["orchestration"], "harness")
        self.assertIsNone(data["key_source"])
        self.assertIsInstance(data["key_error"], str)

    def test_status_loopback_endpoint_needs_no_key(self) -> None:
        self.use_jev()
        os.environ["JEV_API_URL"] = "http://127.0.0.1:9/v1/systemone"
        _, data, _ = run_main("jev", "status")
        self.assertEqual(data["orchestration"], "wev")
        self.assertEqual(data["endpoint"], "http://127.0.0.1:9/v1/systemone")

    def test_status_bad_endpoint_is_reported_not_raised(self) -> None:
        self.use_jev()
        os.environ["JEV_API_URL"] = "http://example.com/v1"
        os.environ["TYPESAFE_API_KEY"] = SECRET
        code, data, output = run_main("jev", "status")
        self.assertEqual(code, 0)
        self.assertEqual(data["orchestration"], "harness")
        self.assertIn("https", data["key_error"])
        self.assertNotIn(SECRET, output)

    def test_status_local_provider_never_looks_up_the_key(self) -> None:
        os.environ["TYPESAFE_API_KEY"] = SECRET

        def forbidden() -> str | None:
            raise AssertionError("the keychain must not be read for provider local")

        with mock.patch("wev_skills.commands.jev.macos_keychain", forbidden):
            _, data, output = run_main("jev", "status")
        self.assertIsNone(data["key_source"])
        self.assertIsNone(data["key_error"])
        self.assertEqual(data["orchestration"], "harness")
        self.assertNotIn(SECRET, output)

    def use_program(self, command: str) -> None:
        config = {"decision": {"provider": "jev", "jev": {"command": command}}}
        (self.work / "wev.config.json").write_text(json.dumps(config), encoding="utf-8")

    def test_status_missing_program_is_harness_with_a_reason(self) -> None:
        self.use_program(str(self.dir / "no-such-jev"))
        code, data, _ = run_main("jev", "status")
        self.assertEqual(code, 0)
        self.assertEqual(data["client"], "program")
        self.assertEqual(data["orchestration"], "harness")
        self.assertIn("no-such-jev", data["key_error"])

    def test_status_usable_program_is_wev(self) -> None:
        program = self.dir / "jev-tool"
        program.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        program.chmod(0o755)
        self.use_program(str(program))
        _, data, _ = run_main("jev", "status")
        self.assertEqual(data["orchestration"], "wev")
        self.assertIsNone(data["key_error"])


class AskTests(JevCliCase):
    def test_ask_prints_answers(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        with self.server((200, ANSWERS, 0)):
            code, data, _ = run_main("jev", "ask", "--questions", questions, "--state", "x")
        self.assertEqual(code, 0)
        self.assertEqual(data, {"answers": {"q": {"answer": True}}})

    def test_ask_redacts_the_state(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        state_file = self.write("s.txt", f"token=ghp_{'a' * 36} done")
        with fake_jev([(200, ANSWERS, 0)]) as fake:
            os.environ["JEV_API_URL"] = fake.url
            run_main("jev", "ask", "--questions", questions, "--state-file", state_file)
            sent = fake.requests[0].body["state"]
        self.assertNotIn("a" * 36, sent)

    def test_ask_invalid_questions_exit_2(self) -> None:
        questions = self.write("q.json", {"q": {"type": "nope", "instructions": "x"}})
        code, _, _ = run_main("jev", "ask", "--questions", questions, "--state", "x")
        self.assertEqual(code, 2)

    def test_ask_unavailable_exits_8(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        with self.server((500, b"{}", 0)):
            code, _, _ = run_main("jev", "ask", "--questions", questions, "--state", "x")
        self.assertEqual(code, 8)

    def test_ask_needs_a_state(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        code, _, _ = run_main("jev", "ask", "--questions", questions)
        self.assertEqual(code, 2)


class BatchTests(JevCliCase):
    def items(self, count: int) -> str:
        lines = [json.dumps({"id": f"i{n}", "state": f"s{n}"}) for n in range(count)]
        return self.write("items.jsonl", "\n".join(lines) + "\n")

    def test_batch_keeps_order_and_counts_failures(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        out = str(self.dir / "out.jsonl")
        script = ((200, ANSWERS, 0), (500, b"{}", 0), (200, ANSWERS, 0))
        with self.server(*script):
            code, data, _ = run_main(
                "jev", "batch", "--questions", questions, "--items", self.items(3), "--out", out
            )
        rows = [json.loads(line) for line in Path(out).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["id"] for row in rows], ["i0", "i1", "i2"])
        self.assertEqual(data, {"ok": 2, "failed": 1, "out": out})
        self.assertEqual(sum("error" in row for row in rows), 1)
        self.assertEqual(code, 8)

    def fake_asker(self, behaviour: Any) -> Any:
        return mock.patch("wev_skills.commands.jev.build_http_asker", lambda *_a, **_k: behaviour)

    def test_batch_order_holds_when_completion_order_is_reversed(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        out = str(self.dir / "out.jsonl")

        def reversed_completion(_questions: object, state: str) -> str:
            time.sleep((3 - int(state[1:])) * 0.15)  # s0 finishes last, s2 first
            return json.dumps({"state": state})

        with self.fake_asker(reversed_completion):
            code, _, _ = run_main(
                "jev", "batch", "--questions", questions, "--items", self.items(3), "--out", out
            )
        rows = [json.loads(line) for line in Path(out).read_text(encoding="utf-8").splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual([row["id"] for row in rows], ["i0", "i1", "i2"])
        self.assertEqual([row["answers"]["state"] for row in rows], ["s0", "s1", "s2"])

    def test_batch_unexpected_error_keeps_the_other_answers(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        out = str(self.dir / "out.jsonl")

        def flaky(_questions: object, state: str) -> str:
            if state == "s1":
                raise RuntimeError(f"Bearer {SECRET}")
            return json.dumps({"state": state})

        with self.fake_asker(flaky):
            code, data, output = run_main(
                "jev", "batch", "--questions", questions, "--items", self.items(3), "--out", out
            )
        text = Path(out).read_text(encoding="utf-8")
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertEqual((code, data["ok"], data["failed"]), (8, 2, 1))
        self.assertEqual([("error" in row) for row in rows], [False, True, False])
        self.assertIn("RuntimeError", rows[1]["error"])
        self.assertNotIn(SECRET, text + output)

    def test_batch_all_ok_exits_0(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        out = str(self.dir / "out.jsonl")
        with self.server((200, ANSWERS, 0)):
            code, data, _ = run_main(
                "jev", "batch", "--questions", questions, "--items", self.items(2), "--out", out
            )
        self.assertEqual((code, data["ok"], data["failed"]), (0, 2, 0))

    def test_batch_bad_line_exit_2_names_the_line(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        items = self.write("bad.jsonl", '{"id": "a", "state": "s"}\nnot json\n')
        out = str(self.dir / "out.jsonl")
        code, _, output = run_main(
            "jev", "batch", "--questions", questions, "--items", items, "--out", out
        )
        self.assertEqual(code, 2)
        self.assertIn("line 2", output)
        self.assertFalse(Path(out).exists())

    def test_batch_item_without_state_exit_2(self) -> None:
        questions = self.write("q.json", QUESTIONS)
        items = self.write("bad.jsonl", '{"id": "a"}\n')
        out = str(self.dir / "o.jsonl")
        code, _, _ = run_main(
            "jev", "batch", "--questions", questions, "--items", items, "--out", out
        )
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
