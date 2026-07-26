from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
from datetime import datetime
from typing import Any

from finance_tools.commodity_scanner import scan_commodity_candidates
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai
from finance_tools.mib30_scanner import scan_mib30_candidates
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.portfolio_store import (
    add_buy_proposal,
    add_position_action_proposal,
    confirm_proposal,
    portfolio_status_summary,
    update_monitored_condition,
)

from langgraph_agent.state import TradingGraphState


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _log(state: TradingGraphState, message: str) -> TradingGraphState:
    logs = list(state.get("logs", []))
    run_id = state.get("run_id", "no-run-id")
    line = f"{_now()} [run {run_id}] [langgraph] {message}"
    logs.append(line)
    print(line, flush=True)
    return {"logs": logs}


def _capture_tool_output(func):
    """Run a noisy local tool and keep raw prints out of the graph timeline."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = func()
    captured_lines = [line.strip() for line in buffer.getvalue().splitlines() if line.strip()]
    return result, captured_lines


def _log_captured_tool_output(
    state: TradingGraphState,
    patch: TradingGraphState,
    step: str,
    market_label: str,
    captured_lines: list[str],
) -> None:
    if not captured_lines:
        patch.update(
            _log(
                {**state, **patch},
                f"{step} tool_output | market={market_label} | nessuna riga interna catturata.",
            )
        )
        return
    patch.update(
        _log(
            {**state, **patch},
            f"{step} tool_output | market={market_label} | "
            f"{len(captured_lines)} righe interne catturate e normalizzate nei dettagli scan.",
        )
    )


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_liquid(item: dict[str, Any]) -> bool:
    return item.get("liquidity_ok") is not False


def _open_positions_by_ticker(portfolio: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for item in portfolio.get("positions", []) or []:
        if item.get("status", "open") == "open":
            rows[str(item.get("ticker", "")).strip().upper()] = item
    return rows


def _pending_tickers(portfolio: dict[str, Any]) -> set[str]:
    tickers = set()
    for item in (portfolio.get("pending_buy_proposals") or []) + (
        portfolio.get("pending_other_proposals") or []
    ):
        ticker = str(item.get("ticker", "")).strip().upper()
        if ticker:
            tickers.add(ticker)
    return tickers


def _performance_by_ticker(performance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("ticker", "")).strip().upper(): item
        for item in performance.get("positions", []) or []
        if item.get("ticker")
    }


def _deep_report_confirms_buy(report: str) -> bool:
    text = (report or "").lower()
    negative_markers = [
        "non comprare",
        "evitare acquisti",
        "evitare ingresso",
        "sell",
        "vendere",
        "rischio elevato",
    ]
    positive_markers = [
        "buy_candidate",
        "buy candidate",
        "ingresso",
        "comprare",
        "acquisto",
        "breakout",
        "supporto confermato",
    ]
    if any(marker in text for marker in negative_markers):
        return False
    return any(marker in text for marker in positive_markers)


def _has_position_action_today(position: dict[str, Any], action_prefix: str) -> bool:
    today = datetime.now().date()
    for item in position.get("position_actions", []) or []:
        created_at = str(item.get("created_at", ""))
        if not created_at.startswith(today.isoformat()):
            continue
        action = str(item.get("action", ""))
        if action.startswith(action_prefix):
            return True
    return False


def _safe_amount(cash: float, pct: float) -> float:
    amount = round(cash * pct / 100.0, 2)
    return max(0.0, amount)


def _scan_decision_label(item: dict[str, Any], candidates: list[dict[str, Any]]) -> str:
    if not _is_liquid(item):
        return "candidate=no reason=liquidita_bassa"
    candidate_tickers = {candidate.get("ticker") for candidate in candidates}
    if item.get("ticker") in candidate_tickers:
        return "candidate=yes reason=score_top_liquido"
    return "candidate=no reason=score_fuori_shortlist"


def _log_scan_rows(
    state: TradingGraphState,
    patch: TradingGraphState,
    market_label: str,
    scan: dict[str, Any],
) -> None:
    candidates = scan.get("candidates", []) or []
    rows = scan.get("scanned_rows", []) or []
    for index, item in enumerate(rows, start=1):
        reasons = "; ".join((item.get("reasons") or [])[:3]) or "nessun segnale forte"
        risks = "; ".join((item.get("risks") or [])[:2]) or "nessun rischio principale"
        liquidity = "ok" if _is_liquid(item) else "bassa"
        decision = _scan_decision_label(item, candidates)
        patch.update(
            _log(
                {**state, **patch},
                f"STEP scan detail | market={market_label} | "
                f"{index}/{len(rows)} ticker={item.get('ticker')} "
                f"score={item.get('score')} close={item.get('close')} "
                f"oggi={item.get('change_1d_pct')}% liquidity={liquidity} "
                f"{decision} | motivi={reasons} | rischi={risks}",
            )
        )


def load_operating_state(state: TradingGraphState) -> TradingGraphState:
    patch = _log(
        state,
        "STEP 1/8 load_operating_state START | leggo portafoglio, performance, posizioni e trigger.",
    )
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
                "STEP 1/8 load_operating_state END | "
                f"posizioni={len(positions)}, trigger_waiting={len(waiting)}, "
                f"cash={portfolio.get('cash', 'n/d')}, pnl={performance.get('total_pnl', 'n/d')} | "
                f"modalita={'operativa_virtuale' if state.get('apply_virtual', True) else 'dry_run'}.",
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
        f"STEP 2/8 scan_ftse_mib START | market=FTSE_MIB | "
        f"calcolo locale Yahoo+indicatori | universo={universe_limit or 'completo'} | top={limit} | "
        "OpenAI=no Playwright=no.",
    )
    try:
        scan, captured_lines = _capture_tool_output(
            lambda: scan_mib30_candidates(
                limit=limit,
                universe_limit=universe_limit,
                create_proposals=False,
                verbose=False,
            )
        )
        _log_captured_tool_output(state, patch, "STEP 2/8", "FTSE_MIB", captured_lines)
        patch["ftse_mib_scan"] = scan
        _log_scan_rows(state, patch, "FTSE_MIB", scan)
        patch.update(
            _log(
                {**state, **patch},
                f"STEP 2/8 scan_ftse_mib END | market=FTSE_MIB | {scan.get('count', 0)} ok, "
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
        f"STEP 3/8 scan_commodities START | market=COMMODITIES_ETC | "
        f"calcolo locale Yahoo+indicatori | universo={universe_limit or 'completo'} | top={limit} | "
        "OpenAI=no Playwright=no.",
    )
    try:
        scan, captured_lines = _capture_tool_output(
            lambda: scan_commodity_candidates(
                limit=limit,
                universe_limit=universe_limit,
                verbose=False,
            )
        )
        _log_captured_tool_output(state, patch, "STEP 3/8", "COMMODITIES_ETC", captured_lines)
        patch["commodity_scan"] = scan
        _log_scan_rows(state, patch, "COMMODITIES_ETC", scan)
        patch.update(
            _log(
                {**state, **patch},
                f"STEP 3/8 scan_commodities END | market=COMMODITIES_ETC | {scan.get('count', 0)} ok, "
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
        "STEP 4/8 build_shortlist START | unisco candidati FTSE MIB + Materie prime, filtro hard liquidita.",
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
                    f"STEP 4/8 shortlist item #{index} | ticker={item.get('ticker')} "
                    f"market={item.get('market_scope')} "
                    f"score={item.get('score')} close={item.get('close')} oggi={item.get('change_1d_pct')}% | "
                    f"motivi={reasons} | rischi={risks}.",
                )
            )
    else:
        patch.update(_log({**state, **patch}, "Short-list vuota: nessun candidato liquido."))
    patch.update(
        _log(
            {**state, **patch},
            f"STEP 4/8 build_shortlist END | shortlist_size={len(shortlist)}.",
        )
    )
    return patch


def plan_deep_analysis(state: TradingGraphState) -> TradingGraphState:
    patch = _log(
        state,
        "STEP 5/8 plan_deep_analysis START | policy Playwright: solo posizioni, trigger scattati, buy candidate o richiesta esplicita.",
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
                    f"STEP 5/8 playwright_plan=yes | ticker={ticker} market={item.get('market_scope')} "
                    f"reason={' ; '.join(reason)}.",
                )
            )
        else:
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 5/8 playwright_plan=no | ticker={ticker} market={item.get('market_scope')} "
                    "reason=non_posizione_non_trigger_non_buy_forte.",
                )
            )
    patch["deep_analysis_plan"] = plan
    patch.update(
        _log(
            {**state, **patch},
            f"STEP 5/8 plan_deep_analysis END | playwright_items={len(plan)}.",
        )
    )
    return patch


def run_deep_analysis(state: TradingGraphState) -> TradingGraphState:
    use_playwright = bool(state.get("use_playwright", True))
    patch = _log(
        state,
        "STEP 6/8 run_deep_analysis START | "
        f"use_playwright={use_playwright} | eseguo Playwright solo sui titoli pianificati.",
    )
    results: list[dict[str, Any]] = []
    for item in state.get("deep_analysis_plan", []) or []:
        ticker = item.get("ticker")
        reason = item.get("reason", "n/d")
        if not use_playwright:
            results.append({**item, "ticker": ticker, "status": "skipped", "report": ""})
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 6/8 playwright SKIP | ticker={ticker} | motivo_approfondimento={reason}.",
                )
            )
            continue
        patch.update(
            _log(
                {**state, **patch},
                f"STEP 6/8 playwright START | ticker={ticker} | motivo_approfondimento={reason}.",
            )
        )
        try:
            result, captured_lines = _capture_tool_output(
                lambda ticker=ticker: confirm_candidate_with_chart_ai(
                    ticker=ticker,
                    no_telegram=True,
                )
            )
            _log_captured_tool_output(state, patch, "STEP 6/8", f"PLAYWRIGHT {ticker}", captured_lines)
            report_len = len(result.get("report") or "")
            results.append({**item, **result})
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 6/8 playwright END | ticker={ticker} status={result.get('status')} "
                    f"analysis_file={result.get('analysis_file')} report_chars={report_len}.",
                )
            )
        except Exception as exc:
            errors = list(state.get("errors", [])) + list(patch.get("errors", []))
            errors.append(f"run_deep_analysis {ticker}: {exc}")
            patch["errors"] = errors
            results.append({**item, "ticker": ticker, "status": "error", "error": str(exc)})
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 6/8 playwright ERROR | ticker={ticker} | {exc}.",
                )
            )
    patch["deep_analysis_results"] = results
    patch.update(
        _log(
            {**state, **patch},
            f"STEP 6/8 run_deep_analysis END | completati={len(results)}.",
        )
    )
    return patch


def apply_virtual_decisions(state: TradingGraphState) -> TradingGraphState:
    apply_virtual = bool(state.get("apply_virtual", True))
    max_pct = float(state.get("max_auto_trade_pct", 25.0) or 25.0)
    patch = _log(
        state,
        "STEP 7/8 apply_virtual_decisions START | "
        f"apply_virtual={apply_virtual} max_trade_pct_cash={max_pct}.",
    )
    decisions: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    created: list[dict[str, Any]] = []
    portfolio = state.get("portfolio") or {}
    performance = state.get("performance") or {}
    positions = _open_positions_by_ticker(portfolio)
    pending_tickers = _pending_tickers(portfolio)
    perf_rows = _performance_by_ticker(performance)
    deep_by_ticker = {
        str(item.get("ticker", "")).strip().upper(): item
        for item in state.get("deep_analysis_results", []) or []
        if item.get("ticker")
    }
    cash = _as_number(portfolio.get("cash"))

    for ticker, perf in perf_rows.items():
        position = positions.get(ticker, {})
        pnl_pct = _as_number(perf.get("pnl_pct"))
        price = _as_number(perf.get("current_price") or perf.get("entry_price"))
        action = "hold"
        percent = 0.0
        if pnl_pct <= -6 and not _has_position_action_today(position, "sell"):
            action = "sell"
            percent = 100.0
        elif pnl_pct <= -3 and not _has_position_action_today(position, "reduce"):
            action = "reduce"
            percent = 50.0
        elif pnl_pct >= 5 and not _has_position_action_today(position, "reduce"):
            action = "reduce"
            percent = 30.0

        reason = (
            f"Gestione autonoma posizione: P/L {pnl_pct:.2f}% su {ticker}. "
            "Regole: <=-6% vendita, <=-3% riduzione 50%, >=5% profit protect 30%."
        )
        decisions.append(
            {
                "ticker": ticker,
                "market_scope": "portfolio",
                "action": action,
                "score": None,
                "close": price,
                "reason": reason,
                "risk": "",
                "applied": False,
            }
        )
        patch.update(
            _log(
                {**state, **patch},
                f"STEP 7/8 portfolio decision | ticker={ticker} pnl_pct={pnl_pct:.2f} "
                f"action={action} percent={percent:g} applied_pending={apply_virtual and action != 'hold'}.",
            )
        )
        if apply_virtual and action in {"sell", "reduce"} and ticker not in pending_tickers:
            proposal = add_position_action_proposal(
                ticker=ticker,
                action_type=action,
                reason=reason,
                percent=percent,
                reference_price=price,
                metadata={"source": "langgraph_autonomous", "run_id": state.get("run_id")},
            )
            result = confirm_proposal(proposal["id"])
            created.append(proposal)
            applied.append(
                {
                    "ticker": ticker,
                    "action": proposal["action"],
                    "proposal_id": proposal["id"],
                    "status": result.get("status"),
                    "reason": reason,
                }
            )
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 7/8 portfolio APPLY | ticker={ticker} proposal={proposal['id']} "
                    f"action={proposal['action']} status={result.get('status')}.",
                )
            )

    for item in state.get("shortlist", []) or []:
        ticker = str(item.get("ticker", "")).strip().upper()
        score = _as_number(item.get("score"))
        close = _as_number(item.get("close"))
        action = "monitor"
        if score >= 8 and item.get("liquidity_ok") is not False:
            action = "candidate_for_entry"
        deep = deep_by_ticker.get(ticker, {})
        deep_status = deep.get("status", "not_required")
        deep_confirms = _deep_report_confirms_buy(deep.get("report", ""))
        already_open = ticker in positions
        already_pending = ticker in pending_tickers
        should_buy = (
            action == "candidate_for_entry"
            and not already_open
            and not already_pending
            and close > 0
            and deep_status == "ok"
            and deep_confirms
        )
        reason = "; ".join((item.get("reasons") or [])[:4])
        risk = "; ".join((item.get("risks") or [])[:3])
        amount = _safe_amount(cash, max_pct)
        decisions.append(
            {
                "ticker": ticker,
                "market_scope": item.get("market_scope"),
                "action": action,
                "score": score,
                "close": close,
                "reason": reason,
                "risk": risk,
                "deep_status": deep_status,
                "deep_confirms_buy": deep_confirms,
                "applied": False,
            }
        )
        patch.update(
            _log(
                {**state, **patch},
                f"STEP 7/8 entry decision | ticker={ticker} market={item.get('market_scope')} "
                f"action={action} score={score:g} liquid={_is_liquid(item)} "
                f"deep_status={deep_status} deep_confirms_buy={deep_confirms} "
                f"already_open={already_open} already_pending={already_pending} "
                f"cash_before={cash:.2f} amount_candidate={amount:.2f} "
                f"applied_pending={apply_virtual and should_buy}.",
            )
        )
        if apply_virtual and should_buy and amount >= 500:
            proposal = add_buy_proposal(
                ticker=ticker,
                reason=(
                    f"BUY autonomo LangGraph: score {score:g}, liquido, "
                    f"conferma Playwright ok. Motivi: {reason}. Rischi: {risk or 'n/d'}."
                ),
                amount=amount,
                entry_price=close,
                metadata={
                    "source": "langgraph_autonomous",
                    "run_id": state.get("run_id"),
                    "market_scope": item.get("market_scope"),
                    "score": score,
                    "deep_analysis_file": deep.get("analysis_file"),
                },
            )
            result = confirm_proposal(proposal["id"])
            cash = max(0.0, cash - amount)
            created.append(proposal)
            applied.append(
                {
                    "ticker": ticker,
                    "action": proposal["action"],
                    "proposal_id": proposal["id"],
                    "status": result.get("status"),
                    "amount": amount,
                    "entry_price": close,
                }
            )
            for condition in (portfolio.get("monitored_conditions") or []):
                if str(condition.get("ticker", "")).strip().upper() == ticker and condition.get("status") in {"waiting", "met"}:
                    update_monitored_condition(
                        condition.get("id"),
                        "applied",
                        note=f"Operazione autonoma applicata dal run LangGraph {state.get('run_id')}: {proposal['id']}.",
                        metadata={"proposal_id": proposal["id"]},
                    )
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 7/8 entry APPLY | ticker={ticker} proposal={proposal['id']} "
                    f"amount={amount:.2f} entry={close} status={result.get('status')} cash_after={cash:.2f}.",
                )
            )
        elif apply_virtual and should_buy and amount < 500:
            patch.update(
                _log(
                    {**state, **patch},
                    f"STEP 7/8 entry SKIP | ticker={ticker} reason=amount_sotto_minimo amount={amount:.2f}.",
                )
            )

    patch["decisions"] = decisions
    patch["applied_actions"] = applied
    patch["created_proposals"] = created
    try:
        patch["portfolio"] = portfolio_status_summary()
        patch["performance"] = calculate_portfolio_performance(record_history=False)
    except Exception as exc:
        errors = list(state.get("errors", [])) + list(patch.get("errors", []))
        errors.append(f"refresh_after_apply: {exc}")
        patch["errors"] = errors
    patch.update(
        _log(
            {**state, **patch},
            f"STEP 7/8 apply_virtual_decisions END | decisions={len(decisions)} "
            f"proposals_created={len(created)} trade_applicati={len(applied)}.",
        )
    )
    return patch


def finalize(state: TradingGraphState) -> TradingGraphState:
    patch = _log(
        state,
        "STEP 8/8 finalize START | preparo riepilogo sintetico del ciclo LangGraph.",
    )
    lines = ["Autonomous Trading Agent - LangGraph workflow", ""]
    lines.append(f"Run ID: {state.get('run_id', 'n/d')}")
    lines.append(
        "Modalita: operativa virtuale"
        if state.get("apply_virtual", True)
        else "Modalita: dry-run, nessuna operazione applicata"
    )
    lines.append("")
    if state.get("errors"):
        lines.append("Errori:")
        lines.extend(f"- {item}" for item in state["errors"])
        lines.append("")
    lines.append("Decisioni preliminari:")
    for item in state.get("decisions", []) or []:
        score = item.get("score")
        score_text = f"{score:.0f}" if isinstance(score, (int, float)) else "n/d"
        lines.append(
            f"- {item['ticker']} [{item['market_scope']}]: {item['action']} "
            f"(score {score_text}, close {item.get('close')})"
        )
    applied = state.get("applied_actions", []) or []
    lines.append("")
    lines.append("Operazioni virtuali applicate:")
    if applied:
        for item in applied:
            detail = f" {item.get('amount')}" if item.get("amount") is not None else ""
            lines.append(
                f"- {item.get('ticker')}: {item.get('action')} proposal={item.get('proposal_id')} "
                f"status={item.get('status')}{detail}"
            )
    else:
        lines.append("- nessuna")
    lines.append("")
    lines.append("Approfondimenti Playwright pianificati:")
    plan = state.get("deep_analysis_plan", []) or []
    if plan:
        lines.extend(f"- {item['ticker']}: {item['reason']}" for item in plan)
    else:
        lines.append("- nessuno")
    patch["final_summary"] = "\n".join(lines)
    patch.update(
        _log(
            {**state, **patch},
            "STEP 8/8 finalize END | ciclo completato.",
        )
    )
    return patch


def build_graph():
    from langgraph.graph import END, StateGraph

    graph = StateGraph(TradingGraphState)
    graph.add_node("load_operating_state", load_operating_state)
    graph.add_node("scan_ftse_mib", scan_ftse_mib)
    graph.add_node("scan_commodities", scan_commodities)
    graph.add_node("build_shortlist", build_shortlist)
    graph.add_node("plan_deep_analysis", plan_deep_analysis)
    graph.add_node("run_deep_analysis", run_deep_analysis)
    graph.add_node("apply_virtual_decisions", apply_virtual_decisions)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("load_operating_state")
    graph.add_edge("load_operating_state", "scan_ftse_mib")
    graph.add_edge("scan_ftse_mib", "scan_commodities")
    graph.add_edge("scan_commodities", "build_shortlist")
    graph.add_edge("build_shortlist", "plan_deep_analysis")
    graph.add_edge("plan_deep_analysis", "run_deep_analysis")
    graph.add_edge("run_deep_analysis", "apply_virtual_decisions")
    graph.add_edge("apply_virtual_decisions", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


def run_langgraph_workflow(
    request: str = "monitor",
    scan_limit: int = 5,
    universe_limit: int | None = None,
    apply_virtual: bool = True,
    use_playwright: bool = True,
    max_auto_trade_pct: float = 25.0,
) -> TradingGraphState:
    initial_state: TradingGraphState = {
        "run_id": _new_run_id(),
        "request": request,
        "scan_limit": scan_limit,
        "universe_limit": universe_limit,
        "apply_virtual": apply_virtual,
        "use_playwright": use_playwright,
        "max_auto_trade_pct": max_auto_trade_pct,
        "logs": [],
        "errors": [],
    }
    app = build_graph()
    return app.invoke(initial_state)


def state_to_json(state: TradingGraphState) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2, default=str)
