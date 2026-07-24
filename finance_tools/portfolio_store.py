import json
from datetime import datetime
from pathlib import Path

from finance_tools.common import PROJECT_ROOT


PORTFOLIO_FILE = PROJECT_ROOT / "portfolio.json"


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def default_portfolio(initial_capital):
    return {
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "base_currency": "EUR",
        "initial_capital": float(initial_capital),
        "cash": float(initial_capital),
        "positions": [],
        "watchlist": [],
        "monitored_conditions": [],
        "pending_proposals": [],
        "closed_proposals": [],
    }


def load_portfolio(path=PORTFOLIO_FILE):
    file_path = Path(path)
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def save_portfolio(portfolio, path=PORTFOLIO_FILE):
    portfolio["updated_at"] = now_iso()
    file_path = Path(path)
    file_path.write_text(json.dumps(portfolio, ensure_ascii=False, indent=2), encoding="utf-8")
    return portfolio


def init_portfolio(initial_capital, overwrite=False, path=PORTFOLIO_FILE):
    file_path = Path(path)
    if file_path.exists() and not overwrite:
        return {
            "status": "exists",
            "file": str(file_path),
            "message": "portfolio.json esiste gia. Usa overwrite=True solo se vuoi ricrearlo.",
            "portfolio": load_portfolio(file_path),
        }
    portfolio = default_portfolio(initial_capital)
    save_portfolio(portfolio, file_path)
    return {"status": "ok", "file": str(file_path), "portfolio": portfolio}


def update_portfolio_capital(new_capital, reason="", path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        portfolio = default_portfolio(float(new_capital))
        save_portfolio(portfolio, path)
        return {
            "status": "created",
            "message": "portfolio.json non esisteva: creato nuovo portafoglio.",
            "portfolio": portfolio,
        }

    old_capital = float(portfolio.get("initial_capital", 0) or 0)
    old_cash = float(portfolio.get("cash", 0) or 0)
    new_capital = float(new_capital)
    delta = new_capital - old_capital

    portfolio["initial_capital"] = new_capital
    portfolio["cash"] = round(old_cash + delta, 2)
    portfolio.setdefault("capital_history", []).append(
        {
            "created_at": now_iso(),
            "old_capital": old_capital,
            "new_capital": new_capital,
            "old_cash": old_cash,
            "new_cash": portfolio["cash"],
            "delta": delta,
            "reason": reason,
        }
    )
    save_portfolio(portfolio, path)
    return {
        "status": "ok",
        "old_capital": old_capital,
        "new_capital": new_capital,
        "old_cash": old_cash,
        "new_cash": portfolio["cash"],
        "delta": delta,
        "portfolio": portfolio,
    }


def add_proposal(action, ticker, reason, metadata=None, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste. Inizializza prima il portafoglio.")
    proposal_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    proposal = {
        "id": proposal_id,
        "created_at": now_iso(),
        "status": "pending",
        "action": action,
        "ticker": ticker,
        "reason": reason,
        "metadata": metadata or {},
    }
    portfolio.setdefault("pending_proposals", []).append(proposal)
    save_portfolio(portfolio, path)
    return proposal


def add_allocation_proposal(capital, allocations, reason, metadata=None, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        portfolio = default_portfolio(capital)
    proposal_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    proposal = {
        "id": proposal_id,
        "created_at": now_iso(),
        "status": "pending",
        "action": "create_virtual_allocation",
        "ticker": "PORTFOLIO",
        "reason": reason,
        "metadata": {
            "capital": float(capital),
            "allocations": allocations,
            **(metadata or {}),
        },
    }
    portfolio["initial_capital"] = float(capital)
    portfolio["cash"] = float(capital)
    portfolio.setdefault("positions", [])
    portfolio.setdefault("watchlist", [])
    portfolio.setdefault("pending_proposals", []).append(proposal)
    save_portfolio(portfolio, path)
    return proposal


def add_buy_proposal(ticker, reason, amount=None, entry_price=None, metadata=None, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste. Inizializza prima il portafoglio.")
    proposal_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    proposal = {
        "id": proposal_id,
        "created_at": now_iso(),
        "status": "pending",
        "action": "buy_virtual_position",
        "ticker": ticker.strip().upper(),
        "reason": reason,
        "metadata": {
            "amount": amount,
            "entry_price": entry_price,
            **(metadata or {}),
        },
    }
    portfolio.setdefault("pending_proposals", []).append(proposal)
    save_portfolio(portfolio, path)
    return proposal


def list_pending_proposals(path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        return []
    return portfolio.get("pending_proposals", [])


def portfolio_status_summary(path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        return {
            "status": "missing",
            "message": "portfolio.json non esiste.",
            "positions": [],
            "pending_buy_proposals": [],
            "pending_other_proposals": [],
            "monitored_conditions": [],
            "watchlist": [],
        }

    pending = portfolio.get("pending_proposals", [])
    pending_buy = [
        item for item in pending if item.get("action") in {"buy_virtual_position", "create_virtual_allocation"}
    ]
    pending_other = [
        item for item in pending if item.get("action") not in {"buy_virtual_position", "create_virtual_allocation"}
    ]
    return {
        "status": "ok",
        "updated_at": portfolio.get("updated_at"),
        "base_currency": portfolio.get("base_currency", "EUR"),
        "initial_capital": portfolio.get("initial_capital"),
        "cash": portfolio.get("cash"),
        "positions": portfolio.get("positions", []),
        "pending_buy_proposals": pending_buy,
        "pending_other_proposals": pending_other,
        "monitored_conditions": portfolio.get("monitored_conditions", []),
        "watchlist": portfolio.get("watchlist", []),
        "closed_proposals_count": len(portfolio.get("closed_proposals", [])),
    }


def list_watchlist(path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        return []
    return portfolio.get("watchlist", [])


def add_watchlist_item(ticker, name="", market="", reason="", priority="normal", tags=None, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste. Inizializza prima il portafoglio.")

    symbol = ticker.strip().upper()
    watchlist = portfolio.setdefault("watchlist", [])
    existing = next((item for item in watchlist if item.get("ticker") == symbol), None)
    payload = {
        "ticker": symbol,
        "name": name.strip() if name else symbol,
        "market": market.strip() if market else "",
        "reason": reason.strip() if reason else "",
        "priority": priority.strip().lower() if priority else "normal",
        "tags": tags or [],
        "status": "active",
        "updated_at": now_iso(),
        "source": "manual_watchlist",
    }
    if existing:
        existing.update({key: value for key, value in payload.items() if value not in ("", [], None)})
        existing.setdefault("added_at", now_iso())
        item = existing
    else:
        item = {"added_at": now_iso(), **payload}
        watchlist.append(item)
    save_portfolio(portfolio, path)
    return item


def remove_watchlist_item(ticker, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste.")
    symbol = ticker.strip().upper()
    watchlist = portfolio.setdefault("watchlist", [])
    match = next((item for item in watchlist if item.get("ticker") == symbol), None)
    if not match:
        return {"status": "missing", "ticker": symbol}
    watchlist.remove(match)
    save_portfolio(portfolio, path)
    return {"status": "ok", "removed": match}


def add_monitored_condition(
    ticker,
    condition,
    reason,
    status="waiting",
    action_if_met="rivaluta per possibile proposta",
    metadata=None,
    path=PORTFOLIO_FILE,
):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste. Inizializza prima il portafoglio.")
    item = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "ticker": ticker.strip().upper(),
        "status": status,
        "condition": condition,
        "reason": reason,
        "action_if_met": action_if_met,
        "metadata": metadata or {},
    }
    portfolio.setdefault("monitored_conditions", []).append(item)
    save_portfolio(portfolio, path)
    return item


def list_monitored_conditions(status=None, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        return []
    items = portfolio.get("monitored_conditions", [])
    if status:
        return [item for item in items if item.get("status") == status]
    return items


def update_monitored_condition(condition_id, status, note="", metadata=None, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste.")
    items = portfolio.setdefault("monitored_conditions", [])
    match = next((item for item in items if item.get("id") == condition_id), None)
    if not match:
        return {"status": "missing", "condition_id": condition_id}
    match["status"] = status
    match["updated_at"] = now_iso()
    if note:
        match.setdefault("notes", []).append({"created_at": now_iso(), "note": note})
    if metadata:
        match.setdefault("metadata", {}).update(metadata)
    save_portfolio(portfolio, path)
    return {"status": "ok", "condition": match}


def confirm_proposal(proposal_id, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste.")
    pending = portfolio.get("pending_proposals", [])
    match = next((item for item in pending if item["id"] == proposal_id), None)
    if not match:
        return {"status": "missing", "proposal_id": proposal_id}

    pending.remove(match)
    match["status"] = "confirmed"
    match["confirmed_at"] = now_iso()
    portfolio.setdefault("closed_proposals", []).append(match)

    if match["action"] == "add_to_watchlist":
        watchlist = portfolio.setdefault("watchlist", [])
        if not any(item.get("ticker") == match["ticker"] for item in watchlist):
            watchlist.append(
                {
                    "ticker": match["ticker"],
                    "name": match.get("metadata", {}).get("name", match["ticker"]),
                    "market": match.get("metadata", {}).get("market", ""),
                    "added_at": now_iso(),
                    "source": "confirmed_agent_proposal",
                }
            )
    elif match["action"] == "create_virtual_allocation":
        metadata = match.get("metadata", {})
        allocations = metadata.get("allocations", [])
        capital = float(metadata.get("capital", portfolio.get("cash", 0)))
        positions = []
        invested = 0.0
        watchlist = portfolio.setdefault("watchlist", [])
        for allocation in allocations:
            amount = float(allocation.get("allocated_amount", 0))
            invested += amount
            positions.append(
                {
                    "ticker": allocation["ticker"],
                    "name": allocation.get("name", allocation["ticker"]),
                    "market": allocation.get("market", ""),
                    "sector": allocation.get("sector", ""),
                    "entry_price": allocation.get("entry_price"),
                    "virtual_quantity": allocation.get("virtual_quantity"),
                    "allocated_amount": amount,
                    "allocation_pct": allocation.get("allocation_pct"),
                    "opened_at": now_iso(),
                    "status": "open",
                    "source": "confirmed_agent_allocation",
                    "reason": allocation.get("reason", ""),
                }
            )
            if not any(item.get("ticker") == allocation["ticker"] for item in watchlist):
                watchlist.append(
                    {
                        "ticker": allocation["ticker"],
                        "name": allocation.get("name", allocation["ticker"]),
                        "market": allocation.get("market", ""),
                        "added_at": now_iso(),
                        "source": "confirmed_agent_allocation",
                    }
                )
        portfolio["initial_capital"] = capital
        portfolio["positions"] = positions
        portfolio["cash"] = round(capital - invested, 2)
    elif match["action"] == "buy_virtual_position":
        metadata = match.get("metadata", {})
        amount = metadata.get("amount")
        entry_price = metadata.get("entry_price")
        quantity = None
        if amount is not None and entry_price:
            quantity = round(float(amount) / float(entry_price), 4)
            portfolio["cash"] = round(float(portfolio.get("cash", 0)) - float(amount), 2)
        portfolio.setdefault("positions", []).append(
            {
                "ticker": match["ticker"],
                "name": metadata.get("name", match["ticker"]),
                "market": metadata.get("market", ""),
                "sector": metadata.get("sector", ""),
                "entry_price": entry_price,
                "virtual_quantity": quantity,
                "allocated_amount": amount,
                "opened_at": now_iso(),
                "status": "open",
                "source": "confirmed_agent_buy_proposal",
                "reason": match.get("reason", ""),
            }
        )

    save_portfolio(portfolio, path)
    return {"status": "ok", "proposal": match, "portfolio": portfolio}


def reject_proposal(proposal_id, path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        raise RuntimeError("portfolio.json non esiste.")
    pending = portfolio.get("pending_proposals", [])
    match = next((item for item in pending if item["id"] == proposal_id), None)
    if not match:
        return {"status": "missing", "proposal_id": proposal_id}
    pending.remove(match)
    match["status"] = "rejected"
    match["rejected_at"] = now_iso()
    portfolio.setdefault("closed_proposals", []).append(match)
    save_portfolio(portfolio, path)
    return {"status": "ok", "proposal": match}
