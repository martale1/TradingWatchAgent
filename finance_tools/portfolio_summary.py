from datetime import datetime

from finance_tools.performance_tool import latest_quote
from finance_tools.portfolio_registry import (
    list_portfolios,
    load_portfolio_config,
    load_portfolio_state,
)


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def open_positions(portfolio):
    return [
        item
        for item in (portfolio or {}).get("positions", [])
        if item.get("status") == "open"
    ]


def load_shared_quotes(portfolios):
    tickers = sorted(
        {
            str(position.get("ticker") or "").strip().upper()
            for portfolio in portfolios
            for position in open_positions(portfolio)
            if position.get("ticker")
        }
    )
    quotes = {}
    errors = {}
    for ticker in tickers:
        try:
            quotes[ticker] = latest_quote(ticker)
        except Exception as exc:
            errors[ticker] = str(exc)
    return quotes, errors


def position_market_value(position, quote):
    allocated = safe_float(position.get("allocated_amount"))
    entry_price = safe_float(position.get("entry_price"))
    quantity = safe_float(position.get("virtual_quantity"))
    if not quantity and allocated and entry_price:
        quantity = allocated / entry_price
    current_price = safe_float((quote or {}).get("current_price"), None)
    if current_price is None or not quantity:
        return allocated
    return quantity * current_price


def build_portfolios_summary(include_archived=False):
    registry = list_portfolios(include_archived=include_archived)
    loaded = []
    for entry in registry.get("items", []):
        portfolio_id = entry["id"]
        config = load_portfolio_config(portfolio_id) or {}
        portfolio = load_portfolio_state(portfolio_id) or {}
        loaded.append(
            {
                "entry": entry,
                "config": config,
                "portfolio": portfolio,
            }
        )

    quotes, quote_errors = load_shared_quotes(
        [item["portfolio"] for item in loaded]
    )
    rows = []
    for item in loaded:
        entry = item["entry"]
        config = item["config"]
        portfolio = item["portfolio"]
        positions = open_positions(portfolio)
        cash = safe_float(portfolio.get("cash"))
        initial_capital = safe_float(portfolio.get("initial_capital"))
        invested_amount = sum(
            safe_float(position.get("allocated_amount"))
            for position in positions
        )
        positions_value = sum(
            position_market_value(
                position,
                quotes.get(str(position.get("ticker") or "").strip().upper()),
            )
            for position in positions
        )
        total_value = cash + positions_value
        pnl = total_value - initial_capital
        pnl_pct = (pnl / initial_capital * 100.0) if initial_capital else 0.0
        cash_pct = (cash / total_value * 100.0) if total_value else 0.0
        exposure_pct = (
            positions_value / total_value * 100.0 if total_value else 0.0
        )
        position_tickers = [
            str(position.get("ticker") or "").strip().upper()
            for position in positions
            if position.get("ticker")
        ]
        position_rows = []
        for position in positions:
            ticker = str(position.get("ticker") or "").strip().upper()
            quote = quotes.get(ticker) or {}
            allocated = safe_float(position.get("allocated_amount"))
            market_value = position_market_value(position, quote)
            position_pnl = market_value - allocated
            position_pnl_pct = (
                position_pnl / allocated * 100.0 if allocated else 0.0
            )
            position_rows.append(
                {
                    "ticker": ticker,
                    "entry_price": (
                        round(safe_float(position.get("entry_price")), 4)
                        if position.get("entry_price") is not None
                        else None
                    ),
                    "market_value": round(market_value, 2),
                    "pnl": round(position_pnl, 2),
                    "pnl_pct": round(position_pnl_pct, 2),
                    "current_price": (
                        round(safe_float(quote.get("current_price")), 4)
                        if quote.get("current_price") is not None
                        else None
                    ),
                    "daily_change_pct": (
                        round(safe_float(quote.get("daily_change_pct")), 2)
                        if quote.get("daily_change_pct") is not None
                        else None
                    ),
                    "quote_available": ticker in quotes,
                }
            )
        position_rows.sort(key=lambda row: row["market_value"], reverse=True)
        rows.append(
            {
                "portfolio_id": entry["id"],
                "name": config.get("name") or entry.get("name") or entry["id"],
                "description": config.get("description", ""),
                "status": config.get("status", entry.get("status", "active")),
                "risk_profile": config.get(
                    "risk_profile",
                    entry.get("risk_profile", "balanced"),
                ),
                "base_currency": portfolio.get("base_currency", "EUR"),
                "initial_capital": round(initial_capital, 2),
                "cash": round(cash, 2),
                "cash_pct": round(cash_pct, 2),
                "invested_amount": round(invested_amount, 2),
                "positions_value": round(positions_value, 2),
                "exposure_pct": round(exposure_pct, 2),
                "total_value": round(total_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "positions_count": len(positions),
                "positions": position_rows,
                "tickers": position_tickers,
                "quote_errors_count": sum(
                    1 for ticker in position_tickers if ticker in quote_errors
                ),
                "allowed_markets": config.get("allowed_markets", []),
                "allowed_asset_classes": config.get(
                    "allowed_asset_classes",
                    [],
                ),
            }
        )

    totals = {
        "initial_capital": round(
            sum(row["initial_capital"] for row in rows),
            2,
        ),
        "total_value": round(sum(row["total_value"] for row in rows), 2),
        "cash": round(sum(row["cash"] for row in rows), 2),
        "positions_value": round(
            sum(row["positions_value"] for row in rows),
            2,
        ),
        "pnl": round(sum(row["pnl"] for row in rows), 2),
        "positions_count": sum(row["positions_count"] for row in rows),
    }
    totals["pnl_pct"] = round(
        (
            totals["pnl"] / totals["initial_capital"] * 100.0
            if totals["initial_capital"]
            else 0.0
        ),
        2,
    )
    return {
        "status": "ok",
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "count": len(rows),
        "active_count": sum(1 for row in rows if row["status"] == "active"),
        "quotes_loaded": len(quotes),
        "quote_errors": quote_errors,
        "totals": totals,
        "items": rows,
        "note": (
            "I totali sono una vista comparativa di capitali virtuali "
            "indipendenti e non rappresentano un unico conto."
        ),
    }
