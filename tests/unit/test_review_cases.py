import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from wev_skills.commands import cases as cases_command
from wev_skills.core.contracts import RawCommandResult
from wev_skills.core.errors import ValidationError
from wev_skills.evaluation import cases
from wev_skills.evaluation.review_cases import review_case_passed
from wev_skills.state.review_records import FindingRecord

DIFF = (
    "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
    "@@ -10,0 +11,3 @@\n+x\n+y\n+z\n"
)


def review_data(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "r1",
        "title": "R",
        "source": "review",
        "ref": "r",
        "agents": [],
        "base_commit": "abc1234",
        "objective": "find the bug",
        "kind": "review",
        "head_commit": "def5678",
        "expect": [{"file": "src/a.py", "first": 12, "last": 13}],
    }
    return {**base, **over}


def finding(tag: str, file: str = "src/a.py", line: int = 12) -> FindingRecord:
    return FindingRecord("f1", 1, file, line, "t", "b", tag, False, 1, 1)


class ReviewCasesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def put(self, data: dict[str, object], diff: str | None = DIFF) -> None:
        folder = self.root / "evals" / "cases"
        (folder / str(data["id"])).mkdir(parents=True, exist_ok=True)
        (folder / f"{data['id']}.json").write_text(json.dumps(data), encoding="utf-8")
        if diff is not None:
            (folder / str(data["id"]) / "change.diff").write_text(diff, encoding="utf-8")

    def refused(self) -> ValidationError:
        with self.assertRaises(ValidationError) as ctx:
            cases.load_cases(self.root)
        self.assertEqual(ctx.exception.code, "invalid_case")
        return ctx.exception

    def test_review_case_loads(self) -> None:
        self.put(review_data())
        case = cases.load_cases(self.root)[0]
        self.assertEqual((case.kind, case.head_commit), ("review", "def5678"))
        self.assertEqual(case.expect, (cases.Expect("src/a.py", 12, 13),))

    def test_review_case_with_check_refused(self) -> None:
        self.put(review_data(check=["true"]))
        self.refused()

    def test_review_case_without_diff_refused(self) -> None:
        self.put(review_data(), diff=None)
        self.refused()

    def test_build_case_without_check_refused(self) -> None:
        data = review_data(kind="build")
        self.put({k: v for k, v in data.items() if k not in ("head_commit", "expect")}, diff=None)
        self.refused()

    def test_expect_must_lie_in_stored_diff(self) -> None:
        for bad in (
            {"file": "src/a.py", "first": 1, "last": 5},
            {"file": "src/b.py", "first": 12, "last": 12},
            {"file": "src/a.py", "first": 13, "last": 12},
        ):
            self.put(review_data(expect=[bad]))
            self.refused()
        self.put(review_data(expect=[{"file": "src/a.py", "first": 9, "last": 11}]))
        cases.load_cases(self.root)  # overlap at one line is enough

    def test_commits_that_are_not_hex_ids_are_refused(self) -> None:
        for field in ("base_commit", "head_commit"):
            for bad in ("--output=x", "HEAD~1"):
                self.put(review_data(**{field: bad}))
                self.refused()

    def test_pass_rule_bug_case(self) -> None:
        self.put(review_data())
        case = cases.load_cases(self.root)[0]
        self.assertTrue(review_case_passed(case, [finding("important", line=13)]))
        self.assertFalse(review_case_passed(case, [finding("important", line=14)]))
        self.assertFalse(review_case_passed(case, [finding("important", file="src/b.py")]))
        self.assertFalse(review_case_passed(case, []))

    def test_nit_does_not_pass_a_bug_case(self) -> None:
        self.put(review_data())
        case = cases.load_cases(self.root)[0]
        self.assertFalse(review_case_passed(case, [finding("nit"), finding("pre_existing")]))

    def test_pass_rule_clean_case(self) -> None:
        self.put(review_data(expect=[]))
        case = cases.load_cases(self.root)[0]
        self.assertTrue(review_case_passed(case, []))
        self.assertTrue(review_case_passed(case, [finding("nit")]))
        self.assertFalse(review_case_passed(case, [finding("important")]))

    def test_old_cases_still_load(self) -> None:
        loaded = {c.id: c for c in cases.load_cases(Path(__file__).resolve().parents[2])}
        for name in (
            "exec-path-owned-dirs",
            "health-large-tools-list",
            "tarball-confined-dotdot-link",
        ):
            self.assertEqual((loaded[name].kind, bool(loaded[name].check)), ("build", True))

    def test_digest_covers_the_diff(self) -> None:
        self.put(review_data())
        before = cases.case_set_digest(self.root)
        self.put(review_data(), diff=DIFF + "+w\n")
        self.assertNotEqual(before, cases.case_set_digest(self.root))

    def test_at_base_compares_the_stored_diff_byte_for_byte(self) -> None:
        self.put(review_data())
        case = cases.load_cases(self.root)[0]
        scope = SimpleNamespace(root=self.root)

        class Git:
            def __init__(self, out: str) -> None:
                self.out, self.argv = out, ()

            def run(self, argv, cwd, timeout, env):  # type: ignore[no-untyped-def]
                self.argv = tuple(argv)
                return RawCommandResult(tuple(argv), 0, self.out, "", 1, False)

        same, other = Git(DIFF), Git(DIFF + "\n")
        self.assertTrue(cases_command._diff_matches(same, scope, case))  # type: ignore[arg-type]
        self.assertIn("--unified=0", same.argv)
        self.assertEqual(same.argv[-3:], ("--end-of-options", "abc1234", "def5678"))
        self.assertFalse(cases_command._diff_matches(other, scope, case))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
