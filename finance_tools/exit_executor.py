from finance_tools.autonomy_settings import autonomous_action_allowed
from finance_tools.portfolio_store import (
    PORTFOLIO_FILE,
    add_position_action_proposal,
    confirm_proposal,
    load_portfolio,
)


EXIT_ACTIONS = {"sell_virtual_position", "reduce_virtual_position"}


def enforce_triggered_exits(exit_rows, path=PORTFOLIO_FILE, portfolio_id=None):
    """Apply the same hard-stop conditions reported as violated by the dashboard."""
    portfolio = load_portfolio(path)
    if portfolio is None:
        return {"status": "missing_portfolio", "decisions": [], "applied_count": 0}

    open_tickers = {
        str(item.get("ticker") or "").strip().upper()
        for item in portfolio.get("positions", [])
        if item.get("status") == "open"
    }
    pending_by_ticker = {
        str(item.get("ticker") or "").strip().upper(): item
        for item in portfolio.get("pending_proposals", [])
        if item.get("status") == "pending" and item.get("action") in EXIT_ACTIONS
    }
    decisions = []
    for row in exit_rows or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        current = row.get("current_price")
        stop = row.get("stop_level")
        try:
            breached = float(current) <= float(stop)
        except (TypeError, ValueError):
            breached = False
        if not ticker or ticker not in open_tickers or not breached:
            continue
        existing = pending_by_ticker.get(ticker)
        if existing:
            decisions.append({
                "ticker": ticker,
                "decision": "pending_exit_exists",
                "proposal_id": existing.get("id"),
                "current_price": current,
                "stop_level": stop,
            })
            continue

        reason = (
            f"Stop operativo violato: prezzo {float(current):.4f} <= livello di uscita "
            f"{float(stop):.4f}. Vendita totale automatica per protezione del capitale."
        )
        proposal = add_position_action_proposal(
            ticker=ticker,
            action_type="sell",
            percent=100,
            reference_price=float(current),
            reason=reason,
            metadata={
                "source": "deterministic_exit_stop",
                "trigger_type": "hard_stop",
                "stop_level": float(stop),
                "observed_price": float(current),
                "exit_status": row.get("status"),
            },
            path=path,
        )
        allowed, autonomy_mode = autonomous_action_allowed(
            proposal.get("action"), portfolio_id=portfolio_id
        )
        result = confirm_proposal(proposal["id"], path=path) if allowed else None
        applied = bool(result and result.get("status") == "ok")
        decisions.append({
            "ticker": ticker,
            "decision": "sold" if applied else ("apply_failed" if allowed else "pending_confirmation"),
            "proposal_id": proposal.get("id"),
            "autonomy_mode": autonomy_mode,
            "current_price": current,
            "stop_level": stop,
            "applied": applied,
            "result_status": (result or {}).get("status"),
        })
        pending_by_ticker[ticker] = proposal

    return {
        "status": "ok",
        "decisions": decisions,
        "applied_count": sum(1 for item in decisions if item.get("applied")),
        "pending_count": sum(1 for item in decisions if item.get("decision") == "pending_confirmation"),
    }
