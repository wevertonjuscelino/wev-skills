#!/usr/bin/env python3
"""Write ``prs.json`` for ``release_prep.py``: the pull requests merged into ``dev`` since a tag.

Usage: ``collect_release_prs.py --since TAG --until REF --out prs.json [--repo-dir DIR]``.

It lists the merge commits on the first-parent chain ``TAG..REF`` whose subject is
``Merge pull request #N from ...`` and asks ``gh pr view N --json number,title,url,labels`` for
each. ``REF`` is the tip of ``dev`` (in the release workflow, ``HEAD^2`` of the dev-to-main merge).
The only network use is ``gh``; ``pr_numbers`` is pure and is what the unit tests cover. Commits
pushed to ``dev`` without a pull request are not listed. Exit codes: 0 ok, 1 failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MERGE_SUBJECT = re.compile(r"^Merge pull request #(\d+) from \S+")


def pr_numbers(subjects: list[str]) -> list[int]:
    """Pull request numbers in the merge subjects, oldest first, without repeats."""
    numbers: list[int] = []
    for subject in reversed(subjects):
        match = MERGE_SUBJECT.match(subject)
        if match and int(match[1]) not in numbers:
            numbers.append(int(match[1]))
    return numbers


def _run(argv: list[str], cwd: Path) -> str:
    result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"{' '.join(argv[:3])} failed: {detail}")
    return result.stdout


def merged_subjects(repo: Path, since: str, until: str) -> list[str]:
    spec = f"{since}..{until}" if since else until
    out = _run(["git", "log", "--first-parent", "--merges", "--format=%s", spec], repo)
    return out.splitlines()


def fetch_pr(repo: Path, number: int) -> dict[str, object]:
    out = _run(["gh", "pr", "view", str(number), "--json", "number,title,url,labels"], repo)
    data = json.loads(out)
    if not isinstance(data, dict):
        raise RuntimeError(f"gh pr view {number}: unexpected output")
    return data


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Collect merged pull requests for a release.")
    parser.add_argument("--since", default="", help="previous release tag (empty: whole history)")
    parser.add_argument("--until", required=True, help="tip of dev")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--repo-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv[1:])
    try:
        numbers = pr_numbers(merged_subjects(args.repo_dir, args.since, args.until))
        prs = [fetch_pr(args.repo_dir, number) for number in numbers]
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"collect_release_prs: {error}", file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(prs, indent=2) + "\n", encoding="utf-8")
    print(f"collected {len(prs)} pull request(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
