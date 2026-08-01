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
        "stop_action_code": "sell_all",
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
    assert sells[0]["metadata"]["action_policy"] == "sell_all"


def test_breached_level_without_sell_policy_is_not_executed(tmp_path):
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

    result = enforce_triggered_exits([{
        "ticker": "TEST.MI",
        "current_price": 1.9,
        "stop_level": 1.95,
        "stop_action_code": "evaluate",
    }], portfolio_path, portfolio_id="exit-test")
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))

    assert result["applied_count"] == 0
    assert portfolio["positions"][0]["status"] == "open"


def test_take_profit_reduces_once(tmp_path):
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
        "status": "TAKE PROFIT",
        "current_price": 2.2,
        "stop_level": 1.9,
        "stop_action_code": "sell_all",
        "take_profit_level": 2.1,
        "take_profit_action_code": "reduce_position",
        "take_profit_percent": 30,
    }]

    first = enforce_triggered_exits(exit_rows, portfolio_path, portfolio_id="exit-test")
    second = enforce_triggered_exits(exit_rows, portfolio_path, portfolio_id="exit-test")
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))

    assert first["applied_count"] == 1
    assert first["decisions"][0]["decision"] == "reduced"
    assert second["applied_count"] == 0
    assert second["decisions"][0]["decision"] == "trigger_already_executed"
    assert portfolio["positions"][0]["status"] == "open"
    assert portfolio["positions"][0]["virtual_quantity"] == 700.0
    reductions = [item for item in portfolio["closed_proposals"] if item["action"] == "reduce_virtual_position"]
    assert len(reductions) == 1
    assert reductions[0]["metadata"]["source"] == "deterministic_take_profit"
