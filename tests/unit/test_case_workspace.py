import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills.config import Config
from wev_skills.core import wiring
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import NotFound, PermissionDenied, ValidationError
from wev_skills.core.ports import SubprocessRunner
from wev_skills.evaluation.cases import CASES_DIR, Case
from wev_skills.evaluation.workspace import case_workspace, not_started, passed, run_check


def git(root: Path, *args: str) -> str:
    done = subprocess.run(
        ("git", "-c", "user.name=t", "-c", "user.email=t@t", *args),
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def make_case(base: str, check: tuple[str, ...], files: tuple[str, ...] = ()) -> Case:
    return Case("c1", "t", "s", "r", (), base, "o", check, files)


class CaseWorkspaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.scratch = self.tmp / "scratch"
        git(self.root, "init", "-q")
        (self.root / "a.txt").write_text("1")
        git(self.root, "add", ".")
        git(self.root, "commit", "-qm", "one")
        self.base = git(self.root, "rev-parse", "HEAD")
        (self.root / "a.txt").write_text("2")
        git(self.root, "commit", "-qam", "two")
        self.runner = SubprocessRunner()
        self.policy = wiring.build_grantless_policy(Config(), self.root)
        self.allow = mock.Mock()  # stands in for a policy that accepts the argv

    def test_workspace_is_at_base_and_removed(self) -> None:
        case = make_case(self.base, ("true",))
        with case_workspace(self.runner, self.root, case, self.scratch) as path:
            self.assertEqual(git(path, "rev-parse", "HEAD"), self.base)
        self.assertFalse(path.exists())
        self.assertEqual(len(git(self.root, "worktree", "list").splitlines()), 1)

    def test_workspace_removed_on_exception(self) -> None:
        case = make_case(self.base, ("true",))
        with (
            self.assertRaises(RuntimeError),
            case_workspace(self.runner, self.root, case, self.scratch) as path,
        ):
            raise RuntimeError("boom")
        self.assertFalse(path.exists())

    def test_missing_base_is_clear(self) -> None:
        case = make_case("0" * 40, ("true",))
        with (
            self.assertRaises(NotFound) as ctx,
            case_workspace(self.runner, self.root, case, self.scratch),
        ):
            pass
        self.assertEqual(ctx.exception.code, "case_base_missing")
        self.assertEqual(len(git(self.root, "worktree", "list").splitlines()), 1)

    def test_check_sees_case_files(self) -> None:
        store = self.root / CASES_DIR / "c1"
        store.mkdir(parents=True)
        (store / "t.txt").write_text("x")
        check = (
            "python3",
            "-c",
            "import pathlib,sys; sys.exit(0 if pathlib.Path('t.txt').exists() else 1)",
        )
        for files, expected in (((), False), (("t.txt",), True)):
            case = make_case(self.base, check, files)
            with case_workspace(self.runner, self.root, case, self.scratch) as path:
                self.assertEqual(
                    passed(run_check(self.runner, self.allow, case, self.root, path, 20)), expected
                )

    def test_hanging_check_is_a_fail(self) -> None:
        case = make_case(self.base, ("python3", "-c", "import time; time.sleep(5)"))
        with case_workspace(self.runner, self.root, case, self.scratch) as path:
            self.assertFalse(passed(run_check(self.runner, self.allow, case, self.root, path, 0.5)))

    def test_denied_check_runs_nothing(self) -> None:
        class Spy:
            calls: list[object] = []

            def run(self, *args: object) -> RawCommandResult:
                self.calls.append(args)
                return RawCommandResult((), 0, "", "", 0)

        spy = Spy()
        case = make_case(self.base, ("cat", ".wev/state.json"))
        with (
            case_workspace(self.runner, self.root, case, self.scratch) as path,
            self.assertRaises(PermissionDenied),
        ):
            run_check(spy, self.policy, case, self.root, path, 5)
        self.assertEqual(spy.calls, [])

    def test_check_env_is_scrubbed(self) -> None:
        seen: list[object] = []

        class Spy:
            def run(
                self, argv: object, cwd: object, timeout: object, env: object
            ) -> RawCommandResult:
                seen.append(env)
                return RawCommandResult((), 0, "", "", 0)

        case = make_case(self.base, ("true",))
        with (
            mock.patch.dict(os.environ, {"SECRET_TOKEN": "x", "LANG": "C"}),
            case_workspace(self.runner, self.root, case, self.scratch) as path,
        ):
            run_check(Spy(), self.allow, case, self.root, path, 5)
        env = seen[0]
        assert isinstance(env, dict)
        self.assertNotIn("SECRET_TOKEN", env)
        self.assertTrue(set(env) <= {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"})
        self.assertEqual(env["LANG"], "C")

    def test_symlinked_parent_is_refused(self) -> None:
        outside = self.tmp / "outside"
        outside.mkdir()
        store = self.root / CASES_DIR / "c1" / "sub"
        store.mkdir(parents=True)
        (store / "t.txt").write_text("x")
        case = make_case(self.base, ("true",), ("sub/t.txt",))
        with case_workspace(self.runner, self.root, case, self.scratch) as path:
            (path / "sub").symlink_to(outside)
            with self.assertRaises(ValidationError):
                run_check(self.runner, self.allow, case, self.root, path, 5)
        self.assertEqual(list(outside.iterdir()), [])

    def test_dotdot_destination_is_refused(self) -> None:
        case = make_case(self.base, ("true",), ("../evil.txt",))
        with (
            case_workspace(self.runner, self.root, case, self.scratch) as path,
            self.assertRaises(PermissionDenied),
        ):
            run_check(self.runner, self.allow, case, self.root, path, 5)
        self.assertFalse((self.scratch / "evil.txt").exists())

    def test_timeout_and_exit_127_are_not_a_verdict(self) -> None:
        self.assertTrue(not_started(RawCommandResult((), None, "", "", 0, True)))
        self.assertTrue(not_started(RawCommandResult((), 127, "", "", 0)))
        self.assertFalse(not_started(RawCommandResult((), 1, "", "", 0)))

    def test_validate_at_base_rejects_a_check_that_cannot_start(self) -> None:
        code, out = self._validate_at_base(0, ["no-such-binary-xyz"])
        self.assertEqual(code, 2, out)
        self.assertIn("case_check_broken", out)

    def _validate_at_base(self, exit_code: int, check: list[str] | None = None) -> tuple[int, str]:
        data = {
            "id": "c1",
            "title": "t",
            "source": "e2e",
            "ref": "r",
            "agents": [],
            "base_commit": self.base,
            "objective": "o",
            "files": [],
            "check": check or ["true" if exit_code == 0 else "false"],
        }
        folder = self.root / "evals" / "cases"
        folder.mkdir(parents=True)
        (folder / "c1.json").write_text(json.dumps(data))
        wev = Path(__file__).resolve().parents[2] / "bin" / "wev"
        done = subprocess.run(
            (str(wev), "cases", "validate", "--at-base"),
            cwd=self.root,
            capture_output=True,
            text=True,
            env={**os.environ, "WEV_LANG": "en"},
        )
        return done.returncode, done.stdout + done.stderr

    def test_validate_at_base_accepts_a_failing_check(self) -> None:
        code, out = self._validate_at_base(1)
        self.assertEqual(code, 0, out)
        self.assertIn('"fails_at_base": true', out)

    def test_validate_at_base_rejects_a_passing_check(self) -> None:
        code, out = self._validate_at_base(0)
        self.assertEqual(code, 2, out)
        self.assertIn("case_passes_at_base", out)


if __name__ == "__main__":
    unittest.main()
