from unittest.mock import patch

from finance_tools.telegram_tool import build_all_portfolios_summary, _portfolio_change_brief


SUMMARY = {
    "totals": {
        "initial_capital": 30000,
        "total_value": 30400,
        "positions_value": 14000,
        "cash": 16400,
        "pnl": 400,
        "pnl_pct": 1.33,
    },
    "items": [
        {
            "portfolio_id": "main",
            "name": "Principale",
            "risk_profile": "balanced",
            "status": "active",
            "total_value": 20400,
            "positions_value": 12000,
            "exposure_pct": 58.82,
            "cash": 8400,
            "cash_pct": 41.18,
            "pnl": 400,
            "pnl_pct": 2,
            "positions_count": 1,
            "quote_errors_count": 0,
            "positions": [
                {
                    "ticker": "ENI.MI",
                    "market_value": 12000,
                    "pnl": 400,
                    "pnl_pct": 3.45,
                    "daily_change_pct": 1.2,
                }
            ],
        },
        {
            "portfolio_id": "prudente",
            "name": "Prudente",
            "risk_profile": "conservative",
            "status": "active",
            "total_value": 10000,
            "positions_value": 2000,
            "exposure_pct": 20,
            "cash": 8000,
            "cash_pct": 80,
            "pnl": 0,
            "pnl_pct": 0,
            "positions_count": 0,
            "quote_errors_count": 0,
            "positions": [],
        },
    ],
}


def test_consolidated_summary_separates_and_details_each_portfolio():
    with patch(
        "finance_tools.portfolio_summary.build_portfolios_summary",
        return_value=SUMMARY,
    ), patch(
        "finance_tools.telegram_tool._portfolio_changes_since_last_summary",
        side_effect=lambda portfolio_id: ["- COMPRATO ENI.MI @ 23,90"] if portfolio_id == "main" else [],
    ):
        message = build_all_portfolios_summary("Ciclo completato.")

    assert "Principale [main]" in message
    assert "Prudente [prudente]" in message
    assert "ENI.MI" in message
    assert "P/L" in message
    assert "oggi +1,20%" in message
    assert "Posizioni: nessuna" in message
    assert "COSA È CAMBIATO, PORTAFOGLIO PER PORTAFOGLIO" in message
    assert "- COMPRATO ENI.MI @ 23,90" in message
    assert "Prudente [prudente]\n- NESSUNA MODIFICA" in message


def test_change_labels_distinguish_sell_reduce_and_take_profit():
    message = "━" * 20
    assert _portfolio_change_brief({
        "action": "sell_virtual_position",
        "ticker": "CRUD.MI",
        "metadata": {"reference_price": 12.058},
    }).startswith("- VENDUTO CRUD.MI")
    assert _portfolio_change_brief({
        "action": "reduce_virtual_position",
        "ticker": "AMP.MI",
        "metadata": {"reference_price": 12.5, "percent": 30, "source": "deterministic_take_profit"},
    }).startswith("- TAKE PROFIT AMP.MI: venduto 30")
    assert _portfolio_change_brief({
        "action": "reduce_virtual_position",
        "ticker": "TEN.MI",
        "metadata": {"reference_price": 24.1, "percent": 50},
    }).startswith("- RIDOTTO TEN.MI: venduto 50")
    assert "━━━━━━━━━━━━━━━━━━━━" in message
