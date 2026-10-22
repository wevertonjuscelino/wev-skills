import json
import tempfile
import unittest
from pathlib import Path

from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import StateConflict, ValidationError
from wev_skills.evaluation import cases

CHECK = ["python3", "-m", "unittest", "tests.unit.test_x"]


def case_data(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "a",
        "title": "A",
        "source": "e2e",
        "ref": "r",
        "agents": [],
        "base_commit": "abc",
        "objective": "do it",
        "check": CHECK,
        "files": [],
    }
    return {**base, **over}


def write(root: Path, rel: str, text: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_case(root: Path, **over: object) -> None:
    data = case_data(**over)
    write(root, f"evals/cases/{data['id']}.json", json.dumps(data))


class FakeRunner:
    def __init__(self, stdout: str) -> None:
        self.stdout, self.argv = stdout, ()

    def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
        self.argv = tuple(argv)
        return RawCommandResult(tuple(argv), 0, self.stdout, "", 1)


class CasesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def invalid(self) -> ValidationError:
        with self.assertRaises(ValidationError) as ctx:
            cases.load_cases(self.root)
        self.assertEqual(ctx.exception.code, "invalid_case")
        return ctx.exception

    def test_loads_a_valid_case(self) -> None:
        write_case(self.root, files=["tests/unit/test_x.py"])
        write(self.root, "evals/cases/a/tests/unit/test_x.py")
        self.assertEqual(cases.load_cases(self.root)[0].check, tuple(CHECK))

    def test_rejects_unknown_source(self) -> None:
        write_case(self.root, source="rumor")
        self.invalid()

    def test_rejects_file_listed_but_missing(self) -> None:
        write_case(self.root, files=["tests/unit/test_x.py"])
        self.invalid()

    def test_rejects_path_escape(self) -> None:
        write_case(self.root, files=["../x"])
        write(self.root, "evals/cases/a/keep")
        write(self.root, "evals/cases/x")
        self.invalid()

    def test_error_names_the_file(self) -> None:
        write_case(self.root, source="rumor")
        self.assertIn("a.json", self.invalid().message)

    def test_cases_for_empty_agents_means_all(self) -> None:
        loaded = (cases.Case(**{**case_data(), "agents": (), "check": ()}),)  # type: ignore[arg-type]
        self.assertEqual(cases.cases_for(loaded, "any"), loaded)

    def test_cases_for_filters_by_agent(self) -> None:
        mine = cases.Case(**{**case_data(agents=("s1",)), "agents": ("s1",), "check": ()})  # type: ignore[arg-type]
        self.assertEqual(cases.cases_for((mine,), "s1"), (mine,))
        self.assertEqual(cases.cases_for((mine,), "s2"), ())

    def test_digest_changes_with_any_byte(self) -> None:
        write(self.root, "evals/cases/a/f", "one")
        before = cases.case_set_digest(self.root)
        write(self.root, "evals/cases/a/f", "two")
        self.assertNotEqual(before, cases.case_set_digest(self.root))

    def test_digest_ignores_order_of_creation(self) -> None:
        other = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(other))
        for rel in ("evals/cases/a/f", "evals/cases/b/g"):
            write(self.root, rel)
        for rel in ("evals/cases/b/g", "evals/cases/a/f"):
            write(other, rel)
        self.assertEqual(cases.case_set_digest(self.root), cases.case_set_digest(other))

    def test_uncommitted_case_is_refused(self) -> None:
        runner = FakeRunner("?? evals/cases/a.json\n")
        with self.assertRaises(StateConflict) as ctx:
            cases.ensure_committed(runner, self.root)
        self.assertEqual(ctx.exception.code, "cases_uncommitted")
        self.assertIn("--untracked-files=all", runner.argv)
        cases.ensure_committed(FakeRunner(""), self.root)


if __name__ == "__main__":
    unittest.main()
