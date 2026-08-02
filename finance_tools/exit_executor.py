from finance_tools.autonomy_settings import autonomous_action_allowed
from finance_tools.portfolio_store import (
    PORTFOLIO_FILE,
    add_position_action_proposal,
    confirm_proposal,
    load_portfolio,
    now_iso,
)


EXIT_ACTIONS = {"sell_virtual_position", "reduce_virtual_position"}


def enforce_triggered_exits(exit_rows, path=PORTFOLIO_FILE, portfolio_id=None):
    """Execute the explicit stop and take-profit policies shown by the dashboard."""
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
    completed_trigger_keys = {
        (
            str(item.get("ticker") or "").strip().upper(),
            str((item.get("metadata") or {}).get("source") or ""),
            str((item.get("metadata") or {}).get("trigger_level") or ""),
        )
        for item in portfolio.get("closed_proposals", [])
        if item.get("status") == "confirmed" and item.get("action") in EXIT_ACTIONS
    }
    decisions = []
    for row in exit_rows or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        current = row.get("current_price")
        stop = row.get("stop_level")
        stop_action = row.get("stop_action_code")
        target = row.get("take_profit_level")
        target_action = row.get("take_profit_action_code")
        try:
            stop_breached = float(current) <= float(stop)
        except (TypeError, ValueError):
            stop_breached = False
        try:
            target_reached = float(current) >= float(target)
        except (TypeError, ValueError):
            target_reached = False
        if not ticker or ticker not in open_tickers:
            continue
        if stop_breached and stop_action == "sell_all":
            action_type = "sell"
            percent = 100.0
            source = "deterministic_exit_stop"
            trigger_type = "hard_stop"
            trigger_level = float(stop)
            reason = (
                f"Stop operativo violato: prezzo {float(current):.4f} <= livello di uscita "
                f"{trigger_level:.4f}. Vendita totale automatica per protezione del capitale."
            )
        elif target_reached and target_action == "reduce_position" and row.get("status") == "TAKE PROFIT":
            action_type = "reduce"
            percent = float(row.get("take_profit_percent") or 30.0)
            source = "deterministic_take_profit"
            trigger_type = "take_profit"
            trigger_level = float(target)
            reason = (
                f"Take profit raggiunto: prezzo {float(current):.4f} >= target {trigger_level:.4f}. "
                f"Vendita parziale automatica del {percent:.0f}%."
            )
        else:
            continue
        trigger_key = (ticker, source, str(trigger_level))
        if trigger_key in completed_trigger_keys:
            decisions.append({
                "ticker": ticker,
                "decision": "trigger_already_executed",
                "trigger_type": trigger_type,
                "trigger_level": trigger_level,
            })
            continue
        existing = pending_by_ticker.get(ticker)
        if existing:
            decisions.append({
                "ticker": ticker,
                "decision": "pending_exit_exists",
                "proposal_id": existing.get("id"),
                "current_price": current,
                "trigger_type": trigger_type,
                "trigger_level": trigger_level,
            })
            continue
        proposal = add_position_action_proposal(
            ticker=ticker,
            action_type=action_type,
            percent=percent,
            reference_price=float(current),
            reason=reason,
            metadata={
                "source": source,
                "trigger_type": trigger_type,
                "action_policy": stop_action if action_type == "sell" else target_action,
                "trigger_level": trigger_level,
                "stop_level": float(stop) if stop is not None else None,
                "take_profit_level": float(target) if target is not None else None,
                "observed_price": float(current),
                "exit_status": row.get("status"),
                "action_audit_snapshot": {
                    "schema_version": 1,
                    "captured_at": row.get("price_as_of") or now_iso(),
                    "decision_kind": "deterministic_trigger",
                    "source": source,
                    "action": "sell_all" if action_type == "sell" else "reduce_position",
                    "percent": percent,
                    "trigger_type": trigger_type,
                    "trigger_level": trigger_level,
                    "observed_price": float(current),
                    "comparison": "price_lte_trigger" if action_type == "sell" else "price_gte_trigger",
                    "condition_met": True,
                    "rule": reason,
                    "audit_complete": True,
                },
            },
            path=path,
        )
        allowed, autonomy_mode = autonomous_action_allowed(
            proposal.get("action"), portfolio_id=portfolio_id
        )
        result = confirm_proposal(proposal["id"], path=path, confirmation_context="automatic") if allowed else None
        applied = bool(result and result.get("status") == "ok")
        decisions.append({
            "ticker": ticker,
            "decision": ("sold" if action_type == "sell" else "reduced") if applied else ("apply_failed" if allowed else "pending_confirmation"),
            "proposal_id": proposal.get("id"),
            "autonomy_mode": autonomy_mode,
            "current_price": current,
            "trigger_type": trigger_type,
            "trigger_level": trigger_level,
            "percent": percent,
            "applied": applied,
            "result_status": (result or {}).get("status"),
        })
        pending_by_ticker[ticker] = proposal
        if applied:
            completed_trigger_keys.add(trigger_key)

    return {
        "status": "ok",
        "decisions": decisions,
        "applied_count": sum(1 for item in decisions if item.get("applied")),
        "pending_count": sum(1 for item in decisions if item.get("decision") == "pending_confirmation"),
    }
