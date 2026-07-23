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


def list_pending_proposals(path=PORTFOLIO_FILE):
    portfolio = load_portfolio(path)
    if portfolio is None:
        return []
    return portfolio.get("pending_proposals", [])


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
