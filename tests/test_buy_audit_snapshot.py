import json
from unittest.mock import patch

from finance_tools.portfolio_store import add_buy_proposal, confirm_proposal


def _portfolio(path):
    path.write_text(
        json.dumps(
            {
                "portfolio_id": "test-audit",
                "initial_capital": 10000,
                "cash": 10000,
                "positions": [],
                "pending_proposals": [],
                "closed_proposals": [],
            }
        ),
        encoding="utf-8",
    )


def test_every_buy_proposal_gets_an_audit_snapshot(tmp_path):
    path = tmp_path / "portfolio.json"
    _portfolio(path)

    proposal = add_buy_proposal("ENI.MI", "Richiesta manuale", 500, 23.9, path=path)
    snapshot = proposal["metadata"]["entry_audit_snapshot"]

    assert snapshot["schema_version"] == 1
    assert snapshot["captured_at"]
    assert snapshot["entry_price"] == 23.9
    assert snapshot["audit_complete"] is False


def test_automatic_buy_is_blocked_without_complete_audit(tmp_path):
    path = tmp_path / "portfolio.json"
    _portfolio(path)
    proposal = add_buy_proposal(
        "ENI.MI",
        "Acquisto automatico",
        500,
        23.9,
        metadata={"source": "autonomous_met_entry_condition"},
        path=path,
    )

    result = confirm_proposal(proposal["id"], path=path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert saved["positions"] == []
    assert saved["cash"] == 10000
    assert saved["closed_proposals"][0]["failure_reason"] == "snapshot audit ingresso automatico mancante o incompleto"


def test_complete_automatic_audit_is_copied_to_position(tmp_path):
    path = tmp_path / "portfolio.json"
    _portfolio(path)
    snapshot = {
        "schema_version": 1,
        "captured_at": "2026-08-02T10:00:00",
        "decision_kind": "automatic_monitored_condition",
        "source": "autonomous_met_entry_condition",
        "condition_id": "condition-1",
        "condition": "Breakout sopra 23,50",
        "scenario": {
            "type": "BREAKOUT",
            "state": "BUY_CANDIDATE",
            "chart_entry_confirmed": True,
            "news_negative": False,
            "required_volume_ratio": 0.8,
        },
        "observed_price": 23.9,
        "entry_price": 23.9,
        "trigger": 23.5,
        "volume_ratio": 1.2,
        "daily_bar_complete": True,
        "liquidity_ok": True,
        "chart_entry_confirmed": True,
        "news_negative": False,
        "audit_complete": True,
    }
    proposal = add_buy_proposal(
        "ENI.MI",
        "Condizione verificata",
        500,
        23.9,
        metadata={
            "source": "autonomous_met_entry_condition",
            "entry_audit_snapshot": snapshot,
        },
        path=path,
    )
    risk = {"allowed": True, "amount": 500.0, "reason": "limiti rispettati"}

    with patch("finance_tools.risk_manager.prepare_buy", return_value=risk), patch(
        "finance_tools.portfolio_registry.load_portfolio_config", return_value={}
    ):
        result = confirm_proposal(proposal["id"], path=path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    stored = saved["positions"][0]["entry_audit_snapshot"]
    assert result["status"] == "ok"
    assert stored["condition_id"] == "condition-1"
    assert stored["scenario"]["state"] == "BUY_CANDIDATE"
    assert stored["risk_validation"] == risk
    assert saved["closed_proposals"][0]["metadata"]["entry_audit_snapshot"] == stored
