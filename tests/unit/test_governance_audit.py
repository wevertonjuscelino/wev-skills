from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from wev_skills.core.errors import ValidationError
from wev_skills.governance.audit import UNREADABLE_EVENT, AuditLog

SECRET = "example_" + "Sup3rS3cret" * 2
API_TOKEN = "sk" + "-" + "aB3dE5gH7jK9mN1pQ2sT4vW6" * 2


class StepClock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        self.value += 1.0
        return self.value


class AuditLogTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "state" / "audit.jsonl"
        self.log = AuditLog(self.path, StepClock())

    def test_append_writes_one_json_object_per_line(self) -> None:
        self.log.append("approval.requested", {"id": "apr-1", "note": "line one\nline two"})
        self.log.append("approval.granted", {"id": "apr-1", "by": "ana"})
        lines = self.path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        self.assertEqual(
            first,
            {
                "ts": 1.0,
                "type": "approval.requested",
                "data": {"id": "apr-1", "note": "line one\nline two"},
            },
        )
        self.assertEqual(json.loads(lines[1])["ts"], 2.0)

    def test_append_returns_the_stored_record(self) -> None:
        record = self.log.append("x", {"a": 1})
        self.assertEqual(record, {"ts": 1.0, "type": "x", "data": {"a": 1}})
        self.assertEqual(self.log.read(), (record,))

    def test_secrets_never_reach_the_file(self) -> None:
        data = {
            "password": SECRET,
            "command": f"curl -H 'Authorization: Bearer {API_TOKEN}' https://e.example",
            "env": {"API_KEY": SECRET, "HOME": "/home/ana"},
            "args": [f"--token={SECRET}", "plain"],
        }
        record = self.log.append(f"run token={SECRET}", data)
        text = self.path.read_text()
        self.assertNotIn(SECRET, text)
        self.assertNotIn(API_TOKEN, text)
        self.assertEqual(record["data"]["env"], {"API_KEY": "[REDACTED]", "HOME": "/home/ana"})
        self.assertEqual(record["data"]["args"][1], "plain")
        self.assertEqual(data["password"], SECRET)

    def test_values_that_are_not_json_are_stringified(self) -> None:
        record = self.log.append("x", {"path": Path("/tmp/a"), "items": (1, 2), "when": None})
        self.assertEqual(record["data"], {"path": "/tmp/a", "items": [1, 2], "when": None})

    def test_read_returns_events_oldest_first_and_limit_keeps_the_latest(self) -> None:
        for number in range(5):
            self.log.append("tick", {"n": number})
        self.assertEqual([event["data"]["n"] for event in self.log.read()], [0, 1, 2, 3, 4])
        self.assertEqual([event["data"]["n"] for event in self.log.read(limit=2)], [3, 4])
        self.assertEqual(len(self.log.read(limit=99)), 5)
        self.assertEqual(self.log.read(limit=0), ())

    def test_read_of_a_missing_log_is_empty(self) -> None:
        self.assertEqual(self.log.read(), ())
        self.assertFalse(self.path.exists())

    def test_damaged_lines_stay_visible(self) -> None:
        self.log.append("ok", {"n": 1})
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write('{"torn": \n[1, 2]\n\n')
        self.log.append("ok", {"n": 2})
        events = self.log.read()
        self.assertEqual(
            [event["type"] for event in events], ["ok", UNREADABLE_EVENT, UNREADABLE_EVENT, "ok"]
        )
        self.assertEqual(events[1]["data"], {"line": 2})

    def test_invalid_arguments_are_validation_errors(self) -> None:
        for event_type, data in (("", {}), ("  ", {}), (None, {}), ("x", ["a"]), ("x", "text")):
            with self.subTest(event_type=event_type, data=data), self.assertRaises(ValidationError):
                self.log.append(event_type, data)  # type: ignore[arg-type]
        with self.assertRaises(ValidationError):
            self.log.read(limit=-1)
        self.assertFalse(self.path.exists())

    def test_file_is_private_and_default_clock_works(self) -> None:
        log = AuditLog(self.path)
        record = log.append("x", {})
        self.assertGreater(record["ts"], 1_000_000_000)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
