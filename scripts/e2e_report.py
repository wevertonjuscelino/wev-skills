#!/usr/bin/env python3
"""Run the whole test suite and print a Markdown report: one row per end-to-end feature (each
test class under ``tests/integration``, named by its docstring) and the verdict for the system
(every test under ``tests``). Exit 1 when anything failed.

Run from the repository root: ``PYTHONPATH=src python3 scripts/e2e_report.py``.
"""

from __future__ import annotations

import sys
import unittest
from collections.abc import Iterator

E2E_PREFIX = "tests.integration."


def flatten(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def feature(test: unittest.TestCase) -> str:
    doc = type(test).__doc__
    return doc.strip().splitlines()[0] if doc else type(test).__name__


def main() -> int:
    tests = list(flatten(unittest.defaultTestLoader.discover("tests", top_level_dir=".")))
    result = unittest.TestResult()
    unittest.TestSuite(tests).run(result)
    broken = {t.id() for t, _ in result.failures + result.errors}
    skipped = {t.id() for t, _ in result.skipped}
    rows: dict[str, list[str]] = {}
    for test in tests:
        if test.id().startswith(E2E_PREFIX):
            rows.setdefault(feature(test), []).append(test.id())
    print("CLI integration, fakes only: bin/wev in a temporary git repository, no real harness.\n")
    print("| Feature | Passed | Status |\n|---|---|---|")
    for name, ids in rows.items():
        ran = [i for i in ids if i not in skipped]
        passed = [i for i in ran if i not in broken]
        status = "skipped" if not ran else "PASS" if len(passed) == len(ran) else "FAIL"
        print(f"| {name} | {len(passed)}/{len(ran)} | {status} |")
    total = result.testsRun - len(skipped)
    verdict = "PASS" if result.wasSuccessful() else "FAIL"
    good = total - len(broken)
    print(f"\nSystem: {verdict}, {good}/{total} tests passed, {len(skipped)} skipped")
    for test_id in sorted(broken):
        print(f"- failed: {test_id}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
