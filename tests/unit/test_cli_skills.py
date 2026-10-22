"""``wev skills list``, run in-process with HOME and XDG_DATA_HOME in a temp dir."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wev_skills import cli
from wev_skills.third_party import state


def run_main(*argv: str) -> tuple[int, dict[str, object]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(["--lang", "en", *argv])
    return code, json.loads(out.getvalue() or "{}")


class ListCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        patcher = mock.patch.dict(
            os.environ, {"HOME": str(self.dir), "XDG_DATA_HOME": str(self.dir / "data")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_cli(self) -> None:
        code, payload = run_main("skills", "list")
        self.assertEqual(code, 0)
        rows = payload["sources"]
        assert isinstance(rows, list)
        self.assertEqual([r["name"] for r in rows], ["rea", "agent-skills", "wev-skills"])
        self.assertEqual(
            set(rows[0]),
            {"name", "kind", "active", "previous", "frozen", "latest_seen", "changelog"},
        )
        self.assertIsNone(rows[0]["active"])
        self.assertFalse(rows[0]["frozen"])

    def test_list_shows_state(self) -> None:
        item = state.SourceState("1.0.0", None, True, None, "1.1.0", None)
        state.save(state.data_home() / "state.json", state.State({"rea": item}, None))
        _, payload = run_main("skills", "list")
        row = payload["sources"][0]  # type: ignore[index]
        self.assertEqual(
            (row["active"], row["frozen"], row["latest_seen"]), ("1.0.0", True, "1.1.0")
        )
        self.assertIn("1.1.0", row["changelog"])

    def test_list_rejects_invalid_state(self) -> None:
        path = state.data_home() / "state.json"
        path.parent.mkdir(parents=True)
        path.write_text('{"sources": {"rea": {"active": "../x"}}}', encoding="utf-8")
        code, _ = run_main("skills", "list")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
