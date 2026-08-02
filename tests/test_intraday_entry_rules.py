import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from finance_tools.market_session import market_close_status
from finance_tools.monitoring_rules import (
    SCENARIO_CONFIRMING,
    SCENARIO_NEAR_TRIGGER,
    _evaluate_breakout,
    _evaluate_pullback,
    chart_report_confirms_entry,
)


class IntradayEntryRulesTestCase(unittest.TestCase):
    def test_market_session_exposes_progress(self):
        status = market_close_status(
            "TEST.MI",
            snapshot_date="2026-07-29",
            now=datetime(2026, 7, 29, 13, 15, tzinfo=ZoneInfo("Europe/Rome")),
        )

        self.assertFalse(status["daily_bar_complete"])
        self.assertEqual(status["market_session_progress"], 0.5)

    def test_intraday_breakout_confirms_when_volume_pace_is_sufficient(self):
        state, reason = _evaluate_breakout(
            {"trigger": 100, "support": 95},
            {
                "close": 101,
                "volume": 500_000,
                "volume_ma10": 1_000_000,
                "daily_bar_complete": False,
                "market_session_progress": 0.5,
            },
            {"liquidity_ok": True},
        )

        self.assertEqual(state, SCENARIO_CONFIRMING)
        self.assertIn("ritmo volumi 1.00x", reason)

    def test_intraday_breakout_waits_when_volume_pace_is_insufficient(self):
        state, _ = _evaluate_breakout(
            {"trigger": 100, "support": 95},
            {
                "close": 101,
                "volume": 200_000,
                "volume_ma10": 1_000_000,
                "daily_bar_complete": False,
                "market_session_progress": 0.5,
            },
            {"liquidity_ok": True},
        )

        self.assertEqual(state, SCENARIO_NEAR_TRIGGER)

    def test_intraday_pullback_can_confirm_before_close(self):
        state, reason = _evaluate_pullback(
            {"support": 100, "entry_area_max": 102.5, "stop": 98.8},
            {
                "close": 101,
                "rsi": 55,
                "volume": 450_000,
                "volume_ma10": 1_000_000,
                "daily_bar_complete": False,
                "market_session_progress": 0.5,
            },
            {"liquidity_ok": True},
        )

        self.assertEqual(state, SCENARIO_CONFIRMING)
        self.assertIn("pullback intraday", reason)

    def test_completed_analysis_is_not_automatically_a_buy_confirmation(self):
        report = (
            "Volumi molto bassi e momentum in indebolimento. "
            "Attendere conferme prima di interpretare il consolidamento come ripartenza."
        )

        self.assertFalse(chart_report_confirms_entry(report))

    def test_chart_requires_explicit_operational_confirmation(self):
        self.assertTrue(
            chart_report_confirms_entry(
                "Rimbalzo confermato sul supporto con volumi adeguati: ingresso confermato."
            )
        )


if __name__ == "__main__":
    unittest.main()
