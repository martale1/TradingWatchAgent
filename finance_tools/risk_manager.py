import os
from datetime import datetime


MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "12"))
MAX_SECTOR_PCT = float(os.getenv("MAX_SECTOR_PCT", "25"))
MIN_CASH_PCT = float(os.getenv("MIN_CASH_PCT", "12"))
MIN_TRADE_PCT = float(os.getenv("MIN_TRADE_PCT", "1"))
MAX_NEW_POSITION_PCT = float(os.getenv("MAX_NEW_POSITION_PCT", "8"))
MAX_INCREMENT_PCT = float(os.getenv("MAX_INCREMENT_PCT", "3"))


def capital_base(portfolio):
    return float(portfolio.get("cash") or 0) + sum(
        float(item.get("allocated_amount") or 0)
        for item in portfolio.get("positions", [])
        if item.get("status") == "open"
    )


def execution_key(ticker, condition_id="", scenario="", portfolio_id="main"):
    return ":".join(
        [
            str(portfolio_id or "main").strip().lower(),
            datetime.now().date().isoformat(),
            str(ticker or "").strip().upper(),
            str(condition_id or "manual"),
            str(scenario or "BUY").upper(),
        ]
    )


def prepare_buy(
    portfolio,
    ticker,
    requested_amount,
    execution_id="",
    sector="",
    risk_limits=None,
):
    ticker = str(ticker or "").strip().upper()
    limits = risk_limits or {}
    max_position_pct = float(limits.get("max_position_pct", MAX_POSITION_PCT))
    max_sector_pct = float(limits.get("max_sector_pct", MAX_SECTOR_PCT))
    min_cash_pct = float(limits.get("min_cash_pct", MIN_CASH_PCT))
    min_trade_pct = float(limits.get("min_trade_pct", MIN_TRADE_PCT))
    max_new_position_pct = float(
        limits.get("max_new_position_pct", MAX_NEW_POSITION_PCT)
    )
    max_increment_pct = float(limits.get("max_increment_pct", MAX_INCREMENT_PCT))
    max_positions = int(limits.get("max_positions", 0) or 0)
    base = capital_base(portfolio)
    cash = float(portfolio.get("cash") or 0)
    existing = next(
        (
            item
            for item in portfolio.get("positions", [])
            if str(item.get("ticker") or "").strip().upper() == ticker and item.get("status") == "open"
        ),
        None,
    )
    current = float((existing or {}).get("allocated_amount") or 0)
    today = datetime.now().date().isoformat()
    already_applied = any(
        item.get("status") == "confirmed"
        and item.get("action") == "buy_virtual_position"
        and str(item.get("ticker") or "").strip().upper() == ticker
        and (
            ((item.get("metadata") or {}).get("execution_key") == execution_id and bool(execution_id))
            or str(item.get("confirmed_at") or "").startswith(today)
        )
        for item in portfolio.get("closed_proposals", [])
    )
    if already_applied:
        return {"allowed": False, "reason": "acquisto sul ticker gia applicato nella stessa seduta", "amount": 0}
    open_positions = [
        item for item in portfolio.get("positions", []) if item.get("status") == "open"
    ]
    if not existing and max_positions and len(open_positions) >= max_positions:
        return {
            "allowed": False,
            "reason": f"numero massimo posizioni raggiunto ({max_positions})",
            "amount": 0,
        }

    reserve = base * min_cash_pct / 100
    available_cash = max(0.0, cash - reserve)
    position_room = max(0.0, base * max_position_pct / 100 - current)
    sector_key = str(sector or (existing or {}).get("sector") or "").strip().lower()
    sector_invested = sum(
        float(item.get("allocated_amount") or 0)
        for item in portfolio.get("positions", [])
        if item.get("status") == "open"
        and sector_key
        and str(item.get("sector") or "").strip().lower() == sector_key
    )
    sector_room = max(0.0, base * max_sector_pct / 100 - sector_invested) if sector_key else float("inf")
    trade_cap_pct = max_increment_pct if existing else max_new_position_pct
    trade_cap = base * trade_cap_pct / 100
    requested = float(requested_amount or trade_cap)
    amount = round(min(requested, available_cash, position_room, sector_room, trade_cap), 2)
    minimum = round(base * min_trade_pct / 100, 2)
    if amount < minimum:
        return {
            "allowed": False,
            "reason": (
                f"spazio insufficiente: importo {amount:.2f}, minimo {minimum:.2f}, "
                f"cash da preservare {reserve:.2f}"
            ),
            "amount": amount,
        }
    return {
        "allowed": True,
        "amount": amount,
        "requested_amount": requested,
        "capital_base": round(base, 2),
        "cash_reserve": round(reserve, 2),
        "position_before": round(current, 2),
        "position_after": round(current + amount, 2),
        "position_after_pct": round((current + amount) / base * 100, 2) if base else 0,
        "sector": sector_key,
        "sector_after_pct": round((sector_invested + amount) / base * 100, 2) if base and sector_key else None,
        "risk_limits": {
            "min_cash_pct": min_cash_pct,
            "max_position_pct": max_position_pct,
            "max_sector_pct": max_sector_pct,
            "min_trade_pct": min_trade_pct,
            "max_new_position_pct": max_new_position_pct,
            "max_increment_pct": max_increment_pct,
            "max_positions": max_positions,
        },
    }
