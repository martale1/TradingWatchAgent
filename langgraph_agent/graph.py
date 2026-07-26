from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from finance_tools.commodity_scanner import scan_commodity_candidates
from finance_tools.mib30_scanner import scan_mib30_candidates
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.portfolio_store import portfolio_status_summary

from langgraph_agent.state import TradingGraphState


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(state: TradingGraphState, message: str) -> TradingGraphState:
    logs = list(state.get("logs", []))
    line = f"{_now()} [langgraph] {message}"
    logs.append(line)
    print(line, flush=True)
    return {"logs": logs}


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_operating_state(state: TradingGraphState) -> TradingGraphState:
    patch = _log(state, "Nodo stato: leggo portafoglio, performance e condizioni monitorate.")
    try:
        portfolio = portfolio_status_summary()
        performance = calculate_portfolio_performance(record_history=False)
        positions = portfolio.get("positions", []) or []
        waiting = [
            item
            for item in (portfolio.get("monitored_conditions", []) or [])
            if item.get("status") == "waiting"
        ]
        patch.update(
            {
                "portfolio": portfolio,
                "performance": performance,
                "mode": state.get("mode", "analysis"),
            }
        )
        patch.update(
            _log(
                {**state, **patch},
                "Stato pronto: "
                f"posizioni={len(positions)}, trigger_waiting={len(waiting)}, "
                f"cash={portfolio.get('cash', 'n/d')}, pnl={performance.get('total_pnl', 'n/d')}.",
            )
        )
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"load_operating_state: {exc}")
        patch.update({"errors": errors})
        patch.update(_log({**state, **patch}, f"Errore nodo stato: {exc}"))
    return patch


def scan_ftse_mib(state: TradingGraphState) -> TradingGraphState:
    limit = int(state.get("scan_limit", 5))
    universe_limit = state.get("universe_limit")
    patch = _log(
        state,
        f"Nodo scanner FTSE MIB: calcolo indicatori locali e score su universo="
        f"{universe_limit or 'completo'}, top={limit}.",
    )
    try:
        scan = scan_mib30_candidates(
            limit=limit,
            universe_limit=universe_limit,
            create_proposals=False,
            verbose=True,
        )
        patch["ftse_mib_scan"] = scan
        patch.update(
            _log(
                {**state, **patch},
                f"FTSE MIB completato: {scan.get('count', 0)} ok, "
                f"{len(scan.get('errors', []) or [])} errori, "
                f"{len(scan.get('candidates', []) or [])} candidati liquidi.",
            )
        )
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"scan_ftse_mib: {exc}")
        patch.update({"errors": errors})
        patch.update(_log({**state, **patch}, f"Errore scanner FTSE MIB: {exc}"))
    return patch


def scan_commodities(state: TradingGraphState) -> TradingGraphState:
    limit = int(state.get("scan_limit", 5))
    universe_limit = state.get("universe_limit")
    patch = _log(
        state,
        f"Nodo scanner Materie prime/ETC: calcolo indicatori locali e score su universo="
        f"{universe_limit or 'completo'}, top={limit}.",
    )
    try:
        scan = scan_commodity_candidates(
            limit=limit,
            universe_limit=universe_limit,
            verbose=True,
        )
        patch["commodity_scan"] = scan
        patch.update(
            _log(
                {**state, **patch},
                f"Materie prime completato: {scan.get('count', 0)} ok, "
                f"{len(scan.get('errors', []) or [])} errori, "
                f"{len(scan.get('candidates', []) or [])} candidati liquidi.",
            )
        )
    except Exception as exc:
        errors = list(state.get("errors", []))
        errors.append(f"scan_commodities: {exc}")
        patch.update({"errors": errors})
        patch.update(_log({**state, **patch}, f"Errore scanner Materie prime: {exc}"))
    return patch


def build_shortlist(state: TradingGraphState) -> TradingGraphState:
    patch = _log(
        state,
        "Nodo short-list: unisco candidati FTSE MIB e Materie prime, escludendo liquidita bassa.",
    )
    rows: list[dict[str, Any]] = []
    for market_key, market_label in [
        ("ftse_mib_scan", "FTSE MIB"),
        ("commodity_scan", "Materie prime/ETC"),
    ]:
        scan = state.get(market_key) or {}
        for item in scan.get("candidates", []) or []:
            if item.get("liquidity_ok") is False:
                patch.update(
                    _log(
                        {**state, **patch},
                        f"Escludo {item.get('ticker')} da {market_label}: liquidita bassa.",
                    )
                )
                continue
            rows.append({**item, "market_scope": market_label})

    rows.sort(key=lambda item: _as_number(item.get("score")), reverse=True)
    scan_limit = int(state.get("scan_limit", 5))
    shortlist = rows[:scan_limit]
    patch["shortlist"] = shortlist
    if shortlist:
        for index, item in enumerate(shortlist, start=1):
            reasons = "; ".join((item.get("reasons") or [])[:3]) or "nessun motivo tecnico forte"
            risks = "; ".join((item.get("risks") or [])[:2]) or "nessun rischio principale"
            patch.update(
                _log(
                    {**state, **patch},
                    f"Short-list #{index}: {item.get('ticker')} [{item.get('market_scope')}] "
                    f"score={item.get('score')} close={item.get('close')} oggi={item.get('change_1d_pct')}% | "
                    f"motivi={reasons} | rischi={risks}.",
                )
            )
    else:
        patch.update(_log({**state, **patch}, "Short-list vuota: nessun candidato liquido."))
    return patch


def plan_deep_analysis(state: TradingGraphState) -> TradingGraphState:
    patch = _log(
        state,
        "Nodo piano approfondimenti: Playwright viene pianificato solo per posizioni, trigger scattati o buy candidate.",
    )
    portfolio = state.get("portfolio") or {}
    positions = {item.get("ticker") for item in (portfolio.get("positions") or [])}
    met_conditions = [
        item
        for item in (portfolio.get("monitored_conditions") or [])
        if str(item.get("status", "")).lower() == "met"
    ]
    met_tickers = {item.get("ticker") for item in met_conditions}

    plan: list[dict[str, Any]] = []
    for item in state.get("shortlist", []) or []:
        ticker = item.get("ticker")
        score = _as_number(item.get("score"))
        scenario_state = str((item.get("metadata") or {}).get("scenario_state") or "").upper()
        is_buy_candidate = score >= 7 or scenario_state == "BUY_CANDIDATE"
        needs_deep = ticker in positions or ticker in met_tickers or is_buy_candidate
        reason = []
        if ticker in positions:
            reason.append("titolo gia in portafoglio")
        if ticker in met_tickers:
            reason.append("trigger monitorato scattato")
        if is_buy_candidate:
            reason.append(f"buy candidate tecnico score {score:g}")
        if needs_deep:
            plan.append(
                {
                    "ticker": ticker,
                    "market_scope": item.get("market_scope"),
                    "reason": "; ".join(reason),
                    "uses_playwright": True,
                }
            )
            patch.update(
                _log(
                    {**state, **patch},
                    f"Approfondimento Playwright pianificato per {ticker}: {'; '.join(reason)}.",
                )
            )
        else:
            patch.update(
                _log(
                    {**state, **patch},
                    f"Niente Playwright per {ticker}: candidato monitorabile ma non posizione/trigger/buy forte.",
                )
            )
    patch["deep_analysis_plan"] = plan
    return patch


def draft_decisions(state: TradingGraphState) -> TradingGraphState:
    patch = _log(state, "Nodo decisioni: creo decisioni preliminari senza applicare operazioni.")
    decisions: list[dict[str, Any]] = []
    for item in state.get("shortlist", []) or []:
        score = _as_number(item.get("score"))
        action = "monitor"
        if score >= 8 and item.get("liquidity_ok") is not False:
            action = "candidate_for_entry"
        decisions.append(
            {
                "ticker": item.get("ticker"),
                "market_scope": item.get("market_scope"),
                "action": action,
                "score": score,
                "close": item.get("close"),
                "reason": "; ".join((item.get("reasons") or [])[:4]),
                "risk": "; ".join((item.get("risks") or [])[:3]),
            }
        )
        patch.update(
            _log(
                {**state, **patch},
                f"Decisione preliminare {item.get('ticker')}: {action}, score={score:g}.",
            )
        )
    patch["decisions"] = decisions
    return patch


def finalize(state: TradingGraphState) -> TradingGraphState:
    patch = _log(state, "Nodo finale: preparo riepilogo sintetico del ciclo LangGraph.")
    lines = ["Autonomous Trading Agent - LangGraph prototype", ""]
    if state.get("errors"):
        lines.append("Errori:")
        lines.extend(f"- {item}" for item in state["errors"])
        lines.append("")
    lines.append("Decisioni preliminari:")
    for item in state.get("decisions", []) or []:
        lines.append(
            f"- {item['ticker']} [{item['market_scope']}]: {item['action']} "
            f"(score {item['score']:.0f}, close {item.get('close')})"
        )
    lines.append("")
    lines.append("Approfondimenti Playwright pianificati:")
    plan = state.get("deep_analysis_plan", []) or []
    if plan:
        lines.extend(f"- {item['ticker']}: {item['reason']}" for item in plan)
    else:
        lines.append("- nessuno")
    patch["final_summary"] = "\n".join(lines)
    return patch


def build_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(TradingGraphState)
    graph.add_node("load_operating_state", load_operating_state)
    graph.add_node("scan_ftse_mib", scan_ftse_mib)
    graph.add_node("scan_commodities", scan_commodities)
    graph.add_node("build_shortlist", build_shortlist)
    graph.add_node("plan_deep_analysis", plan_deep_analysis)
    graph.add_node("draft_decisions", draft_decisions)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("load_operating_state")
    graph.add_edge("load_operating_state", "scan_ftse_mib")
    graph.add_edge("scan_ftse_mib", "scan_commodities")
    graph.add_edge("scan_commodities", "build_shortlist")
    graph.add_edge("build_shortlist", "plan_deep_analysis")
    graph.add_edge("plan_deep_analysis", "draft_decisions")
    graph.add_edge("draft_decisions", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_langgraph_workflow(
    request: str = "monitor",
    scan_limit: int = 5,
    universe_limit: int | None = None,
) -> TradingGraphState:
    initial_state: TradingGraphState = {
        "request": request,
        "scan_limit": scan_limit,
        "universe_limit": universe_limit,
        "logs": [],
        "errors": [],
    }
    app = build_graph()
    return app.invoke(initial_state)


def state_to_json(state: TradingGraphState) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2, default=str)

