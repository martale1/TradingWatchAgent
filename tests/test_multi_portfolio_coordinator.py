import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import agent_portfolio_manager as manager


class MultiPortfolioCoordinatorTestCase(unittest.TestCase):
    @patch.object(manager.subprocess, "run")
    @patch.object(manager, "list_portfolios")
    def test_secondary_cycles_reuse_scanners_and_skip_inactive(
        self,
        list_portfolios_mock,
        subprocess_run_mock,
    ):
        list_portfolios_mock.return_value = {
            "items": [
                {"id": "main", "name": "Main", "status": "active"},
                {"id": "dynamic-test", "name": "Dynamic", "status": "active"},
                {"id": "paused-test", "name": "Paused", "status": "paused"},
            ]
        }
        subprocess_run_mock.return_value = SimpleNamespace(
            returncode=0,
            stdout="child completed",
            stderr="",
        )
        with patch.dict(os.environ, {"ACTIVE_PORTFOLIO_ID": "main"}, clear=False):
            results = manager.run_secondary_portfolio_cycles(
                model="gpt-5-mini",
                interval_minutes=30,
                scan_limit=5,
                universe_limit=0,
                live_news=True,
                deep_confirm_limit=2,
                auto_apply_virtual=True,
                max_auto_trade_pct=8,
                periodic_max_turns=12,
            )

        self.assertEqual(results, [{"portfolio_id": "dynamic-test", "returncode": 0}])
        subprocess_run_mock.assert_called_once()
        args, kwargs = subprocess_run_mock.call_args
        command = args[0]
        self.assertIn("--skip-market-scanners", command)
        self.assertIn("--once", command)
        self.assertEqual(kwargs["env"]["ACTIVE_PORTFOLIO_ID"], "dynamic-test")
        self.assertEqual(kwargs["env"]["MULTI_PORTFOLIO_CHILD"], "1")


if __name__ == "__main__":
    unittest.main()
