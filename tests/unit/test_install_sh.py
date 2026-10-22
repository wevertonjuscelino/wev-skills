"""``install.sh`` run for real in a temp HOME, with fake harness CLIs, docker, git and curl.

PATH is ``tests/fixtures/fake_bin`` first, then a directory of symlinks to the real bash,
python and coreutils, so only the harness CLIs, docker, git and curl are fakes. Every fake
appends its argv to ``$FAKE_LOG``. The network is cut with a dead HTTPS proxy, so ``skills
update`` fails fast and offline; the tests that need a rea version seed Part 4's state.
Questions need a terminal: ``start_new_session`` gives the script none, and ``drive`` gives it
a pty (with stdin a different pipe) to prove the answers come from the terminal.
"""

from __future__ import annotations

import json
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

from tests.fixtures.fake_jev_server import fake_jev
from wev_skills.third_party.state import SourceState, State, save

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "install.sh"
FAKE_BIN = ROOT / "tests" / "fixtures" / "fake_bin"
BASH = shutil.which("bash") or "/bin/bash"
COREUTILS = ("env", "uname", "mktemp", "rm", "mkdir", "mv", "chmod", "cat", "dirname", "stty")
DEAD = "http://127.0.0.1:1"
PLUGIN = "wev-skills@wev-skills-marketplace"
KEY = "typed-key-A1b2C3d4E5f6G7h8"
ANSWERS = json.dumps({"answers": {"q": {"answer": True}}}).encode()
HELPER = (
    "import os, sys, termios, fcntl; os.setsid(); fcntl.ioctl(1, termios.TIOCSCTTY, 0); "
    "os.execv(sys.argv[1], sys.argv[1:])"
)
FLAGS = ("--yes", "--lang", "--harness", "--jev", "--no-jev") + (
    "--rea-mode",
    "--source",
    "--uninstall",
    "--purge",
    "--help",
)


class InstallCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        for name in ("home", "data", "conf", "work", "tmpdir"):
            (self.dir / name).mkdir()
        self.log = self.dir / "fake.log"
        self.tools = self.make_tools()
        # wev finds docker on permissions.exec_path, never on PATH; the user tier carries it
        (self.dir / "conf" / "wev-skills").mkdir(mode=0o700)
        exec_path = {"permissions": {"exec_path": [str(FAKE_BIN)]}}
        (self.dir / "conf" / "wev-skills" / "wev.config.json").write_text(json.dumps(exec_path))

    def assertInstalled(self, done: subprocess.CompletedProcess[str]) -> None:
        """Offline, exactly rea, agent-skills and activate fail; nothing else does."""
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("Finished with 3 failures", done.stdout)
        self.assertNotIn("Cannot continue", done.stderr)

    def assertFinished(self, code: int, out: str) -> None:
        self.assertEqual(code, 1, out)
        self.assertIn("Finished with 3 failures", out)

    def make_tools(self, python: bool = True, extra: tuple[str, ...] = ()) -> Path:
        tools = Path(tempfile.mkdtemp(dir=self.dir))
        for name in ("bash", *COREUTILS):
            os.symlink(shutil.which(name) or "/bin/" + name, tools / name)
        if python:
            os.symlink(sys.executable, tools / "python3")
        for name in ("node", "npm", *extra):
            stub = tools / name
            stub.write_text("#!/bin/sh\nexit 0\n")
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        return tools

    def env(self, tools: Path | None = None, **extra: str) -> dict[str, str]:
        env = {
            "HOME": str(self.dir / "home"),
            "XDG_DATA_HOME": str(self.dir / "data"),
            "XDG_CONFIG_HOME": str(self.dir / "conf"),
            "TMPDIR": str(self.dir / "tmpdir"),
            "FAKE_LOG": str(self.log),
            "FAKE_REPO": str(ROOT),
            "LANG": "en_US.UTF-8",
            "PATH": f"{FAKE_BIN}:{tools or self.tools}",
            "HTTPS_PROXY": DEAD,
            "HTTP_PROXY": DEAD,
            "NO_PROXY": "127.0.0.1",  # the fake JEV server is local; everything else is cut
        }
        return {**env, **extra}

    def run_script(
        self, *args: str, stdin: str = "", **extra: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - fixed argv, a temp HOME
            [BASH, str(SCRIPT), *args],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=self.dir / "work",
            env=self.env(**extra),
            start_new_session=True,  # no controlling terminal: /dev/tty cannot be opened
            timeout=180,
            check=False,
        )

    def install(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        base = ["--yes", "--lang", "en", "--no-jev", "--source", str(ROOT)]
        return self.run_script(*base, *args, **extra)

    def drive(
        self,
        args: list[str],
        replies: list[tuple[bytes, bytes, bool]],
        stdin: str = "",
        **extra: str,
    ) -> tuple[int, str]:
        """Run the script on a pty; each (marker, reply, hidden) answers one prompt in order."""
        master, slave = os.openpty()
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, a temp HOME
            [sys.executable, "-c", HELPER, BASH, str(SCRIPT), *args],
            stdin=subprocess.PIPE,
            stdout=slave,
            stderr=slave,
            cwd=self.dir / "work",
            env=self.env(**extra),
        )
        assert proc.stdin is not None
        proc.stdin.write(stdin.encode())
        proc.stdin.close()
        out, seen, pending = b"", 0, list(replies)
        deadline = time.monotonic() + 120  # the slave stays open here to read ECHO afterwards
        try:
            while True:
                if time.monotonic() > deadline:
                    raise AssertionError("timed out: " + out.decode(errors="replace"))
                exited = proc.poll() is not None
                if not select.select([master], [], [], 0 if exited else 0.05)[0]:
                    if exited:
                        break
                    continue
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    chunk = b""
                if exited and not chunk:
                    break
                out += chunk
                while pending and pending[0][0] in out[seen:]:
                    marker, reply, hidden = pending.pop(0)
                    seen = out.index(marker, seen) + len(marker)
                    while hidden and termios.tcgetattr(master)[3] & termios.ECHO:
                        if time.monotonic() > deadline:  # `read -s` never turned echo off
                            raise AssertionError("echo stayed on: " + out.decode(errors="replace"))
                        time.sleep(0.02)
                    os.write(master, reply)
            code = proc.wait(timeout=10)
            self.echo_after = bool(termios.tcgetattr(master)[3] & termios.ECHO)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            os.close(master)
            os.close(slave)
        return code, out.decode(errors="replace")

    def logged(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def seed_rea(self) -> None:
        state = State({"rea": SourceState(active="1.2.3")})
        save(self.dir / "data" / "wev-skills" / "third-party" / "state.json", state)

    def user_config(self) -> dict[str, object]:
        return json.loads((self.dir / "conf" / "wev-skills" / "wev.config.json").read_text())

    def files_containing(self, text: str) -> list[Path]:
        return [
            p
            for p in self.dir.rglob("*")
            if p.is_file() and not p.is_symlink() and text.encode() in p.read_bytes()
        ]


class ScriptTextTest(unittest.TestCase):
    text = SCRIPT.read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

    def test_has_no_eval_no_shell_strings_and_no_piped_download(self) -> None:
        for pattern in (r"\beval\b", r"\b(?:ba)?sh -c\b", r"\|\s*(?:ba)?sh\b"):
            self.assertIsNone(re.search(pattern, self.code), pattern)

    def test_never_puts_an_expansion_in_a_command_position(self) -> None:
        # a command word is a literal or a quoted "$VAR"; a bare $VAR would be word-split
        position = re.compile(r"(?:^|[;&|(]|\bthen|\bdo|\belse|\|\|)\s*\$[A-Za-z_{(]", re.M)
        self.assertIsNone(position.search(re.sub(r"\[\[.*?\]\]", "", self.code)))
        for var in ("PY", "WEV"):
            self.assertEqual(len(re.findall(rf"\$\{{?{var}\b(?!\"|/|\}})", self.code)), 0, var)

    def test_is_strict_executable_and_under_400_lines(self) -> None:
        self.assertIn("set -euo pipefail", self.text)
        self.assertLess(len(self.text.splitlines()), 400)
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_every_message_key_has_both_languages_and_the_same_placeholders(self) -> None:
        body = self.text.split("msg() {")[1].split("\n  esac")[0]
        entries = re.findall(
            r"^    (\w+)\) (.*?) ;;$", re.sub(r'"\n\s+pt=', '" pt=', body), re.M | re.S
        )
        keys = [key for key, _ in entries]
        self.assertGreater(len(keys), 30)
        self.assertEqual(len(keys), len(set(keys)))
        for key, text in entries:
            en, pt = re.match(r'en="(.*?)" pt="(.*)"$', text, re.S).groups()  # type: ignore[union-attr]
            self.assertEqual(en.count("%s"), pt.count("%s"), key)
        used = set(re.findall(r"\b(?:say|ask_line|confirm|msg|die \d) \"?([a-z_]+)", self.text))
        used |= set(re.findall(r"\brow (st_\w+)", self.text))
        used |= set(re.findall(r"\brow st_\w+ \S+ (r_\w+)", self.text))
        self.assertLessEqual(used, set(keys))

    def test_licence_lines_match_the_license_file(self) -> None:
        first, _, url = (ROOT / "LICENSE").read_text().splitlines()[:3]
        self.assertIn(first.removeprefix("# "), self.text)
        self.assertIn(url.strip("<>"), self.text)


class FlagsTest(InstallCase):
    def test_help_prints_every_flag(self) -> None:
        done = self.run_script("--help")
        self.assertEqual(done.returncode, 0)
        for flag in FLAGS:
            self.assertIn(flag, done.stdout)

    def test_unknown_flag_and_bad_values_exit_2_with_usage(self) -> None:
        for args in (
            ["--bogus"],
            ["--lang", "fr"],
            ["--rea-mode", "x"],
            ["--harness", "vim"],
            ["--harness", ""],
        ):
            done = self.run_script(*args)
            self.assertEqual(done.returncode, 2, args)
            self.assertIn("Usage", done.stderr)

    def test_without_a_terminal_and_without_yes_it_refuses_and_names_yes(self) -> None:
        done = self.run_script("--source", str(ROOT), stdin="n\n" * 20)  # stdin is never an answer
        self.assertEqual(done.returncode, 2)
        self.assertIn("--yes", done.stderr)
        self.assertNotIn("fake claude", done.stdout)
        self.assertEqual(self.logged(), "")

    def test_questions_are_read_from_the_terminal_not_from_stdin(self) -> None:
        args = ["--source", str(ROOT), "--no-jev", "--harness", "codex", "--rea-mode", "direct"]
        replies = [(b"(default", b"en\n", False), (b"license? [y/N] ", b"y\n", False)]
        code, out = self.drive(args, replies, stdin="n\nn\nn\nn\n")
        self.assertFinished(code, out)
        self.assertIn("codex", out)
        self.assertIn("plugin add", self.logged())

    def test_declining_the_license_installs_nothing(self) -> None:
        args = ["--source", str(ROOT), "--lang", "en"]
        code, out = self.drive(args, [(b"license? [y/N] ", b"n\n", False)])
        self.assertEqual(code, 1, out)
        self.assertIn("Nothing was installed", out)
        self.assertEqual(self.logged(), "")


class InstallTest(InstallCase):
    def test_license_is_printed_before_the_first_install_call(self) -> None:
        done = self.install("--harness", "claude")
        self.assertInstalled(done)
        text = done.stdout
        self.assertIn("Noncommercial use only", text)
        self.assertLess(text.index("Noncommercial use only"), text.index("fake claude:"))
        self.assertEqual(text.count("Noncommercial use only"), 2)  # again in the summary

    def test_pt_br_messages_come_from_the_table(self) -> None:
        done = self.run_script("--yes", "--lang", "pt-BR", "--no-jev", "--source", str(ROOT))
        self.assertEqual(done.returncode, 1, done.stderr)  # the offline third-party failures
        self.assertIn("Somente uso não comercial", done.stdout)
        self.assertIn("Resumo", done.stdout)
        self.assertIn("Terminou com 3 falhas", done.stdout)

    def test_python_code_run_by_the_installer_ignores_the_working_directory(self) -> None:
        marker = self.dir / "marker"
        (self.dir / "work" / "json.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
        self.assertInstalled(self.install("--harness", "codex", "--rea-mode", "direct"))
        self.assertFalse(marker.exists())

    def test_a_wev_config_in_the_run_directory_has_no_effect(self) -> None:
        bogus = {"permissions": {"exec_path": ["/nonexistent"]}}
        (self.dir / "work" / "wev.config.json").write_text(json.dumps(bogus))
        self.seed_rea()
        self.assertInstalled(self.install("--harness", "codex", "--rea-mode", "isolated"))
        self.assertIn("docker build", self.logged())

    def test_an_old_python3_on_path_still_installs_and_the_summary_warns(self) -> None:
        tools = self.make_tools(python=False)
        (tools / "python3").write_text("#!/bin/sh\necho False\n")
        (tools / "python3").chmod(0o755)
        newer = Path(tempfile.mkdtemp(dir=self.dir))
        os.symlink(sys.executable, newer / "python3.14")
        done = self.install(
            "--harness", "codex", "--rea-mode", "direct", PATH=f"{FAKE_BIN}:{tools}:{newer}"
        )
        self.assertInstalled(done)
        self.assertIn("older than 3.14", done.stdout)

    def test_each_detected_harness_registers_through_its_own_route(self) -> None:
        done = self.install("--harness", "claude,codex,gemini,opencode")
        self.assertInstalled(done)
        log = self.logged()
        self.assertIn(f"claude plugin marketplace add {ROOT}", log)
        self.assertIn(f"claude plugin install {PLUGIN}", log)
        self.assertLess(log.index("marketplace add"), log.index("claude plugin install"))
        self.assertIn("codex plugin add", log)
        for target in ("codex", "gemini", "opencode"):
            manifest = self.dir / "data" / "wev-skills" / "harness" / target / "manifest.json"
            self.assertEqual(json.loads(manifest.read_text())["target"], target)
        self.assertIn("Installed from a local source, not self-updating.", done.stdout)
        self.assertIn("codex mcp add rea --", done.stdout)
        self.assertEqual(list((self.dir / "tmpdir").iterdir()), [])

    def test_a_harness_without_its_cli_is_skipped_with_the_reason(self) -> None:
        stripped = self.dir / "only_bin"
        stripped.mkdir()
        for name in ("claude", "docker", "git", "curl"):
            os.symlink(FAKE_BIN / name, stripped / name)
        tools = self.make_tools()
        done = self.run_script(
            "--yes", "--lang", "en", "--no-jev", "--source", str(ROOT), PATH=f"{stripped}:{tools}"
        )
        self.assertRegex(done.stdout, r"skipped\s+codex\s+CLI not found")
        self.assertRegex(done.stdout, r"done\s+claude")
        self.assertNotIn("codex ", self.logged())

    def test_rerun_with_the_same_flags_does_not_duplicate_registrations(self) -> None:
        args = ("--harness", "codex,opencode")
        self.assertInstalled(self.install(*args))
        root = self.dir / "data" / "wev-skills" / "harness"
        first = {t: (root / t / "manifest.json").read_bytes() for t in ("codex", "opencode")}
        self.assertInstalled(self.install(*args))
        second = {t: (root / t / "manifest.json").read_bytes() for t in ("codex", "opencode")}
        self.assertEqual(first, second)
        self.assertEqual(self.logged().count("codex plugin add"), 2)
        registrations = [tuple(r) for r in json.loads(first["codex"])["registrations"]]
        self.assertEqual(len(registrations), len(set(registrations)))

    def test_rea_mode_direct_writes_rea_json(self) -> None:
        done = self.install("--harness", "codex", "--rea-mode", "direct")
        self.assertInstalled(done)
        rea = json.loads((self.dir / "conf" / "wev-skills" / "rea.json").read_text())
        self.assertEqual(rea, {"mode": "direct"})
        self.assertNotIn("docker", self.logged())

    def test_isolated_mode_builds_the_image_when_rea_is_installed(self) -> None:
        self.seed_rea()
        done = self.install("--harness", "codex", "--rea-mode", "isolated")
        self.assertInstalled(done)
        self.assertIn("docker build", self.logged())
        self.assertRegex(done.stdout, r"done\s+rea-image")

    def test_isolated_mode_skips_the_image_when_rea_is_not_installed(self) -> None:
        done = self.install("--harness", "codex", "--rea-mode", "isolated")
        self.assertInstalled(done)
        self.assertRegex(done.stdout, r"skipped\s+rea-image\s+rea is not installed")
        self.assertNotIn("docker build", self.logged())

    def test_a_failing_wev_call_stops_with_its_error_and_removes_the_temp_dir(self) -> None:
        self.seed_rea()
        done = self.install(
            "--harness", "codex", "--rea-mode", "isolated", FAKE_FAIL="docker-build"
        )
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("rea_image_build_failed", done.stderr)
        self.assertIn("wev rea build-image", done.stderr)
        self.assertEqual(list((self.dir / "tmpdir").iterdir()), [])

    def test_failed_third_party_updates_are_reported_and_the_run_continues(self) -> None:
        done = self.install("--harness", "codex", "--rea-mode", "direct")
        self.assertInstalled(done)
        self.assertRegex(done.stdout, r"failed\s+agent-skills\s+see the output above")
        self.assertRegex(done.stdout, r"done\s+codex")


class DownloadRouteTest(InstallCase):
    def test_clones_the_pinned_release_tag_then_updates_through_the_cli(self) -> None:
        done = self.run_script("--yes", "--lang", "en", "--no-jev", FAKE_TAG="v9.9.9")
        log = self.logged()
        self.assertIn("api.github.com/repos/wevertonjuscelino/wev-skills/releases/latest", log)
        clone = "git clone --quiet --depth 1 --branch v9.9.9 "
        self.assertIn(clone + "https://github.com/wevertonjuscelino/wev-skills.git", log)
        self.assertNotEqual(done.returncode, 0)  # the offline `skills update wev-skills` fails
        self.assertIn("skills update wev-skills", done.stderr)
        self.assertEqual(list((self.dir / "tmpdir").iterdir()), [])

    def test_an_odd_release_tag_is_refused_before_any_clone(self) -> None:
        done = self.run_script("--yes", "--lang", "en", "--no-jev", FAKE_TAG="v1.0.0; rm -rf x")
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("git clone", self.logged())


class SystemChecksTest(InstallCase):
    def test_missing_python_with_yes_names_the_installer_and_does_not_run_it(self) -> None:
        tools = self.make_tools(python=False, extra=("brew",))
        done = self.run_script(
            "--yes", "--lang", "en", "--source", str(ROOT), PATH=f"{FAKE_BIN}:{tools}"
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("brew install python", done.stderr)
        self.assertEqual(self.logged(), "")

    def test_missing_node_with_yes_names_the_installer(self) -> None:
        tools = self.dir / "nonode"
        tools.mkdir()
        for name in ("bash", "brew", *COREUTILS):
            os.symlink(shutil.which(name) or "/bin/" + name, tools / name)
        os.symlink(sys.executable, tools / "python3")
        done = self.run_script(
            "--yes", "--lang", "en", "--source", str(ROOT), PATH=f"{FAKE_BIN}:{tools}"
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("brew install node", done.stderr)


class JevTest(InstallCase):
    def typed(self, *extra: str, **env: str) -> tuple[int, str]:
        args = ["--yes", "--lang", "en", "--jev", "--source", str(ROOT), "--harness", "codex"]
        replies = [(b"hidden): ", KEY.encode() + b"\n", True)]
        return self.drive([*args, *extra], replies, **env)

    def test_key_typed_on_the_terminal_lands_only_in_the_0600_key_file(self) -> None:
        code, out = self.typed(JEV_API_URL=f"{DEAD}/v1/systemone")
        self.assertFinished(code, out)
        key_file = self.dir / "conf" / "wev-skills" / ".env"
        self.assertIn(KEY, key_file.read_text())
        self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(key_file.parent.stat().st_mode), 0o700)
        self.assertNotIn(KEY, out)
        self.assertNotIn(KEY, self.logged())
        self.assertEqual(self.files_containing(KEY), [key_file])

    def test_probe_failure_turns_jev_off_and_the_summary_says_so(self) -> None:
        code, out = self.typed(JEV_API_URL=f"{DEAD}/v1/systemone")
        self.assertFinished(code, out)
        self.assertNotIn("decision", self.user_config())
        self.assertEqual(self.user_config()["language"], "en")
        self.assertRegex(out, r"skipped\s+JEV\s+JEV is off, the probe failed")

    def test_probe_success_sets_jev_as_provider_and_validates_the_config(self) -> None:
        with fake_jev([(200, ANSWERS, 0)]) as jev:
            code, out = self.typed(JEV_API_URL=jev.url)
            self.assertEqual(len(jev.requests), 1)
        self.assertFinished(code, out)
        self.assertEqual(self.user_config()["decision"], {"provider": "jev"})
        self.assertRegex(out, r"done\s+JEV")
        self.assertNotIn(KEY, out)

    def test_a_rejected_typed_key_turns_jev_off_even_with_a_working_exported_key(self) -> None:
        with fake_jev([(401, b"{}", 0)]) as jev:
            code, out = self.typed(JEV_API_URL=jev.url, TYPESAFE_API_KEY="exported-" + KEY)
        self.assertFinished(code, out)
        self.assertNotIn("decision", self.user_config())
        self.assertRegex(out, r"skipped\s+JEV\s+JEV is off, the probe failed")
        self.assertIn("will win over the stored key", out)

    def test_interrupting_the_key_prompt_restores_echo_and_exits_130(self) -> None:
        args = ["--yes", "--lang", "en", "--jev", "--source", str(ROOT), "--harness", "codex"]
        code, out = self.drive(args, [(b"hidden): ", b"\x03", True)])
        self.assertEqual(code, 130, out)
        self.assertTrue(self.echo_after)
        self.assertFalse((self.dir / "conf" / "wev-skills" / ".env").exists())

    def test_no_jev_turns_off_a_previous_jev_setting_and_keeps_other_keys(self) -> None:
        conf = self.dir / "conf" / "wev-skills"
        other = {"approval_ttl_seconds": 60.0}
        before = {"language": "pt-BR", "decision": {"provider": "jev"}, "permissions": other}
        (conf / "wev.config.json").write_text(json.dumps(before))
        done = self.install("--harness", "codex", "--rea-mode", "direct")
        self.assertInstalled(done)
        self.assertEqual(self.user_config(), {"language": "en", "permissions": other})

    def test_jev_without_a_terminal_refuses_instead_of_guessing_a_key(self) -> None:
        done = self.run_script(
            "--yes", "--lang", "en", "--jev", "--source", str(ROOT), stdin=KEY + "\n"
        )
        self.assertEqual(done.returncode, 2)
        self.assertNotIn(KEY, done.stdout + done.stderr)
        self.assertFalse((self.dir / "conf" / "wev-skills" / ".env").exists())


class UninstallTest(InstallCase):
    def setUp(self) -> None:
        super().setUp()
        self.assertInstalled(self.install("--harness", "claude,codex,opencode"))
        self.data = self.dir / "data" / "wev-skills"
        self.conf = self.dir / "conf" / "wev-skills"

    def uninstall(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_script("--uninstall", "--yes", "--lang", "en", "--source", str(ROOT), *args)

    def test_uninstall_removes_the_data_dir_and_keeps_the_config_dir(self) -> None:
        self.assertTrue(self.data.exists())
        done = self.uninstall()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.data.exists())
        self.assertTrue(self.conf.exists())
        self.assertIn(f"Kept: {self.conf}", done.stdout)
        log = self.logged()
        self.assertIn("claude plugin uninstall wev-skills", log)
        self.assertIn("claude plugin marketplace remove wev-skills-marketplace", log)
        self.assertIn("codex plugin remove", log)

    def test_uninstall_with_purge_removes_the_config_dir_too(self) -> None:
        done = self.uninstall("--purge")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.conf.exists())

    def test_a_failing_undo_step_keeps_the_data_dir_and_exits_1(self) -> None:
        done = self.run_script(
            "--uninstall", "--yes", "--lang", "en", "--source", str(ROOT), FAKE_FAIL="codex"
        )
        self.assertEqual(done.returncode, 1, done.stdout)
        manifest = self.data / "harness" / "codex" / "manifest.json"
        self.assertTrue(manifest.exists())
        self.assertIn("was kept", done.stderr)

    def test_uninstall_without_wev_to_undo_registrations_keeps_the_data_dir(self) -> None:
        done = self.run_script("--uninstall", "--yes", "--lang", "en")  # no `current` link
        self.assertEqual(done.returncode, 1)
        self.assertTrue(self.data.exists())


if __name__ == "__main__":
    unittest.main()
