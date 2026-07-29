import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finance_tools import portfolio_registry as registry
from finance_tools import shared_market_analysis as shared


class MultiPortfolioTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.portfolios_root = self.root / "data" / "portfolios"
        self.legacy_path = self.root / "portfolio.json"
        self.registry_patches = [
            patch.object(registry, "PORTFOLIOS_ROOT", self.portfolios_root),
            patch.object(registry, "REGISTRY_FILE", self.portfolios_root / "registry.json"),
            patch.object(registry, "LEGACY_PORTFOLIO_FILE", self.legacy_path),
        ]
        for item in self.registry_patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.registry_patches):
            item.stop()
        self.temporary.cleanup()

    def write_legacy(self):
        payload = {
            "version": 1,
            "initial_capital": 20000.0,
            "cash": 15000.0,
            "positions": [
                {
                    "ticker": "AAA.MI",
                    "status": "open",
                    "allocated_amount": 5000.0,
                }
            ],
            "watchlist": [],
            "monitored_conditions": [{"id": "condition-1", "status": "waiting"}],
            "pending_proposals": [],
            "closed_proposals": [],
        }
        self.legacy_path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_migration_is_idempotent_and_preserves_legacy_state(self):
        legacy = self.write_legacy()
        first = registry.ensure_registry()
        second = registry.ensure_registry()
        migrated = registry.load_portfolio_state("main")

        self.assertEqual(first, second)
        self.assertEqual(migrated["cash"], legacy["cash"])
        self.assertEqual(migrated["positions"], legacy["positions"])
        self.assertEqual(
            migrated["monitored_conditions"],
            legacy["monitored_conditions"],
        )
        self.assertEqual(
            json.loads(self.legacy_path.read_text(encoding="utf-8")),
            legacy,
        )

    def test_portfolios_have_independent_state_and_profiles(self):
        self.write_legacy()
        registry.ensure_registry()
        created = registry.create_portfolio(
            "dynamic-test",
            "Dinamico test",
            10000,
            profile_name="dynamic",
        )

        main = registry.load_portfolio_state("main")
        dynamic = registry.load_portfolio_state("dynamic-test")
        config = registry.load_portfolio_config("dynamic-test")

        self.assertEqual(main["cash"], 15000.0)
        self.assertEqual(dynamic["cash"], 10000.0)
        self.assertEqual(dynamic["positions"], [])
        self.assertEqual(config["risk_profile"], "dynamic")
        self.assertEqual(config["risk_limits"]["max_position_pct"], 18.0)
        self.assertEqual(created["portfolio"]["portfolio_id"], "dynamic-test")

    def test_same_analysis_is_evaluated_differently_by_profile(self):
        self.write_legacy()
        registry.ensure_registry()
        registry.update_portfolio_config(
            "main",
            {
                "risk_profile": "conservative",
                "risk_limits": {},
            },
        )
        registry.create_portfolio(
            "dynamic-test",
            "Dinamico test",
            10000,
            profile_name="dynamic",
        )
        shared_root = self.root / "data" / "shared"
        latest_result = shared_root / "opportunities" / "latest.json"
        snapshot = {
            "run_id": "shared-test",
            "created_at": "2026-07-28T12:00:00",
            "count": 1,
            "items": [
                {
                    "ticker": "TEST.MI",
                    "market_key": "ftse_mib",
                    "asset_class": "equity",
                    "score": 5.5,
                    "close": 9.8,
                    "support_10": 9.2,
                    "resistance_10": 10.0,
                    "volume_ma10": 100000.0,
                    "turnover_eur": 150000.0,
                    "liquidity_ok": True,
                    "leveraged": False,
                    "shared_analysis_run_id": "shared-test",
                    "shared_analysis_as_of": "2026-07-28T12:00:00",
                }
            ],
        }
        with (
            patch.object(shared, "LATEST_OPPORTUNITIES_FILE", latest_result),
            patch.object(
                shared,
                "portfolio_runtime_path",
                lambda portfolio_id: self.portfolios_root / portfolio_id / "runtime.json",
            ),
        ):
            result = shared.evaluate_snapshot_for_portfolios(snapshot)

        by_id = {item["portfolio_id"]: item for item in result["portfolios"]}
        self.assertFalse(by_id["main"]["items"][0]["eligible"])
        self.assertTrue(by_id["dynamic-test"]["items"][0]["eligible"])
        self.assertEqual(
            by_id["main"]["items"][0]["shared_analysis_run_id"],
            by_id["dynamic-test"]["items"][0]["shared_analysis_run_id"],
        )

        applications = shared.apply_shared_snapshot_to_portfolios(
            snapshot,
            result,
            max_candidates_per_market=3,
        )
        applications_by_id = {
            item["portfolio_id"]: item for item in applications
        }
        self.assertEqual(
            applications_by_id["main"]["created_conditions_count"],
            0,
        )
        self.assertEqual(
            applications_by_id["dynamic-test"]["created_conditions_count"],
            1,
        )
        dynamic_state = registry.load_portfolio_state("dynamic-test")
        self.assertEqual(
            dynamic_state["monitored_conditions"][0]["ticker"],
            "TEST.MI",
        )
        self.assertEqual(
            dynamic_state["monitored_conditions"][0]["metadata"]["score"],
            5,
        )
        repeated = shared.apply_shared_snapshot_to_portfolios(
            snapshot,
            result,
            max_candidates_per_market=3,
        )
        repeated_by_id = {item["portfolio_id"]: item for item in repeated}
        self.assertEqual(
            repeated_by_id["dynamic-test"]["created_conditions_count"],
            0,
        )
        dynamic_state_after_repeat = registry.load_portfolio_state("dynamic-test")
        self.assertEqual(len(dynamic_state_after_repeat["monitored_conditions"]), 1)


if __name__ == "__main__":
    unittest.main()
