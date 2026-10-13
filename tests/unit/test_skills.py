"""Checks for the Claude Code skills and the plugin packaging.

Standard library only. The skills are Markdown that tells a model which CLI commands to run, so
the main risk is drift: a command, subcommand or flag that no longer exists. These tests extract
every ``wev`` command line shown in the skill files and check it against the real CLI help.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEV = ROOT / "bin" / "wev"
SKILLS_DIR = ROOT / "skills"
AGENTS_DIR = ROOT / "agents"
PLUGIN_DIR = ROOT / ".claude-plugin"
EXAMPLES_DIR = ROOT / "examples"
EXPECTED_SKILLS = (
    "wev-agent-builder",
    "wev-claude-md",
    "wev-harness-evaluation",
    "wev-orchestrate",
    "wev-readme",
    "wev-remote-ops",
)

ALLOWED_KEYS = frozenset(
    {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
        "argument-hint",
        "disable-model-invocation",
        "user-invocable",
    }
)
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REPOSITORY_URL = "https://github.com/wevertonjuscelino/wev-skills"
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY_LINES = 500
RESERVED_PREFIXES = ("anthropic-", "claude-")
RESERVED_NAMES = frozenset({"claude-plugins-official"})
GLOBAL_OPTIONS = ("--lang", "--config")
CLI_START = re.compile(r'(?:"\$\{CLAUDE_PLUGIN_ROOT\}/bin/wev"|(?<![\w./-])wev)(?=\s)')
INLINE_CODE = re.compile(r"`([^`\n]+)`")
LINK = re.compile(r"\]\(([^)\s]+)\)")
SHELL_BREAKS = re.compile(r"\s(?:\||>|>>|&&|;)\s")
TIMEOUT_SECONDS = 60


class FrontmatterError(ValueError):
    pass


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """The frontmatter lines and the body of a Markdown file."""
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise FrontmatterError("file must start with a line containing only ---")
    for index in range(1, len(lines)):
        if lines[index] == "---":
            return lines[1:index], "\n".join(lines[index + 1 :])
    raise FrontmatterError("frontmatter is not closed by a line containing only ---")


def parse_scalar(raw: str, key: str) -> str:
    """A double-quoted JSON-style string, or a plain scalar that YAML would also read as text."""
    value = raw.strip()
    if not value:
        raise FrontmatterError(f"{key}: empty value")
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(f"{key}: bad double-quoted string: {exc}") from exc
        if not isinstance(parsed, str):
            raise FrontmatterError(f"{key}: expected a string")
        return parsed
    if value[0] in "'[{&*!|>%@`#" or ": " in value or " #" in value or value.endswith(":"):
        raise FrontmatterError(f"{key}: plain value is ambiguous YAML, quote it with double quotes")
    return value


def parse_frontmatter(lines: list[str]) -> dict[str, str]:
    """Strict reader for flat ``key: value`` frontmatter; nesting and duplicates are errors."""
    result: dict[str, str] = {}
    for number, line in enumerate(lines, start=2):
        if not line.strip():
            continue
        if line != line.lstrip():
            raise FrontmatterError(f"line {number}: indentation is not supported here")
        key, sep, raw = line.partition(":")
        if not sep or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", key):
            raise FrontmatterError(f"line {number}: expected 'key: value'")
        if key in result:
            raise FrontmatterError(f"line {number}: duplicate key {key}")
        result[key] = parse_scalar(raw, key)
    return result


def lenient_top_level(lines: list[str]) -> dict[str, str]:
    """Top-level keys only, for generated agent files whose frontmatter may hold lists."""
    result: dict[str, str] = {}
    for line in lines:
        if line and line == line.lstrip() and ":" in line:
            key, _, raw = line.partition(":")
            result[key] = raw.strip().strip('"')
    return result


@cache
def run_wev(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WEV), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=TIMEOUT_SECONDS,
        check=False,
        cwd=ROOT,
    )


def skill_files() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.rglob("*.md") if p.is_file())


def code_snippets(text: str) -> list[str]:
    """Lines of fenced code blocks plus inline code spans, with ``\\`` continuations joined."""
    snippets: list[str] = []
    in_fence = False
    pending = ""
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            pending = ""
            continue
        if in_fence:
            joined = pending + line.strip()
            if joined.endswith("\\"):
                pending = joined[:-1] + " "
                continue
            pending = ""
            snippets.append(joined)
        else:
            snippets.extend(INLINE_CODE.findall(line))
    return snippets


def cli_invocations(snippet: str) -> list[list[str]]:
    """Token lists that follow each ``wev`` program name in a code snippet."""
    found: list[list[str]] = []
    for match in CLI_START.finditer(snippet):
        rest = SHELL_BREAKS.split(snippet[match.end() :])[0]
        try:
            found.append(shlex.split(rest))
        except ValueError as exc:
            raise AssertionError(f"cannot tokenize {snippet!r}: {exc}") from exc
    return found


def command_path(tokens: list[str]) -> tuple[list[str], list[str]]:
    """``(command path, remaining tokens)`` after skipping global options."""
    index = 0
    while index < len(tokens) and tokens[index] in GLOBAL_OPTIONS:
        index += 2
    rest = tokens[index:]
    if not rest:
        raise AssertionError("no command after wev")
    group = rest[0]
    help_text = run_wev(group, "--help")
    if help_text.returncode != 0:
        raise AssertionError(f"'wev {group}' is not a command")
    if "<command>" in help_text.stdout:
        if len(rest) < 2:
            raise AssertionError(f"'wev {group}' needs a subcommand")
        return [group, rest[1]], rest[2:]
    return [group], rest[1:]


def flags_before_separator(tokens: list[str]) -> list[str]:
    flags: list[str] = []
    for token in tokens:
        if token == "--":
            break
        if token.startswith("--"):
            flags.append(token.split("=", 1)[0])
    return flags


class SkillStructureTests(unittest.TestCase):
    def test_expected_skills_exist(self) -> None:
        found = sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())
        self.assertEqual(found, sorted(EXPECTED_SKILLS))

    def test_frontmatter_is_valid_for_every_skill(self) -> None:
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
                lines, _ = split_frontmatter(text)
                meta = parse_frontmatter(lines)
                self.assertLessEqual(set(meta), ALLOWED_KEYS)
                self.assertEqual(meta.get("name"), name)
                self.assertRegex(name, NAME_PATTERN)
                self.assertLessEqual(len(name), MAX_NAME)
                description = meta.get("description", "")
                self.assertTrue(1 <= len(description) <= MAX_DESCRIPTION, len(description))
                self.assertIn("Use when", description)
                self.assertIn("português", description)

    def test_body_is_shorter_than_the_limit(self) -> None:
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertLess(len(text.split("\n")), MAX_BODY_LINES)

    def test_every_skill_tells_the_model_how_to_handle_portuguese(self) -> None:
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("--lang pt-BR", text)

    def test_relative_links_resolve_and_references_are_one_level_deep(self) -> None:
        for path in skill_files():
            text = path.read_text(encoding="utf-8")
            for target in LINK.findall(text):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), link=target):
                    resolved = (path.parent / target.split("#", 1)[0]).resolve()
                    self.assertTrue(resolved.is_file(), f"missing {resolved}")
                    if path.name != "SKILL.md":
                        self.fail("reference files must not link to other files")

    def test_every_reference_file_is_linked_from_its_skill(self) -> None:
        for name in EXPECTED_SKILLS:
            skill_dir = SKILLS_DIR / name
            body = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            for reference in sorted((skill_dir / "references").glob("*")):
                with self.subTest(reference=str(reference.relative_to(ROOT))):
                    self.assertIn(f"references/{reference.name}", body)

    def test_no_empty_directories(self) -> None:
        for base in (SKILLS_DIR, EXAMPLES_DIR, PLUGIN_DIR):
            for directory in [base, *(p for p in base.rglob("*") if p.is_dir())]:
                with self.subTest(directory=str(directory.relative_to(ROOT))):
                    self.assertTrue(any(directory.iterdir()), "directory is empty")


class SkillCommandTests(unittest.TestCase):
    def test_every_command_shown_in_a_skill_exists_with_its_flags(self) -> None:
        checked = 0
        for path in skill_files():
            for snippet in code_snippets(path.read_text(encoding="utf-8")):
                for tokens in cli_invocations(snippet):
                    with self.subTest(file=path.name, snippet=snippet):
                        route, rest = command_path(tokens)
                        help_run = run_wev(*route, "--help")
                        self.assertEqual(help_run.returncode, 0, f"wev {' '.join(route)}")
                        for flag in flags_before_separator(rest):
                            pattern = rf"(?<![\w-]){re.escape(flag)}(?![\w-])"
                            self.assertRegex(
                                help_run.stdout, pattern, f"{flag} not in 'wev {' '.join(route)}'"
                            )
                        checked += 1
        self.assertGreater(checked, 40)

    def test_global_options_exist(self) -> None:
        top = run_wev("--help").stdout
        for option in GLOBAL_OPTIONS:
            self.assertIn(option, top)

    def test_no_fenced_command_grants_an_approval_or_claims_to_be_human(self) -> None:
        for path in skill_files():
            in_fence = False
            for line in path.read_text(encoding="utf-8").split("\n"):
                if line.strip().startswith("```"):
                    in_fence = not in_fence
                elif in_fence:
                    with self.subTest(file=path.name, line=line):
                        self.assertNotIn("approval grant", line)
                        self.assertNotIn("--i-am-human", line)

    def test_no_skill_names_the_human_confirmation_flag_anywhere(self) -> None:
        for path in skill_files():
            with self.subTest(file=path.name):
                self.assertNotIn("--i-am-human", path.read_text(encoding="utf-8"))

    def test_orchestrate_skill_explains_the_hooks_and_how_to_quiet_them(self) -> None:
        text = (SKILLS_DIR / "wev-orchestrate" / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "## Hooks",
            "run finish",
            "run brief",
            "fail open",
            "never approves anything by itself",
            "not permission-checked by the engine",
            "harness.plan_reminder",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


class ManifestTests(unittest.TestCase):
    @staticmethod
    def load(name: str) -> dict:
        return json.loads((PLUGIN_DIR / name).read_text(encoding="utf-8"))

    @staticmethod
    def project_version() -> str:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert match is not None, "version not found in pyproject.toml"
        return match.group(1)

    def test_plugin_manifest_has_the_required_fields(self) -> None:
        plugin = self.load("plugin.json")
        self.assertRegex(plugin["name"], NAME_PATTERN)
        self.assertEqual(plugin["version"], self.project_version())
        self.assertEqual(plugin["license"], "MIT")
        self.assertTrue(plugin["description"].strip())
        self.assertTrue(plugin["author"]["name"].strip())
        self.assertTrue(plugin["keywords"])
        self.assertEqual(plugin["homepage"], REPOSITORY_URL)
        self.assertEqual(plugin["repository"], REPOSITORY_URL)

    def test_marketplace_manifest_points_at_this_plugin(self) -> None:
        plugin = self.load("plugin.json")
        market = self.load("marketplace.json")
        name = market["name"]
        self.assertRegex(name, NAME_PATTERN)
        self.assertFalse(name.startswith(RESERVED_PREFIXES), name)
        self.assertNotIn(name, RESERVED_NAMES)
        self.assertTrue(market["owner"]["name"].strip())
        self.assertEqual(len(market["plugins"]), 1)
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], plugin["name"])
        self.assertEqual(entry["source"], "./")

    def test_plugin_directories_sit_at_the_plugin_root(self) -> None:
        self.assertEqual(
            sorted(p.name for p in PLUGIN_DIR.iterdir()), ["marketplace.json", "plugin.json"]
        )
        self.assertTrue((ROOT / "bin" / "wev").is_file())
        self.assertTrue((ROOT / "hooks" / "hooks.json").is_file())

    def test_exported_agents_have_name_and_description(self) -> None:
        files = sorted(AGENTS_DIR.glob("*.md"))
        self.assertTrue(files)
        for path in files:
            with self.subTest(agent=path.name):
                lines, _ = split_frontmatter(path.read_text(encoding="utf-8"))
                meta = lenient_top_level(lines)
                self.assertEqual(meta.get("name"), path.stem)
                self.assertTrue(meta.get("description"))


@unittest.skipUnless(shutil.which("git"), "needs git")
class ExampleFileTests(unittest.TestCase):
    def test_example_config_validates(self) -> None:
        result = run_wev("config", "validate", str(EXAMPLES_DIR / "config.example.json"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_example_plan_is_accepted_by_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=work, check=True, timeout=TIMEOUT_SECONDS)
            (work / "Makefile").write_text("test:\n\t@echo ok\n", encoding="utf-8")

            def wev(*args: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, str(WEV), "--config", str(work / "wev.json"), *args],
                    cwd=work,
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    timeout=TIMEOUT_SECONDS,
                    check=False,
                )

            (work / "wev.json").write_text(
                json.dumps({"state_dir": str(work / "state")}), encoding="utf-8"
            )
            started = wev(
                "run", "start", "--objective", "Example", "--files", "8", "--mode", "plan"
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            planned = wev("plan", "set", "--file", str(EXAMPLES_DIR / "plan.example.json"))
            self.assertEqual(planned.returncode, 0, planned.stderr)
            self.assertEqual(len(json.loads(planned.stdout)["tasks"]), 2)


class FrontmatterReaderTests(unittest.TestCase):
    def test_reader_accepts_quoted_values_and_rejects_ambiguous_ones(self) -> None:
        self.assertEqual(
            parse_frontmatter(['name: "a"', 'description: "x: y"']),
            {"name": "a", "description": "x: y"},
        )
        for bad in (
            ["description: x: y"],
            ["name: a", "name: b"],
            ["  nested: 1"],
            ["key: [a]"],
            ["noseparator"],
        ):
            with self.subTest(bad=bad), self.assertRaises(FrontmatterError):
                parse_frontmatter(bad)

    def test_command_extraction_skips_global_options_and_stops_at_separator(self) -> None:
        tokens = cli_invocations(
            '"${CLAUDE_PLUGIN_ROOT}/bin/wev" --lang pt-BR exec --timeout 5 -- ls --nope'
        )[0]
        route, rest = command_path(tokens)
        self.assertEqual(route, ["exec"])
        self.assertEqual(flags_before_separator(rest), ["--timeout"])


if __name__ == "__main__":
    unittest.main()
