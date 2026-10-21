import contextlib
import io
import json
import shlex
import tempfile
import unittest
from pathlib import Path

from wev_skills import cli
from wev_skills.adapters.harness_package import build_package, render_skill_text, skipped_notes
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.core.wiring import REPO_ROOT

WEV = REPO_ROOT / "bin" / "wev"
SPACED = Path("/tmp/my clone's dir/bin/wev")
SKILL_FILES = {
    p.relative_to(REPO_ROOT / "skills").as_posix()
    for p in (REPO_ROOT / "skills").rglob("*")
    if p.is_file()
}
AGENT_IDS = {p.stem for p in (REPO_ROOT / "agents").glob("*.md")}


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _files(root: Path) -> set[str]:
    return set(_tree(root))


def _hook_commands(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]]


class RenderTests(unittest.TestCase):
    def test_render_replaces_every_placeholder(self) -> None:
        for name in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
            text = render_skill_text(name.read_text(encoding="utf-8"), WEV)
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", text, name)
        self.assertEqual(len(list((REPO_ROOT / "skills").glob("*/SKILL.md"))), 7)

    def test_render_quotes_a_path_with_spaces(self) -> None:
        out = render_skill_text('run "${CLAUDE_PLUGIN_ROOT}/bin/wev" eval list', SPACED)
        self.assertEqual(shlex.split(out), ["run", str(SPACED), "eval", "list"])
        out = render_skill_text("run ${CLAUDE_PLUGIN_ROOT}/bin/wev eval", SPACED)
        self.assertEqual(shlex.split(out), ["run", str(SPACED), "eval"])
        out = render_skill_text("see ${CLAUDE_PLUGIN_ROOT}/examples/plan.json", SPACED)
        self.assertEqual(shlex.split(out), ["see", f"{SPACED.parent.parent}/examples/plan.json"])


class LayoutTests(unittest.TestCase):
    def _build(self, target: str, wev: Path = WEV) -> tuple[Path, list[Path]]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "pkg"
        return out, build_package(target, out, wev)

    def _skills(self) -> set[str]:
        return {f"skills/{f}" for f in SKILL_FILES}

    def test_codex_layout(self) -> None:
        out, written = self._build("codex")
        self.assertEqual(_files(out), {".codex-plugin/plugin.json", "hooks.json"} | self._skills())
        self.assertEqual({p.relative_to(out).as_posix() for p in written}, _files(out))
        manifest = json.loads((out / ".codex-plugin/plugin.json").read_text())
        self.assertEqual(manifest["skills"], "./skills/")
        self.assertEqual(manifest["hooks"], "./hooks.json")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+")
        hooks = json.loads((out / "hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "PreToolUse"})
        self.assertEqual(hooks["PreToolUse"][0]["matcher"], "Bash")

    def test_gemini_layout(self) -> None:
        out, _ = self._build("gemini")
        agents = {f"agents/{i}.md" for i in AGENT_IDS}
        self.assertEqual(
            _files(out), {"gemini-extension.json", "hooks/hooks.json"} | self._skills() | agents
        )
        manifest = json.loads((out / "gemini-extension.json").read_text())
        self.assertEqual(manifest["name"], "wev-skills")
        self.assertNotIn("contextFileName", manifest)
        hooks = json.loads((out / "hooks/hooks.json").read_text())["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "BeforeTool"})
        self.assertEqual(hooks["BeforeTool"][0]["matcher"], "run_shell_command")
        agent = (out / "agents/architect.md").read_text()
        self.assertTrue(agent.startswith('---\nname: "architect"\ndescription: "'))

    def test_opencode_layout(self) -> None:
        out, _ = self._build("opencode")
        agents = {f"agents/{i}.md" for i in AGENT_IDS}
        self.assertEqual(_files(out), {"plugins/wev-guard.js"} | self._skills() | agents)
        agent = (out / "agents/architect.md").read_text()
        self.assertIn("mode: subagent", agent.split("---")[1])
        self.assertTrue((out / "plugins/wev-guard.js").read_text().startswith("// wev-placeholder"))

    def test_hook_commands_use_absolute_wev(self) -> None:
        for target, path in (("codex", "hooks.json"), ("gemini", "hooks/hooks.json")):
            out, _ = self._build(target, SPACED)
            commands = _hook_commands(out / path)
            self.assertEqual(len(commands), 2)
            for command in commands:
                argv = shlex.split(command)
                self.assertEqual(argv[0], str(SPACED))
                self.assertEqual(argv[-2:], ["--harness", target])

    def test_export_is_deterministic(self) -> None:
        for target in ("codex", "gemini", "opencode"):
            first, _ = self._build(target)
            second, _ = self._build(target)
            self.assertEqual(_tree(first), _tree(second))

    def test_skipped_notes_state_the_limits(self) -> None:
        self.assertTrue(any("wev-placeholder" in n for n in skipped_notes("opencode")))
        self.assertTrue(any("inferred" in n for n in skipped_notes("gemini")))

    def test_non_empty_out_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "keep.txt").write_text("x")
            with self.assertRaises(StateConflict):
                build_package("codex", Path(tmp), WEV)
            self.assertEqual(_files(Path(tmp)), {"keep.txt"})

    def test_unknown_target_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            self._build("emacs")


class ExportCommandTests(unittest.TestCase):
    def test_export_prints_files_and_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = cli.main(["harness", "export", "--target", "codex", "--out", tmp + "/o"])
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["target"], "codex")
            self.assertTrue(all(Path(f).is_file() for f in data["files"]))
            self.assertTrue(any("subagents not exported for codex" in s for s in data["skipped"]))


if __name__ == "__main__":
    unittest.main()
