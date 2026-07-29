from unittest.mock import patch

from finance_tools.telegram_tool import (
    build_readable_monitoring_summary,
    build_readable_performance_summary,
)


EMPTY_PERFORMANCE = {
    "status": "ok",
    "total_value": 10000,
    "total_pnl": 0,
    "total_pnl_pct": 0,
    "cash": 10000,
    "cash_pct": 100,
    "invested_amount": 0,
    "exposure_pct": 0,
    "positions": [],
    "alerts": [],
}


def test_monitoring_summary_identifies_selected_portfolio():
    with (
        patch("finance_tools.telegram_tool.portfolio_status_summary") as status,
        patch("finance_tools.telegram_tool.calculate_portfolio_performance", return_value=EMPTY_PERFORMANCE),
        patch("finance_tools.telegram_tool.list_monitored_conditions", return_value=[]),
        patch("finance_tools.telegram_tool.load_portfolio", return_value={"closed_proposals": []}),
        patch("finance_tools.telegram_tool.load_agent_run_state", return_value={}),
    ):
        status.return_value = {
            "cash": 10000,
            "positions": [],
            "pending_buy_proposals": [],
        }
        message = build_readable_monitoring_summary(portfolio_id="dinamico-10k")

    assert "Portafoglio | Dinamico 10k [dinamico-10k]" in message


def test_performance_summary_identifies_selected_portfolio():
    message = build_readable_performance_summary(
        EMPTY_PERFORMANCE,
        portfolio_id="materie-prime",
    )

    assert "Portafoglio | Materie prime [materie-prime]" in message
