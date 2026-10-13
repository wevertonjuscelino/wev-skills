"""The ``bin/wev`` launcher: the interpreter version is checked before the package loads."""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import io
import unittest
from pathlib import Path
from types import ModuleType

LAUNCHER = Path(__file__).resolve().parents[2] / "bin" / "wev"


def load_launcher() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("wev_launcher", str(LAUNCHER))
    spec = importlib.util.spec_from_loader("wev_launcher", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class VersionGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = load_launcher()

    def guard(self, version: tuple[int, ...], *args: str) -> tuple[int | None, str]:
        stream = io.StringIO()
        return self.launcher.version_guard(version, list(args), stream), stream.getvalue()

    def test_a_supported_interpreter_passes_silently(self) -> None:
        for version in ((3, 14, 0), (3, 14, 7), (3, 15, 0), (4, 0, 0)):
            self.assertEqual(self.guard(version, "hook", "pre-tool-use"), (None, ""))

    def test_a_hook_under_an_old_interpreter_exits_zero_with_one_line(self) -> None:
        for version, shown in (((3, 9, 18), "3.9"), ((3, 13, 5), "3.13")):
            for args in (("hook", "pre-tool-use"), ("--lang", "en", "hook", "session-context")):
                code, text = self.guard(version, *args)
                self.assertEqual((code, text.count("\n")), (0, 1))
                self.assertIn(shown, text)
                self.assertIn("needs 3.14", text)
                self.assertIn("nothing was checked", text)

    def test_any_other_command_fails_with_a_clear_message(self) -> None:
        for args in (("run", "status"), (), ("--config", "hook", "run", "start"), ("exec", "hook")):
            code, text = self.guard((3, 13, 0), *args)
            self.assertEqual((code, text.count("\n")), (1, 1))
            self.assertIn("needs Python 3.14", text)

    def test_the_guard_runs_before_the_package_is_imported(self) -> None:
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        top_level = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
        names = {alias.name for node in top_level for alias in node.names}
        self.assertEqual(names, {"os", "sys"})

    def test_the_launcher_avoids_syntax_an_old_interpreter_cannot_parse(self) -> None:
        tree = ast.parse(LAUNCHER.read_text(encoding="utf-8"))
        newer = (ast.JoinedStr, ast.NamedExpr, ast.AnnAssign, ast.Match)
        self.assertFalse([node for node in ast.walk(tree) if isinstance(node, newer)])
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        self.assertTrue(all(node.returns is None for node in functions))


if __name__ == "__main__":
    unittest.main()
