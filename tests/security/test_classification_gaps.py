"""Regression tests for the classification gaps an independent review found."""

from __future__ import annotations

import shlex
import unittest

from wev_skills.security import commands
from wev_skills.security.readonly import is_read_only


def risk(line: str) -> commands.CommandRisk:
    return commands.classify(tuple(shlex.split(line)))


class GitAbbreviationTests(unittest.TestCase):
    def test_unique_prefixes_of_long_options_are_recognized(self) -> None:
        for line in (
            "git reset --har",
            "git reset --ha HEAD~1",
            "git clean --forc -d",
            "git clean --fo",
            "git checkout --forc main",
            "git branch --delete --forc topic",
            "git branch --del --for topic",
            "git restore --work file",
            "git switch --discard-changes main",
            "git switch --disc main",
        ):
            with self.subTest(line=line):
                self.assertTrue(risk(line).destructive)

    def test_push_abbreviations_are_force_pushes(self) -> None:
        for line in (
            "git push --forc",
            "git push --force-with-l origin",
            "git push --del origin topic",
            "git push --mirr",
            "git push --pru",
        ):
            with self.subTest(line=line):
                found = risk(line)
                self.assertTrue(found.destructive and found.external_effect)

    def test_plain_forms_stay_unflagged(self) -> None:
        plain = ("git status", "git reset HEAD~1", "git log --oneline", "git restore --staged f")
        for line in plain:
            with self.subTest(line=line):
                self.assertFalse(risk(line).needs_approval)


class GitConfigExecutionTests(unittest.TestCase):
    def test_config_driven_execution_is_unanalyzable(self) -> None:
        for line in (
            "git -c alias.x='!rm -rf src' x",
            "git -c core.fsmonitor='rm -rf src' status",
            "git -c core.pager=/tmp/p log",
            "git -c core.sshCommand=/tmp/s fetch",
            "git -c core.editor=/tmp/e commit",
            "git -c diff.external=/tmp/d diff",
            "git -c clean.requireForce=false clean -d",
            "git --exec-path=/tmp/evil status",
            "git --config-env=core.pager=X log",
            "git -calias.x=!id x",
        ):
            with self.subTest(line=line):
                self.assertTrue(risk(line).unanalyzable)

    def test_git_subcommands_that_run_programs_are_unanalyzable(self) -> None:
        for line in (
            "git rebase --exec 'rm -rf src' HEAD~1",
            "git rebase -x 'make' HEAD~1",
            "git submodule foreach 'rm -rf .'",
            "git bisect run ./t.sh",
            "git filter-branch --tree-filter 'rm x' HEAD",
            "git frobnicate",
        ):
            with self.subTest(line=line):
                self.assertTrue(risk(line).unanalyzable)

    def test_checkout_of_paths_from_a_revision_discards_work(self) -> None:
        self.assertTrue(risk("git checkout HEAD~5 src").destructive)

    def test_a_config_option_never_makes_a_command_read_only(self) -> None:
        for line in ("git -c core.pager=/tmp/p log", "git --exec-path=/tmp/e status"):
            with self.subTest(line=line):
                self.assertFalse(is_read_only(tuple(shlex.split(line))))


class WrapperTests(unittest.TestCase):
    def test_wrappers_are_unwrapped(self) -> None:
        for wrapper in (
            "script -q /dev/null",
            "nohup",
            "setsid",
            "timeout 5",
            "gtimeout 5",
            "nice -n 5",
            "time",
            "stdbuf -oL",
            "ionice -c 3",
            "caffeinate -i",
            "arch -arm64",
            "expect -c",
        ):
            with self.subTest(wrapper=wrapper):
                self.assertTrue(risk(f"{wrapper} rm -rf src").destructive)

    def test_programs_that_run_text_are_unanalyzable(self) -> None:
        for line in (
            "eval rm -rf src",
            "source ./x.sh",
            ". ./x.sh",
            "exec ls",
            "command ls",
            "builtin cd",
            "script -q /dev/null ls",
            "expect x.exp",
            "xargs rm",
            "env -S 'rm -rf src'",
            "env --split-string 'ls' ",
            "find . -exec rm {} ;",
            "find . -execdir rm {} ;",
            "find . -ok rm {} ;",
        ):
            with self.subTest(line=line):
                self.assertTrue(risk(line).unanalyzable)

    def test_env_that_sets_variables_is_unanalyzable(self) -> None:
        for line in ("env GIT_EXTERNAL_DIFF=/tmp/x git diff", "env -i ls", "env -u HOME ls"):
            with self.subTest(line=line):
                self.assertTrue(risk(line).unanalyzable)


class EmbeddedShellTests(unittest.TestCase):
    def test_one_argument_holding_shell_operators_is_flagged(self) -> None:
        for argv in (
            ("tmux", "send-keys", "ls | head"),
            ("docker", "exec", "c", "ls; rm -rf /"),
            ("mytool", "a && b"),
            ("ssh", "host", "ls | head"),
        ):
            with self.subTest(argv=argv):
                self.assertTrue(commands.classify(argv).unanalyzable)

    def test_text_tools_keep_their_patterns(self) -> None:
        for argv in (
            ("grep", "a | b", "f"),
            ("jq", ".a | .b", "f.json"),
            ("git", "commit", "-m", "fix a; b"),
            ("echo", "a > b"),
            ("sed", "-n", "s/a/b/; p", "f"),
        ):
            with self.subTest(argv=argv):
                self.assertFalse(commands.classify(argv).unanalyzable)


class PsTests(unittest.TestCase):
    def test_only_fixed_safe_forms_are_read_only(self) -> None:
        for line in ("ps", "ps aux", "ps -A", "ps -Af", "ps ax", "ps -p 1", "ps -o pid,comm -p 1"):
            with self.subTest(line=line):
                self.assertTrue(is_read_only(tuple(shlex.split(line))))

    def test_forms_that_can_print_environments_are_not(self) -> None:
        for line in (
            "ps -eww",
            "ps -e",
            "ps -ef",
            "ps -E",
            "ps e",
            "ps eww",
            "ps auxe",
            "ps -o pid,environ",
            "ps --forest e",
            "ps -Aeww",
            "ps -wwE",
            "ps axe -o command",
        ):
            with self.subTest(line=line):
                self.assertFalse(is_read_only(tuple(shlex.split(line))))


class SmallGapTests(unittest.TestCase):
    def test_scheduling_privileged_containers_and_awk_system(self) -> None:
        self.assertTrue(risk("crontab x").external_effect)
        self.assertTrue(risk("docker run --privileged -v /:/h alpine sh").privileged)
        self.assertTrue(commands.classify(("awk", 'BEGIN{system("rm -rf src")}')).unanalyzable)
        self.assertFalse(commands.classify(("awk", "{print $1}", "f")).unanalyzable)

    def test_a_process_environment_file_is_not_read_only(self) -> None:
        self.assertFalse(is_read_only(("cat", "/proc/self/environ")))
        self.assertFalse(is_read_only(("head", "/proc/1/environ")))
        self.assertTrue(is_read_only(("cat", "/proc/cpuinfo")))


if __name__ == "__main__":
    unittest.main()
