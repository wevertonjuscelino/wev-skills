"""``rea.json``: validated as data, default by Docker, private file mode."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from wev_skills.core.errors import ValidationError
from wev_skills.rea.config import ReaConfig, load_rea_config, save_rea_config


class ReaConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "conf" / "rea.json"

    def write(self, data: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_absent_defaults_by_docker(self) -> None:
        self.assertEqual(load_rea_config(self.path, True), (ReaConfig("isolated"), "default"))
        self.assertEqual(load_rea_config(self.path, False), (ReaConfig("direct"), "default"))

    def test_roundtrip_and_private_mode(self) -> None:
        cfg = ReaConfig("direct")
        save_rea_config(self.path, cfg)
        self.assertEqual(load_rea_config(self.path, True), (cfg, "config"))
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_config_wins_over_docker_default(self) -> None:
        self.write({"mode": "direct"})
        self.assertEqual(load_rea_config(self.path, True), (ReaConfig("direct"), "config"))

    def test_invalid_shapes_are_refused(self) -> None:
        bad: list[object] = [
            [],
            "isolated",
            {},
            {"mode": "isolated; sh"},
            {"mode": "Isolated"},
            {"mode": 1},
            {"mode": "direct", "extra": 1},
            {"mode": "direct", "image": "wev-rea:1"},
            {"mode": "direct", "image": 3},
            {"mode": "direct", "image": "a b:1"},
            {"mode": "direct", "image": "a/../b:1"},
        ]
        for data in bad:
            with self.subTest(data=data):
                self.write(data)
                with self.assertRaises(ValidationError) as ctx:
                    load_rea_config(self.path, True)
                self.assertEqual(ctx.exception.code, "rea_config_invalid")

    def test_not_json_is_refused(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{nope", encoding="utf-8")
        with self.assertRaises(ValidationError):
            load_rea_config(self.path, True)


if __name__ == "__main__":
    unittest.main()
