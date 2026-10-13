from __future__ import annotations

import sys
import unittest

from wev_skills.core.ports import AgentLike, Clock, SubprocessRunner, SystemClock


class SubprocessRunnerTests(unittest.TestCase):
    def run_py(self, code: str, timeout: float | None = None):  # type: ignore[no-untyped-def]
        return SubprocessRunner().run([sys.executable, "-c", code], None, timeout, None)

    def test_success_captures_output(self) -> None:
        result = self.run_py("import sys; print('out'); print('err', file=sys.stderr)")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.stdout.strip(), "out")
        self.assertEqual(result.stderr.strip(), "err")
        self.assertFalse(result.timed_out)
        self.assertEqual(result.argv[0], sys.executable)
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_non_zero_exit_does_not_raise(self) -> None:
        result = self.run_py("import sys; sys.exit(3)")
        self.assertEqual(result.exit_code, 3)
        self.assertFalse(result.timed_out)

    def test_timeout_is_reported_not_raised(self) -> None:
        result = self.run_py("import time; time.sleep(10)", timeout=0.3)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertLess(result.duration_ms, 5000)

    def test_no_shell_interpretation(self) -> None:
        result = SubprocessRunner().run(["echo", "a; echo b"], None, None, None)
        self.assertEqual(result.stdout.strip(), "a; echo b")

    def test_missing_binary_does_not_raise(self) -> None:
        result = SubprocessRunner().run(["/no/such/binary-wev"], None, None, None)
        self.assertEqual(result.exit_code, 127)
        self.assertIn("FileNotFoundError", result.stderr)

    def test_env_and_cwd_are_honored(self) -> None:
        code = "import os; print(os.environ.get('WEV_T')); print(os.getcwd())"
        result = SubprocessRunner().run([sys.executable, "-c", code], "/", None, {"WEV_T": "1"})
        lines = result.stdout.split()
        self.assertEqual(lines[0], "1")
        self.assertEqual(lines[1], "/")


class ProtocolTests(unittest.TestCase):
    def test_system_clock_is_monotonic_enough(self) -> None:
        clock: Clock = SystemClock()
        first = clock.now()
        self.assertGreater(first, 1_600_000_000)
        self.assertGreaterEqual(clock.now(), first)

    def test_agent_like_is_structural(self) -> None:
        class Spec:
            id = "a"
            description = "d"
            specialties = ("x",)

        self.assertIsInstance(Spec(), AgentLike)
        self.assertNotIsInstance(object(), AgentLike)


if __name__ == "__main__":
    unittest.main()
