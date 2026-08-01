import json

from finance_tools.exit_executor import enforce_triggered_exits


def test_breached_stop_sells_open_position_once(tmp_path):
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(
        json.dumps({
            "version": 1,
            "portfolio_id": "exit-test",
            "initial_capital": 10000.0,
            "cash": 8000.0,
            "positions": [{
                "ticker": "TEST.MI",
                "status": "open",
                "entry_price": 2.0,
                "virtual_quantity": 1000.0,
                "allocated_amount": 2000.0,
            }],
            "pending_proposals": [],
            "closed_proposals": [],
        }),
        encoding="utf-8",
    )
    exit_rows = [{
        "ticker": "TEST.MI",
        "status": "USCITA DA VALUTARE",
        "current_price": 1.9,
        "stop_level": 1.95,
    }]

    first = enforce_triggered_exits(exit_rows, portfolio_path, portfolio_id="exit-test")
    second = enforce_triggered_exits(exit_rows, portfolio_path, portfolio_id="exit-test")
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))

    assert first["applied_count"] == 1
    assert first["decisions"][0]["decision"] == "sold"
    assert second["applied_count"] == 0
    assert not [item for item in portfolio["positions"] if item.get("status") == "open"]
    assert portfolio["positions"][0]["status"] == "closed"
    sells = [item for item in portfolio["closed_proposals"] if item["action"] == "sell_virtual_position"]
    assert len(sells) == 1
    assert sells[0]["metadata"]["source"] == "deterministic_exit_stop"
