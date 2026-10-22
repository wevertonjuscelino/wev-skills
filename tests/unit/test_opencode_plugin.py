import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.adapters.opencode_plugin import render_plugin

HAS_NODE = shutil.which("node") is not None
DRIVER = """
const mod = await import(process.argv[2]);
const hooks = await mod.WevGuard({ directory: process.argv[3] });
const tool = process.argv[4];
const output = { args: { command: "ls" } };
const warnings = [];
console.warn = (m) => warnings.push(m);
try {
  await hooks["tool.execute.before"]({ tool }, output);
  console.log(JSON.stringify({ threw: null, warnings }));
} catch (e) {
  console.log(JSON.stringify({ threw: String(e.message), warnings }));
}
"""


class PluginTextTests(unittest.TestCase):
    def test_plugin_spawns_absolute_wev_without_shell(self) -> None:
        wev = Path('/tmp/a b/"q"/bin/wev')
        text = render_plugin(wev)
        self.assertIn(json.dumps(str(wev)), text)
        self.assertIn("spawnSync", text)
        for forbidden in ("shell: true", "execSync", "exec(", "$`"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn("wev-placeholder", text)
        self.assertIn('"--harness", "opencode"', text)

    def test_plugin_runs_wev_with_the_install_interpreter(self) -> None:
        python = "/opt/my py/python3"
        with mock.patch.object(sys, "executable", python):
            text = render_plugin(Path("/w/bin/wev"))
        self.assertIn(f"const PYTHON = {json.dumps(python)};", text)
        self.assertIn('spawnSync(PYTHON, [WEV, "hook", "pre-tool-use"', text)


@unittest.skipUnless(HAS_NODE, "node is not on PATH")
class PluginNodeTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        (self.tmp / "driver.mjs").write_text(DRIVER)

    def fake_wev(self, body: str) -> Path:
        path = self.tmp / "wev"
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def run_plugin(self, wev: Path, tool: str = "bash") -> dict[str, object]:
        plugin = self.tmp / "guard.mjs"
        with mock.patch.object(sys, "executable", "/bin/sh"):  # the fake wev is a sh script
            plugin.write_text(render_plugin(wev))
        done = subprocess.run(
            ["node", str(self.tmp / "driver.mjs"), str(plugin), str(self.tmp), tool],
            capture_output=True, text=True, check=True, timeout=30,
        )  # fmt: skip
        result: dict[str, object] = json.loads(done.stdout)
        return result

    def test_plugin_denies_on_guard_deny(self) -> None:
        wev = self.fake_wev('cat >/dev/null\necho \'{"decision":"deny","reason":"nope"}\'\n')
        self.assertEqual(self.run_plugin(wev)["threw"], "nope")

    def test_plugin_sends_the_documented_payload(self) -> None:
        wev = self.fake_wev(f"cat > {self.tmp}/stdin.json\n"
                            f"echo \"$@\" > {self.tmp}/argv.txt\n")  # fmt: skip
        self.assertIsNone(self.run_plugin(wev)["threw"])
        sent = json.loads((self.tmp / "stdin.json").read_text())
        self.assertEqual(sent, {"tool": "bash", "args": {"command": "ls"}, "cwd": str(self.tmp)})
        self.assertEqual(
            (self.tmp / "argv.txt").read_text().strip(), "hook pre-tool-use --harness opencode"
        )

    def test_plugin_fails_closed_when_wev_missing(self) -> None:
        result = self.run_plugin(self.tmp / "absent")
        self.assertIsNotNone(result["threw"])

    def test_plugin_fails_closed_on_bad_output_or_exit(self) -> None:
        for body in ("echo not-json\n", "exit 3\n", 'echo \'{"decision":"maybe"}\'\n'):
            with self.subTest(body=body):
                self.assertIsNotNone(self.run_plugin(self.fake_wev(body))["threw"])

    def test_plugin_allows_silently_and_warns_on_reason(self) -> None:
        silent = self.run_plugin(self.fake_wev("cat >/dev/null\n"))
        self.assertEqual(silent, {"threw": None, "warnings": []})
        warn = self.fake_wev('cat >/dev/null\necho \'{"decision":"allow","reason":"care"}\'\n')
        self.assertEqual(self.run_plugin(warn), {"threw": None, "warnings": ["care"]})

    def test_plugin_fails_closed_on_json_that_is_not_an_object(self) -> None:
        for body in ("echo null\n", "echo 3\n", "echo '\"allow\"'\n", "echo '[]'\n"):
            with self.subTest(body=body):
                self.assertIsNotNone(self.run_plugin(self.fake_wev(body))["threw"])

    def test_plugin_ignores_other_tools(self) -> None:
        wev = self.fake_wev("exit 3\n")
        self.assertIsNone(self.run_plugin(wev, tool="read")["threw"])
