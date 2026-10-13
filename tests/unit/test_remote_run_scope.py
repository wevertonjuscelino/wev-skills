"""Mode and risk of a remote command: the run decides, the command line may only restrict."""

from __future__ import annotations

import unittest
from pathlib import Path

from wev_skills.config import Config
from wev_skills.core.active import ActiveRun
from wev_skills.core.contracts import Mode, RiskLevel
from wev_skills.core.errors import PermissionDenied
from wev_skills.remote.run_scope import resolve_levels
from wev_skills.state.model import Phase


def active(mode: Mode, risk: RiskLevel, error: str | None = None) -> ActiveRun:
    return ActiveRun(Path("/r"), Path("/r/.wev"), "run-1", mode, risk, Config(), Phase.PLAN, error)


class ResolveLevelsTests(unittest.TestCase):
    def test_without_a_run_the_command_line_decides_and_risk_defaults_to_medium(self) -> None:
        self.assertEqual(resolve_levels(None, None, None), (None, RiskLevel.MEDIUM))
        self.assertEqual(resolve_levels(None, Mode.AUTO, RiskLevel.LOW), (Mode.AUTO, RiskLevel.LOW))

    def test_the_run_gives_mode_and_risk_when_the_command_line_is_silent(self) -> None:
        for mode in Mode:
            for risk in RiskLevel:
                with self.subTest(mode=mode, risk=risk):
                    self.assertEqual(resolve_levels(active(mode, risk), None, None), (mode, risk))

    def test_plan_is_accepted_everywhere_and_wins(self) -> None:
        for mode in Mode:
            got = resolve_levels(active(mode, RiskLevel.LOW), Mode.PLAN, None)
            self.assertEqual(got, (Mode.PLAN, RiskLevel.LOW))

    def test_a_plan_run_refuses_every_other_mode(self) -> None:
        for mode in (Mode.EXECUTE, Mode.AUTO, Mode.RESUME):
            with self.subTest(mode=mode), self.assertRaises(PermissionDenied) as ctx:
                resolve_levels(active(Mode.PLAN, RiskLevel.LOW), mode, None)
            self.assertEqual(ctx.exception.code, "remote_mode_widened")

    def test_a_non_plan_run_keeps_its_own_mode_whatever_non_plan_mode_is_asked(self) -> None:
        got = resolve_levels(active(Mode.AUTO, RiskLevel.LOW), Mode.EXECUTE, None)
        self.assertEqual(got, (Mode.AUTO, RiskLevel.LOW))

    def test_risk_may_rise_but_never_fall_below_the_run(self) -> None:
        run = active(Mode.EXECUTE, RiskLevel.MEDIUM)
        self.assertEqual(resolve_levels(run, None, RiskLevel.HIGH)[1], RiskLevel.HIGH)
        self.assertEqual(resolve_levels(run, None, RiskLevel.MEDIUM)[1], RiskLevel.MEDIUM)
        with self.assertRaises(PermissionDenied) as ctx:
            resolve_levels(run, None, RiskLevel.LOW)
        self.assertEqual(ctx.exception.code, "remote_risk_widened")
        self.assertEqual(ctx.exception.details["run_risk"], "medium")

    def test_an_unreadable_run_is_refused_whatever_is_asked(self) -> None:
        run = active(Mode.PLAN, RiskLevel.HIGH, "invalid_state")
        for mode, risk in ((None, None), (Mode.PLAN, RiskLevel.HIGH), (Mode.EXECUTE, None)):
            with self.subTest(mode=mode), self.assertRaises(PermissionDenied) as ctx:
                resolve_levels(run, mode, risk)
            self.assertEqual(ctx.exception.code, "remote_run_state_unreadable")
            self.assertIn("invalid_state", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
