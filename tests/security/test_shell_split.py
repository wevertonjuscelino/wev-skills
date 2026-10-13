"""Splitting a shell command line into simple commands, or refusing when that is unsafe."""

from __future__ import annotations

import unittest

from wev_skills.security.shell import SimpleCommand, split_commands


def argvs(command: str) -> list[tuple[str, ...]] | None:
    parts = split_commands(command)
    return None if parts is None else [part.argv for part in parts]


class SplitTests(unittest.TestCase):
    def test_a_simple_command_is_one_argv(self) -> None:
        self.assertEqual(argvs("git status"), [("git", "status")])
        self.assertEqual(argvs("  ls   -la  "), [("ls", "-la")])
        self.assertEqual(argvs(""), [])
        self.assertEqual(argvs("   \n "), [])

    def test_control_operators_separate_commands(self) -> None:
        self.assertEqual(argvs("a && b || c ; d | e |& f & g\nh"), [(c,) for c in "abcdefgh"])
        self.assertEqual(argvs("cd src&&make test"), [("cd", "src"), ("make", "test")])
        self.assertEqual(argvs("ls;"), [("ls",)])

    def test_quotes_protect_operators_and_spaces(self) -> None:
        self.assertEqual(argvs("echo 'a && b' \"c | d\""), [("echo", "a && b", "c | d")])
        self.assertEqual(argvs("git commit -m 'fix; done'"), [("git", "commit", "-m", "fix; done")])
        self.assertEqual(argvs('echo "it\'s" \'say "hi"\''), [("echo", "it's", 'say "hi"')])
        self.assertEqual(argvs(r"echo a\ b \; c"), [("echo", "a b", ";", "c")])
        self.assertEqual(argvs('echo "a\\"b" ""'), [("echo", 'a"b', "")])
        self.assertEqual(argvs("echo one \\\n two"), [("echo", "one", "two")])

    def test_redirections_are_taken_out_of_the_argv_and_their_files_are_kept(self) -> None:
        cases = {
            "echo hi > out.txt": SimpleCommand(("echo", "hi"), ("out.txt",)),
            "echo hi >> 'my out.txt'": SimpleCommand(("echo", "hi"), ("my out.txt",)),
            "sort < in.txt > out.txt": SimpleCommand(("sort",), ("in.txt", "out.txt")),
            "make test 2>&1": SimpleCommand(("make", "test"), ()),
            "make test 2> err.log": SimpleCommand(("make", "test"), ("err.log",)),
            "make test &> all.log": SimpleCommand(("make", "test"), ("all.log",)),
            "make test >/dev/null 2>&1": SimpleCommand(("make", "test"), ("/dev/null",)),
            "cat x >| out": SimpleCommand(("cat", "x"), ("out",)),
            "cmd >&2": SimpleCommand(("cmd",), ()),
            "cmd >& both.log": SimpleCommand(("cmd",), ("both.log",)),
            "cmd 2>&-": SimpleCommand(("cmd",), ()),
            "echo 2 > two": SimpleCommand(("echo", "2"), ("two",)),
            "> empty.txt": SimpleCommand((), ("empty.txt",)),
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(split_commands(command), (expected,))

    def test_a_pipeline_with_redirection_keeps_each_part(self) -> None:
        parts = split_commands("grep -r TODO src | sort > todo.txt && wc -l todo.txt")
        self.assertEqual(
            parts,
            (
                SimpleCommand(("grep", "-r", "TODO", "src"), ()),
                SimpleCommand(("sort",), ("todo.txt",)),
                SimpleCommand(("wc", "-l", "todo.txt"), ()),
            ),
        )

    def test_leading_assignments_are_kept_out_of_the_argv(self) -> None:
        self.assertEqual(argvs("FOO=bar BAZ='q x' make test"), [("make", "test")])
        self.assertEqual(argvs("FOO=bar"), [()])
        self.assertEqual(argvs("make FOO=bar"), [("make", "FOO=bar")])

    def test_comments_are_ignored(self) -> None:
        self.assertEqual(argvs("ls # rm -rf /"), [("ls",)])
        self.assertEqual(argvs("# only a comment\nls"), [("ls",)])
        self.assertEqual(argvs("echo a#b '#c'"), [("echo", "a#b", "#c")])

    def test_variables_in_arguments_stay_literal(self) -> None:
        self.assertEqual(argvs('rm -rf "$DIR"/build'), [("rm", "-rf", "$DIR/build")])
        self.assertEqual(argvs("echo ${HOME}"), [("echo", "${HOME}")])

    def test_what_cannot_be_split_safely_is_refused(self) -> None:
        for command in (
            "echo 'unbalanced",
            'echo "unbalanced',
            "echo trailing\\",
            "echo $(whoami)",
            'echo "$(whoami)"',
            "echo `whoami`",
            'echo "`whoami`"',
            "cat <<EOF\nhello\nEOF",
            "cat <<< 'here string'",
            "diff <(ls a) <(ls b)",
            "tee >(cat)",
            "(cd src && make)",
            "{ ls; pwd; }",
            "if true; then rm -rf x; fi",
            "for f in *; do rm $f; done",
            "while true; do date; done",
            "case x in x) ls;; esac",
            "! ls",
            "function f { ls; }",
            "f() { ls; }",
            "[[ -f x ]] && rm x",
            "echo hi >",
            "echo hi > $OUT",
            "echo a\x00b",
            "ls ${x:-$(rm -rf /)}",
        ):
            with self.subTest(command=command):
                self.assertIsNone(split_commands(command))

    def test_a_command_word_from_a_variable_is_marked_dynamic(self) -> None:
        for command in (
            "$CMD --flag",
            '"$CMD" --flag',
            '"${ROOT}/bin/tool" run',
            "ls && $EDITOR x",
        ):
            with self.subTest(command=command):
                parts = split_commands(command)
                self.assertIsNotNone(parts)
                self.assertTrue(parts[-1].dynamic)
        self.assertEqual(
            split_commands('"${ROOT}/bin/tool" run')[0].argv, ("${ROOT}/bin/tool", "run")
        )
        self.assertFalse(split_commands("echo $HOME")[0].dynamic)
        self.assertFalse(split_commands("'$CMD' x")[0].dynamic)

    def test_single_quotes_make_substitution_syntax_literal(self) -> None:
        self.assertEqual(argvs("echo '$(whoami) `id`'"), [("echo", "$(whoami) `id`")])
        self.assertEqual(argvs("grep -n 'a(b)' file"), [("grep", "-n", "a(b)", "file")])

    def test_find_exec_braces_and_escaped_semicolon(self) -> None:
        self.assertEqual(
            argvs(r"find . -name '*.py' -exec wc -l {} \;"),
            [("find", ".", "-name", "*.py", "-exec", "wc", "-l", "{}", ";")],
        )


class AssignmentAndExpansionTests(unittest.TestCase):
    def test_leading_assignments_are_reported_not_dropped(self) -> None:
        (part,) = split_commands("GIT_EXTERNAL_DIFF=/tmp/x.sh FOO='a b' git diff")  # type: ignore[misc]
        self.assertEqual(part.argv, ("git", "diff"))
        self.assertEqual(part.assignments, ("GIT_EXTERNAL_DIFF", "FOO"))

    def test_an_assignment_alone_is_a_part_of_its_own(self) -> None:
        parts = split_commands("F=-rf; rm $F src")
        assert parts is not None
        found = [(p.argv, p.assignments) for p in parts]
        self.assertEqual(found, [((), ("F",)), (("rm", "$F", "src"), ())])
        self.assertTrue(parts[1].unresolved)

    def test_words_the_reader_cannot_resolve_are_marked(self) -> None:
        for line in (
            "rm $F src",
            'rm "$F" src',
            "rm ${F} src",
            "rm $'-rf' src",
            'rm $"-rf" src',
            "cat .e*",
            "cat .en?",
            "cat .[e]nv",
            "git reset {--hard,HEAD}",
            "ls file{1..3}",
            "cat ~root/.profile",
            "cat ~+/x",
        ):
            with self.subTest(line=line):
                (part,) = split_commands(line)  # type: ignore[misc]
                self.assertTrue(part.unresolved)

    def test_literal_words_are_not_marked(self) -> None:
        for line in (
            "ls -la src",
            "echo '$HOME' 'a*' \"b?\" '{x,y}'",
            "echo a\\*",
            "cat ~/notes.txt",
            "ls ~",
            "git log --format=%H",
            "echo a=b",
        ):
            with self.subTest(line=line):
                (part,) = split_commands(line)  # type: ignore[misc]
                self.assertFalse(part.unresolved)


if __name__ == "__main__":
    unittest.main()
