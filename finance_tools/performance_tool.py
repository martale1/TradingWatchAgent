import json
from datetime import datetime

import yfinance as yf

from finance_tools.portfolio_store import load_portfolio


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def latest_quote(ticker):
    data = yf.download(ticker, period="5d", interval="1d", progress=False, auto_adjust=False)
    if data is None or data.empty:
        raise RuntimeError(f"Nessun prezzo disponibile per {ticker}")
    close = data["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close = close.dropna()
    if close.empty:
        raise RuntimeError(f"Nessuna chiusura disponibile per {ticker}")
    current = float(close.iloc[-1])
    previous = float(close.iloc[-2]) if len(close) >= 2 else None
    daily_change_pct = ((current - previous) / previous * 100.0) if previous else None
    return {
        "current_price": current,
        "previous_close": previous,
        "daily_change_pct": daily_change_pct,
    }


def latest_price(ticker):
    return latest_quote(ticker)["current_price"]


def calculate_portfolio_performance(path=None):
    portfolio = load_portfolio(path) if path else load_portfolio()
    if portfolio is None:
        return {
            "status": "missing",
            "message": "portfolio.json non esiste.",
            "positions": [],
            "alerts": [],
        }

    positions = [item for item in portfolio.get("positions", []) if item.get("status") == "open"]
    cash = safe_float(portfolio.get("cash"))
    initial_capital = safe_float(portfolio.get("initial_capital"))
    rows = []
    alerts = []
    invested = 0.0
    current_positions_value = 0.0

    for item in positions:
        ticker = str(item.get("ticker", "")).strip().upper()
        allocated = safe_float(item.get("allocated_amount"))
        entry = safe_float(item.get("entry_price"))
        quantity = safe_float(item.get("virtual_quantity"))
        if not quantity and allocated and entry:
            quantity = allocated / entry
        invested += allocated
        try:
            quote = latest_quote(ticker)
            price = quote["current_price"]
            market_value = quantity * price if quantity else allocated
            pnl = market_value - allocated
            pnl_pct = (pnl / allocated * 100.0) if allocated else 0.0
            price_change_pct = ((price - entry) / entry * 100.0) if entry else 0.0
            daily_change_pct = quote.get("daily_change_pct")
            previous_close = quote.get("previous_close")
            status = "ok"
            error = ""
        except Exception as exc:
            price = None
            daily_change_pct = None
            previous_close = None
            market_value = allocated
            pnl = 0.0
            pnl_pct = 0.0
            price_change_pct = 0.0
            status = "price_error"
            error = str(exc)
            alerts.append(
                {
                    "level": "warning",
                    "ticker": ticker,
                    "type": "price_error",
                    "message": f"{ticker}: prezzo non disponibile ({exc})",
                }
            )

        current_positions_value += market_value
        if pnl_pct >= 5:
            alerts.append(
                {
                    "level": "info",
                    "ticker": ticker,
                    "type": "position_gain",
                    "message": f"{ticker}: rendimento posizione {pnl_pct:.2f}%",
                }
            )
        elif pnl_pct <= -3:
            alerts.append(
                {
                    "level": "warning",
                    "ticker": ticker,
                    "type": "position_loss",
                    "message": f"{ticker}: rendimento posizione {pnl_pct:.2f}%",
                }
            )

        rows.append(
            {
                "ticker": ticker,
                "entry_price": round(entry, 4) if entry else None,
                "current_price": round(price, 4) if price is not None else None,
                "previous_close": round(previous_close, 4) if previous_close is not None else None,
                "daily_change_pct": round(daily_change_pct, 2) if daily_change_pct is not None else None,
                "virtual_quantity": round(quantity, 4) if quantity else None,
                "invested_amount": round(allocated, 2),
                "market_value": round(market_value, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "price_change_pct": round(price_change_pct, 2),
                "status": status,
                "error": error,
                "opened_at": item.get("opened_at"),
                "reason": item.get("reason", ""),
            }
        )

    total_value = cash + current_positions_value
    total_pnl = total_value - initial_capital
    total_pnl_pct = (total_pnl / initial_capital * 100.0) if initial_capital else 0.0
    exposure_pct = (current_positions_value / total_value * 100.0) if total_value else 0.0
    cash_pct = (cash / total_value * 100.0) if total_value else 0.0

    if total_pnl_pct >= 2:
        alerts.append(
            {
                "level": "info",
                "ticker": "PORTFOLIO",
                "type": "portfolio_gain",
                "message": f"Portafoglio totale {total_pnl_pct:.2f}%",
            }
        )
    elif total_pnl_pct <= -2:
        alerts.append(
            {
                "level": "warning",
                "ticker": "PORTFOLIO",
                "type": "portfolio_loss",
                "message": f"Portafoglio totale {total_pnl_pct:.2f}%",
            }
        )

    best = max(rows, key=lambda item: item["pnl_pct"], default=None)
    worst = min(rows, key=lambda item: item["pnl_pct"], default=None)

    return {
        "status": "ok",
        "updated_at": now_iso(),
        "initial_capital": round(initial_capital, 2),
        "cash": round(cash, 2),
        "invested_amount": round(invested, 2),
        "positions_value": round(current_positions_value, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "exposure_pct": round(exposure_pct, 2),
        "cash_pct": round(cash_pct, 2),
        "positions_count": len(rows),
        "best_position": best,
        "worst_position": worst,
        "positions": rows,
        "alerts": alerts,
    }


def build_performance_summary(performance=None):
    perf = performance or calculate_portfolio_performance()
    if perf.get("status") != "ok":
        return perf.get("message", "Performance non disponibile.")

    lines = [
        "TradingWatchAgent - performance portafoglio",
        "",
        f"Valore totale: EUR {perf['total_value']:.2f}",
        f"P/L totale: EUR {perf['total_pnl']:.2f} ({perf['total_pnl_pct']:.2f}%)",
        f"Cash: EUR {perf['cash']:.2f} ({perf['cash_pct']:.1f}%)",
        f"Investito: EUR {perf['invested_amount']:.2f} ({perf['exposure_pct']:.1f}%)",
        "",
        "Posizioni:",
    ]
    if not perf["positions"]:
        lines.append("- nessuna")
    for item in perf["positions"][:10]:
        lines.append(
            f"- {item['ticker']}: EUR {item['invested_amount']:.2f} -> "
            f"EUR {item['market_value']:.2f}, P/L EUR {item['pnl']:.2f} ({item['pnl_pct']:.2f}%)"
        )

    best = perf.get("best_position")
    worst = perf.get("worst_position")
    if best or worst:
        lines.append("")
        if best:
            lines.append(f"Best: {best['ticker']} {best['pnl_pct']:.2f}%")
        if worst:
            lines.append(f"Worst: {worst['ticker']} {worst['pnl_pct']:.2f}%")

    if perf.get("alerts"):
        lines.append("")
        lines.append("Alert performance:")
        for alert in perf["alerts"][:10]:
            lines.append(f"- {alert['message']}")

    return "\n".join(lines)


def calculate_portfolio_performance_json():
    return json.dumps(calculate_portfolio_performance(), ensure_ascii=False, indent=2)
