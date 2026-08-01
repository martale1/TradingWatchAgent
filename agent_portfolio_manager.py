import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from agents import Agent, ModelSettings, Runner, function_tool

from finance_tools.chart_tool import generate_chart_context_json
from finance_tools.autonomy_settings import autonomous_action_allowed, load_autonomy_settings
from finance_tools.commodity_scanner import load_commodity_tickers_json, scan_commodity_candidates_json
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai
from finance_tools.etf_scanner import load_etf_tickers_json, scan_etf_candidates_json
from finance_tools.exit_executor import enforce_triggered_exits
from finance_tools.exit_view import build_exit_conditions
from finance_tools.mib30_scanner import propose_virtual_allocation_json, scan_mib30_candidates_json
from finance_tools.monitoring_rules import (
    ensure_candidate_conditions,
    evaluate_monitored_entry_scenarios,
    invalidate_illiquid_monitored_conditions,
)
from finance_tools.news_tool import get_news_report
from finance_tools.news_notifications import send_relevant_news_alerts
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.performance_tool import calculate_portfolio_performance_json
from finance_tools.portfolio_deep_analysis import run_deep_portfolio_analysis_json
from finance_tools.agent_run_state import mark_agent_run_completed, mark_agent_run_started
from finance_tools.portfolio_store import (
    add_buy_proposal,
    add_monitored_condition,
    add_position_action_proposal,
    add_watchlist_item,
    confirm_proposal as confirm_portfolio_proposal,
    init_portfolio,
    list_monitored_conditions,
    list_pending_proposals,
    list_watchlist as list_portfolio_watchlist,
    load_portfolio as load_portfolio_file,
    portfolio_status_summary,
    reject_proposal as reject_portfolio_proposal,
    remove_watchlist_item,
    save_portfolio as save_portfolio_file,
    update_portfolio_capital,
    update_monitored_condition,
)
from finance_tools.ticker_resolver import resolve_ticker, resolve_ticker_context
from finance_tools.telegram_tool import (
    send_all_portfolios_summary,
    send_monitoring_summary,
    send_performance_summary,
    should_send_monitoring_summary,
)
from finance_tools.token_usage import record_token_usage
from finance_tools.risk_manager import execution_key
from finance_tools.shared_market_analysis import run_shared_portfolio_evaluation
from finance_tools.portfolio_registry import list_portfolios


DEFAULT_MODEL = os.getenv("OPENAI_AGENT_MODEL", "gpt-5-mini")
DEFAULT_MAX_TURNS = int(os.getenv("OPENAI_AGENT_MAX_TURNS", "24"))
DEFAULT_PERIODIC_MAX_TURNS = int(os.getenv("OPENAI_PERIODIC_MAX_TURNS", "24"))
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("OPENAI_AGENT_MAX_OUTPUT_TOKENS", "6000"))
DEFAULT_PERIODIC_CONDITION_LIMIT = int(os.getenv("OPENAI_PERIODIC_CONDITION_LIMIT", "8"))
DEFAULT_MONITOR_INTERVAL_MINUTES = int(os.getenv("MONITOR_INTERVAL_MINUTES", "30"))
DEFAULT_MAX_AUTO_TRADE_PCT = float(os.getenv("MAX_AUTO_TRADE_PCT", "25"))
DEFAULT_MAX_COMMODITY_ALLOCATION_PCT = float(os.getenv("MAX_COMMODITY_ALLOCATION_PCT", "20"))
AUTO_ENTRY_DECISION_ACTION = "auto_entry_decision"


ENTRY_SCENARIOS_GUIDE = (
    "Modella sempre gli ingressi con uno di questi scenari, dichiarandolo nella condizione e nella motivazione. "
    "SCENARIO BREAKOUT: ingresso solo su chiusura sopra resistenza/trigger con volumi almeno in recupero o sopra media; "
    "stop/invalidazione sotto il supporto o sotto il livello rotto; e utile quando vuoi conferma di forza. "
    "SCENARIO PULLBACK_SUPPORTO: ingresso vicino al supporto solo se il supporto tiene e compare reazione positiva "
    "(candela di rimbalzo, tenuta intraday/close sopra supporto, momentum che smette di peggiorare, volumi non contrari); "
    "stop stretto sotto supporto; target iniziale verso resistenza/trigger breakout. "
    "Non considerare il semplice arrivo vicino al supporto come buy automatico: serve evidenza di tenuta/rimbalzo e news non negative. "
)


class TimestampedStream:
    def __init__(self, stream):
        self.stream = stream
        self._buffer = ""
        self._tradingwatch_timestamped = True

    def write(self, text):
        if not text:
            return 0
        text = str(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write_line(line, newline=True)
        return len(text)

    def flush(self):
        if self._buffer:
            self._write_line(self._buffer, newline=False)
            self._buffer = ""
        self.stream.flush()

    def _write_line(self, line, newline=True):
        suffix = "\n" if newline else ""
        if line.strip():
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.stream.write(f"{timestamp} {line}{suffix}")
        else:
            self.stream.write(suffix)

    def __getattr__(self, name):
        return getattr(self.stream, name)


def configure_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

    if os.getenv("TRADINGWATCH_TIMESTAMP_LOGS", "0") == "1":
        if not getattr(sys.stdout, "_tradingwatch_timestamped", False):
            sys.stdout = TimestampedStream(sys.stdout)
        if not getattr(sys.stderr, "_tradingwatch_timestamped", False):
            sys.stderr = TimestampedStream(sys.stderr)


def _open_position_tickers(portfolio):
    return {
        str(item.get("ticker", "")).strip().upper()
        for item in (portfolio or {}).get("positions", [])
        if item.get("status") == "open"
    }


def _pending_buy_tickers(portfolio):
    return {
        str(item.get("ticker", "")).strip().upper()
        for item in (portfolio or {}).get("pending_proposals", [])
        if item.get("status") == "pending" and item.get("action") == "buy_virtual_position"
    }


def _condition_best_scenario(condition):
    metadata = condition.get("metadata", {}) or {}
    scenarios = metadata.get("entry_scenarios") or []
    ranked_states = {
        "BUY_CANDIDATE": 50,
        "TRIGGER_MET": 45,
        "CONFIRMED": 40,
        "CONFIRMING": 35,
        "NEAR_TRIGGER": 25,
        "WAIT": 10,
    }
    if scenarios:
        return max(
            scenarios,
            key=lambda item: ranked_states.get(str(item.get("state") or "").upper(), 0),
        )
    return {}


def _condition_reference_values(condition):
    metadata = condition.get("metadata", {}) or {}
    scenario = _condition_best_scenario(condition)
    price = (
        metadata.get("current_price")
        or metadata.get("last_price")
        or scenario.get("last_price")
        or metadata.get("close")
    )
    trigger = metadata.get("trigger_price") or scenario.get("trigger") or metadata.get("resistance_10")
    volume_ratio = (
        metadata.get("volume_ratio_ma10")
        or metadata.get("volume_ratio")
        or scenario.get("last_volume_ratio")
    )
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    try:
        trigger = float(trigger) if trigger is not None else None
    except (TypeError, ValueError):
        trigger = None
    try:
        volume_ratio = float(volume_ratio) if volume_ratio is not None else None
    except (TypeError, ValueError):
        volume_ratio = None
    return scenario, price, trigger, volume_ratio


def _record_auto_entry_decision(condition, decision, reason, status="logged", metadata=None):
    portfolio = load_portfolio_file()
    if portfolio is None:
        return None
    now_text = datetime.now().replace(microsecond=0).isoformat()
    condition_id = condition.get("id")
    ticker = str(condition.get("ticker", "")).strip().upper()
    decision_key = f"{condition_id}:{decision}"
    entry = {
        "id": f"auto-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
        "created_at": now_text,
        "confirmed_at": now_text,
        "status": status,
        "action": AUTO_ENTRY_DECISION_ACTION,
        "ticker": ticker,
        "reason": reason,
        "metadata": {
            "condition_id": condition_id,
            "decision": decision,
            "decision_key": decision_key,
            **(metadata or {}),
        },
    }
    closed = portfolio.setdefault("closed_proposals", [])
    for item in reversed(closed):
        item_metadata = item.get("metadata", {}) or {}
        if item.get("action") == AUTO_ENTRY_DECISION_ACTION and item_metadata.get("decision_key") == decision_key:
            item.update(entry)
            save_portfolio_file(portfolio)
            return item
    closed.append(entry)
    save_portfolio_file(portfolio)
    return entry


def _format_auto_trade_amount(value):
    try:
        return f"EUR {float(value):.2f}"
    except (TypeError, ValueError):
        return "EUR n/d"


def process_autonomous_met_entry_conditions(auto_apply_virtual, max_auto_trade_pct):
    """Apply or audit confirmed entry conditions after the LLM cycle.

    The LLM can still make richer decisions, but this deterministic pass ensures
    every confirmed BUY_CANDIDATE leaves an operational trace: buy applied,
    already-held skip, pending skip, cash/liquidity skip, or manual-mode skip.
    """
    conditions = [
        item
        for item in list_monitored_conditions(status="met")
        if str((item.get("metadata") or {}).get("scenario_state") or "").upper()
        in {"BUY_CANDIDATE", "TRIGGER_MET", "CONFIRMED"}
    ]
    if not conditions:
        log_step("Post-check autonomia ingressi: nessuna condizione met/BUY_CANDIDATE da processare")
        return []

    settings = load_autonomy_settings()
    action_mode = settings.get("portfolio_action_mode", "confirmation")
    log_step(
        "Post-check autonomia ingressi: "
        f"{len(conditions)} condizioni confermate | mode={action_mode} auto_apply_virtual={auto_apply_virtual}"
    )

    decisions = []
    for condition in conditions:
        portfolio = load_portfolio_file()
        if portfolio is None:
            break
        ticker = str(condition.get("ticker", "")).strip().upper()
        metadata = condition.get("metadata", {}) or {}
        scenario, price, trigger, volume_ratio = _condition_reference_values(condition)
        state = str(metadata.get("scenario_state") or scenario.get("state") or condition.get("status")).upper()
        condition_text = condition.get("condition", "")
        reason_base = (
            metadata.get("scenario_reason")
            or metadata.get("reason")
            or scenario.get("reason")
            or "setup operativo confermato"
        )
        held = ticker in _open_position_tickers(portfolio)
        pending = ticker in _pending_buy_tickers(portfolio)
        cash = float(portfolio.get("cash") or 0)
        max_amount = round(cash * max(0.0, float(max_auto_trade_pct or 0)) / 100.0, 2)
        liquidity_ok = metadata.get("liquidity_ok", True) is not False
        audit_metadata = {
            "scenario_state": state,
            "condition": condition_text,
            "scenario_reason": reason_base,
            "last_price": price,
            "trigger": trigger,
            "volume_ratio": volume_ratio,
            "autonomy_mode": action_mode,
            "auto_apply_virtual": auto_apply_virtual,
            "execution_key": execution_key(
                ticker,
                condition.get("id"),
                state,
                portfolio_id=portfolio.get("portfolio_id", "main"),
            ),
        }

        log_step(
            "Post-check autonomia ingressi | "
            f"{ticker}: state={state} price={price} trigger={trigger} vol_ratio={volume_ratio} "
            f"held={held} pending={pending} cash={cash:.2f} max_amount={max_amount:.2f} liquidity_ok={liquidity_ok}"
        )

        if pending:
            reason = f"{ticker}: setup ingresso confermato, ma esiste gia una proposta buy pending."
            _record_auto_entry_decision(condition, "skip_pending_buy", reason, status="skipped", metadata=audit_metadata)
            update_monitored_condition(
                condition_id=condition.get("id"),
                status="met",
                note=reason,
                metadata={**metadata, "auto_decision": "skip_pending_buy", "auto_decision_reason": reason},
            )
            log_step(f"Post-check autonomia ingressi | {ticker}: skip, proposta pending esistente")
            decisions.append({"ticker": ticker, "decision": "skip_pending_buy", "reason": reason})
            continue

        if not liquidity_ok:
            reason = f"{ticker}: setup ingresso confermato ma liquidita non sufficiente per operativita automatica."
            _record_auto_entry_decision(condition, "skip_low_liquidity", reason, status="skipped", metadata=audit_metadata)
            update_monitored_condition(
                condition_id=condition.get("id"),
                status="invalidated",
                note=reason,
                metadata={**metadata, "auto_decision": "skip_low_liquidity", "auto_decision_reason": reason},
            )
            log_step(f"Post-check autonomia ingressi | {ticker}: invalidato per liquidita")
            decisions.append({"ticker": ticker, "decision": "skip_low_liquidity", "reason": reason})
            continue

        action_allowed, _ = autonomous_action_allowed("buy_virtual_position")
        if not auto_apply_virtual or not action_allowed:
            reason = (
                f"{ticker}: setup ingresso confermato ({reason_base}), ma la modalita corrente non consente acquisto automatico."
            )
            _record_auto_entry_decision(condition, "skip_manual_mode", reason, status="skipped", metadata=audit_metadata)
            update_monitored_condition(
                condition_id=condition.get("id"),
                status="met",
                note=reason,
                metadata={**metadata, "auto_decision": "skip_manual_mode", "auto_decision_reason": reason},
            )
            log_step(f"Post-check autonomia ingressi | {ticker}: skip, modalita non autonoma")
            decisions.append({"ticker": ticker, "decision": "skip_manual_mode", "reason": reason})
            continue

        if price is None or price <= 0 or max_amount <= 0 or cash <= 0:
            reason = (
                f"{ticker}: setup ingresso confermato ma prezzo/cash non validi "
                f"(price={price}, cash={cash:.2f}, max_amount={max_amount:.2f})."
            )
            _record_auto_entry_decision(condition, "skip_missing_price_or_cash", reason, status="skipped", metadata=audit_metadata)
            update_monitored_condition(
                condition_id=condition.get("id"),
                status="met",
                note=reason,
                metadata={**metadata, "auto_decision": "skip_missing_price_or_cash", "auto_decision_reason": reason},
            )
            log_step(f"Post-check autonomia ingressi | {ticker}: skip, prezzo o cash non valido")
            decisions.append({"ticker": ticker, "decision": "skip_missing_price_or_cash", "reason": reason})
            continue

        amount = min(cash, max_amount)
        trade_label = "INCREMENTO automatico" if held else "BUY automatico"
        success_decision = "applied_increase" if held else "applied_buy"
        failed_decision = "failed_increase" if held else "failed_buy"
        reason = (
            f"{trade_label} da condizione monitorata {condition.get('id')}: {state}. "
            f"Condizione: {condition_text}. Esito: {reason_base}. "
            f"Prezzo {price:.4f}, trigger {trigger if trigger is not None else 'n/d'}, "
            f"volume {volume_ratio if volume_ratio is not None else 'n/d'}x MA10."
        )
        proposal = add_buy_proposal(
            ticker=ticker,
            reason=reason,
            amount=amount,
            entry_price=price,
            metadata={
                **audit_metadata,
                "source": "autonomous_met_entry_condition",
                "execution_key": audit_metadata["execution_key"],
                "amount": amount,
                "entry_price": price,
            },
        )
        result = confirm_portfolio_proposal(proposal["id"])
        confirm_status = str(result.get("status") or "").lower()
        applied = confirm_status in {"ok", "confirmed", "applied"}
        update_monitored_condition(
            condition_id=condition.get("id"),
            status="bought" if applied else "met",
            note=(
                f"{trade_label} applicato: {ticker} {_format_auto_trade_amount(amount)}."
                if applied
                else f"{trade_label} non applicato: {result.get('status')}"
            ),
            metadata={
                **metadata,
                "auto_decision": success_decision if applied else failed_decision,
                "auto_decision_reason": reason,
                "auto_proposal_id": proposal["id"],
                "auto_trade_amount": amount,
            },
        )
        log_step(
            "Post-check autonomia ingressi | "
            f"{ticker}: {trade_label} {'applicato' if applied else 'fallito'} "
            f"proposal_id={proposal['id']} amount={amount:.2f}"
        )
        decisions.append(
            {
                "ticker": ticker,
                "decision": success_decision if applied else failed_decision,
                "proposal_id": proposal["id"],
                "amount": amount,
                "reason": reason,
            }
        )
    return decisions


def log_step(message):
    print(f"[agent] {message}", flush=True)


def short_text(value, limit=110):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def fmt_eur(value):
    try:
        return f"{float(value):,.2f} EUR"
    except (TypeError, ValueError):
        return "n/d"


def scheduled_telegram_tools_suppressed():
    return os.getenv("SUPPRESS_AGENT_TELEGRAM_TOOLS") == "1"


def log_operational_snapshot(label):
    """Write a compact but readable snapshot of the portfolio state into logs."""
    try:
        status = portfolio_status_summary()
        performance = calculate_portfolio_performance(record_history=False)
    except Exception as exc:
        log_step(f"Snapshot operativo {label}: non disponibile ({exc.__class__.__name__}: {exc})")
        return

    positions = status.get("positions", []) or []
    pending_buy = status.get("pending_buy_proposals", []) or []
    pending_other = status.get("pending_other_proposals", []) or []
    waiting_conditions = [
        item for item in (status.get("monitored_conditions", []) or []) if item.get("status") == "waiting"
    ]
    watchlist = status.get("watchlist", []) or []

    log_step(
        f"Snapshot operativo {label}: "
        f"cash={fmt_eur(status.get('cash'))}; "
        f"valore_portafoglio={fmt_eur(performance.get('total_value'))}; "
        f"pnl={fmt_eur(performance.get('total_pnl'))} ({performance.get('total_pnl_pct', 0):.2f}%); "
        f"posizioni={len(positions)}; trigger_waiting={len(waiting_conditions)}; "
        f"pending_buy={len(pending_buy)}; pending_other={len(pending_other)}; watchlist={len(watchlist)}"
    )

    if positions:
        log_step("Posizioni aperte da controllare:")
        for item in positions[:10]:
            log_step(
                "  - "
                f"{item.get('ticker')}: allocato={fmt_eur(item.get('allocated_amount'))}; "
                f"entry={item.get('entry_price', 'n/d')}; qty={item.get('virtual_quantity', 'n/d')}"
            )
        if len(positions) > 10:
            log_step(f"  - ... altre {len(positions) - 10} posizioni")
    else:
        log_step("Posizioni aperte da controllare: nessuna")

    if waiting_conditions:
        log_step("Trigger/condizioni in monitoraggio:")
        for item in waiting_conditions[:14]:
            log_step(
                "  - "
                f"{item.get('ticker')}: {short_text(item.get('condition'))} | "
                f"azione={short_text(item.get('action_if_met'), 80)}"
            )
        if len(waiting_conditions) > 14:
            log_step(f"  - ... altri {len(waiting_conditions) - 14} trigger waiting")
    else:
        log_step("Trigger/condizioni in monitoraggio: nessuno")

    if watchlist:
        log_step("Watchlist manuale da considerare nel ciclo:")
        for item in watchlist[:10]:
            entry = item.get("entry_condition") or "nessuna condizione ingresso salvata"
            log_step(
                "  - "
                f"{item.get('ticker')}: priorita={item.get('priority', 'normal')}; "
                f"motivo={short_text(item.get('reason'), 70)}; entry={short_text(entry, 90)}"
            )
        if len(watchlist) > 10:
            log_step(f"  - ... altri {len(watchlist) - 10} titoli in watchlist")
    else:
        log_step("Watchlist manuale da considerare nel ciclo: vuota")


def log_monitor_plan(
    scan_limit,
    universe_limit,
    live_news,
    deep_confirm_limit,
    auto_apply_virtual,
    max_auto_trade_pct,
    condition_limit=DEFAULT_PERIODIC_CONDITION_LIMIT,
    run_market_scanners=True,
):
    universe_label = f"primi {universe_limit} strumenti" if universe_limit else "universo completo"
    mode_label = "applica operazioni virtuali autonome" if auto_apply_virtual else "solo proposte pending"
    log_step("Piano ciclo monitor:")
    log_step("  1) Leggo portafoglio, cash, performance, posizioni aperte e alert.")
    log_step(
        f"  2) Rivaluto i {condition_limit} trigger attivi a priorita piu alta e la watchlist; "
        "prima filtri numerici, poi eventuale conferma."
    )
    if run_market_scanners:
        log_step(
            "  3) Scanner orario locale FTSE MIB, Materie prime ed ETF: "
            f"top={scan_limit}, universo={universe_label}. Questo step usa dati Yahoo/indicatori, non Playwright."
        )
    else:
        log_step("  3) Ciclo intermedio: scanner saltati; uso le condizioni gia salvate.")
    if live_news:
        log_step(
            "  4) Playwright/ChatGPT viene usato solo dopo filtro numerico: "
            f"trigger in CONFIRMING/BUY_CANDIDATE o posizioni con segnale concreto di uscita; massimo {deep_confirm_limit} approfondimenti."
        )
    else:
        log_step(
            "  4) Playwright/ChatGPT disabilitato in questo ciclo: uso solo indicatori locali e news in cache."
        )
    log_step(
        "  5) Decisione finale: "
        f"{mode_label}; limite singola operazione autonoma={max_auto_trade_pct:.1f}% del cash; "
        f"news_live={'abilitate' if live_news else 'disabilitate'}."
    )


def compact_report_payload(payload, report_key="report", limit=1800):
    compact = dict(payload)
    report = str(compact.get(report_key) or "")
    if len(report) > limit:
        compact[report_key] = report[:limit].rsplit(" ", 1)[0] + "..."
        compact["report_truncated"] = True
        compact["full_report_file"] = compact.get("file") or compact.get("analysis_file")
    return compact


def _short_text(value, limit=320):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _condition_priority(item):
    metadata = item.get("metadata", {}) or {}
    state = str(metadata.get("scenario_state") or item.get("status") or "").upper()
    state_rank = {
        "BUY_CANDIDATE": 60,
        "TRIGGER_MET": 55,
        "CONFIRMED": 50,
        "CONFIRMING": 45,
        "NEAR_TRIGGER": 35,
        "WAIT": 10,
        "WAITING": 10,
    }.get(state, 0)
    try:
        price = float(metadata.get("last_price"))
        trigger = float(metadata.get("trigger_price") or metadata.get("resistance_10"))
        gap = abs(price - trigger) / trigger if trigger else 99.0
    except (TypeError, ValueError):
        gap = 99.0
    liquidity_rank = 1 if metadata.get("liquidity_ok", True) is not False else 0
    return state_rank, liquidity_rank, -gap, str(item.get("updated_at") or item.get("created_at") or "")


def select_priority_conditions(status="waiting", limit=DEFAULT_PERIODIC_CONDITION_LIMIT):
    conditions = list_monitored_conditions(status=status or None)
    if not status or status in {"waiting", "met"}:
        conditions = [
            item
            for item in conditions
            if item.get("status") in {"waiting", "met"}
        ]
    conditions.sort(key=_condition_priority, reverse=True)
    return conditions[:max(1, int(limit))]


def compact_condition(item):
    metadata = item.get("metadata", {}) or {}
    compact_metadata = {
        key: metadata.get(key)
        for key in (
            "scenario_state",
            "last_entry_scenario_eval_at",
            "last_price",
            "change_1d_pct",
            "volume_ratio",
            "support_10",
            "resistance_10",
            "trigger_price",
            "liquidity_ok",
            "asset_class",
            "auto_decision",
            "daily_bar_complete",
            "market_close_at",
            "volume_finalized_at",
            "market_session_reason",
        )
        if metadata.get(key) is not None
    }
    if metadata.get("scenario_reason"):
        compact_metadata["scenario_reason"] = _short_text(metadata["scenario_reason"], 260)
    scenarios = []
    for scenario in (metadata.get("entry_scenarios") or [])[:2]:
        scenarios.append(
            {
                key: scenario.get(key)
                for key in ("name", "state", "trigger", "support", "last_price", "last_volume_ratio")
                if scenario.get(key) is not None
            }
        )
        if scenario.get("reason"):
            scenarios[-1]["reason"] = _short_text(scenario["reason"], 220)
    if scenarios:
        compact_metadata["entry_scenarios"] = scenarios
    return {
        "id": item.get("id"),
        "ticker": item.get("ticker"),
        "status": item.get("status"),
        "condition": _short_text(item.get("condition"), 360),
        "reason": _short_text(item.get("reason"), 240),
        "action_if_met": _short_text(item.get("action_if_met"), 220),
        "updated_at": item.get("updated_at"),
        "metadata": compact_metadata,
    }


def compact_operating_status(condition_limit=DEFAULT_PERIODIC_CONDITION_LIMIT):
    status = portfolio_status_summary()
    conditions = select_priority_conditions(limit=condition_limit)
    positions = []
    for item in status.get("positions", []):
        positions.append(
            {
                key: item.get(key)
                for key in (
                    "ticker",
                    "name",
                    "market",
                    "entry_price",
                    "virtual_quantity",
                    "allocated_amount",
                    "opened_at",
                    "status",
                )
                if item.get(key) is not None
            }
        )
    watchlist = [
        {
            "ticker": item.get("ticker"),
            "priority": item.get("priority"),
            "reason": _short_text(item.get("reason"), 220),
            "entry_condition": _short_text(item.get("entry_condition"), 300),
        }
        for item in status.get("watchlist", [])
    ]
    return {
        "status": status.get("status"),
        "updated_at": status.get("updated_at"),
        "initial_capital": status.get("initial_capital"),
        "cash": status.get("cash"),
        "positions": positions,
        "pending_buy_proposals": status.get("pending_buy_proposals", []),
        "pending_other_proposals": status.get("pending_other_proposals", []),
        "priority_conditions": [compact_condition(item) for item in conditions],
        "priority_conditions_count": len(conditions),
        "active_conditions_total": len(
            [
                item
                for item in status.get("monitored_conditions", [])
                if item.get("status") in {"waiting", "met"}
            ]
        ),
        "watchlist": watchlist,
    }


def compact_scan_payload(payload, limit):
    compact = {
        key: payload.get(key)
        for key in ("status", "market", "scanned", "errors", "file")
        if payload.get(key) is not None
    }
    candidates = []
    for item in (payload.get("candidates") or [])[:max(1, int(limit))]:
        candidate = {
            key: item.get(key)
            for key in (
                "ticker",
                "name",
                "market",
                "sector",
                "score",
                "close",
                "change_1d_pct",
                "volume_ratio",
                "support_10",
                "resistance_10",
                "liquidity_ok",
            )
            if item.get(key) is not None
        }
        if item.get("reasons"):
            candidate["reasons"] = [_short_text(reason, 180) for reason in item["reasons"][:4]]
        if item.get("risks"):
            candidate["risks"] = [_short_text(risk, 180) for risk in item["risks"][:3]]
        candidates.append(candidate)
    compact["candidates"] = candidates
    compact["monitored_conditions_created"] = [
        compact_condition(item)
        for item in (payload.get("monitored_conditions_created") or [])[:max(1, int(limit))]
    ]
    return compact


def compact_scenario_evaluation(payload):
    compact_results = []
    for item in payload.get("results", []):
        result = {
            key: item.get(key)
            for key in (
                "status",
                "ticker",
                "condition_id",
                "scenario_state",
                "last_price",
                "trigger",
                "support",
                "volume_ratio",
                "liquidity_ok",
                "playwright_used",
            )
            if item.get(key) is not None
        }
        if item.get("reason"):
            result["reason"] = _short_text(item["reason"], 300)
        scenarios = item.get("scenarios") or []
        if scenarios:
            result["scenarios"] = [
                {
                    key: scenario.get(key)
                    for key in ("name", "state", "trigger", "support", "last_price", "last_volume_ratio")
                    if scenario.get(key) is not None
                }
                for scenario in scenarios[:2]
            ]
        compact_results.append(result)
    return {
        "status": payload.get("status"),
        "evaluated": payload.get("evaluated"),
        "playwright_used": payload.get("playwright_used"),
        "results": compact_results,
    }


@function_tool
def analyze_stock_chart(ticker: str, days: int = 70, period: str = "1y") -> str:
    """Generate technical charts and numeric technical context for one stock.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        days: Number of recent trading bars to include in charts.
        period: Yahoo Finance download period, for example 6mo, 1y, or 2y.
    """
    log_step(
        f"FASE ANALISI TECNICA: {ticker} | scarico dati Yahoo Finance, calcolo indicatori e preparo grafici "
        f"(days={days}, period={period})"
    )
    return generate_chart_context_json(ticker=ticker, days=days, period=period)


@function_tool
def analyze_stock_news(ticker: str, live: bool = True) -> str:
    """Return a news report for one stock.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        live: If true, run the Playwright ChatGPT news workflow; if false, read cached news if available.
    """
    mode = "Playwright live" if live else "cache locale"
    log_step(f"FASE NEWS: {ticker} | modalita={mode}")
    return json.dumps(
        compact_report_payload(get_news_report(ticker=ticker, live=live), limit=1800),
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def evaluate_entry_scenarios(
    tickers: str = "",
    use_playwright: bool = True,
    live_news: bool = True,
    max_playwright: int = 2,
    limit: int = DEFAULT_PERIODIC_CONDITION_LIMIT,
) -> str:
    """Evaluate monitored entry scenarios and confirm only near-decision tickers with Playwright.

    Args:
        tickers: Optional comma-separated tickers. Empty means all waiting monitored conditions.
        use_playwright: If true, use Playwright chart/news only when numeric checks reach confirmation state.
        live_news: If true, live news confirmation uses Playwright/ChatGPT.
        max_playwright: Maximum number of tickers to confirm visually/news-live in this call.
        limit: Maximum number of priority conditions to evaluate when tickers is empty.
    """
    selected = [item.strip().upper() for item in tickers.split(",") if item.strip()]
    if not selected:
        selected = [
            str(item.get("ticker", "")).strip().upper()
            for item in select_priority_conditions(limit=limit)
            if item.get("ticker")
        ]
    log_step(
        "Tool evaluate_entry_scenarios chiamato | "
        f"tickers={selected} limit={limit} use_playwright={use_playwright} "
        f"live_news={live_news} max_playwright={max_playwright}"
    )
    payload = evaluate_monitored_entry_scenarios(
        tickers=selected,
        use_playwright=use_playwright,
        live_news=live_news,
        max_playwright=max_playwright,
    )
    return json.dumps(
        compact_scenario_evaluation(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    )


@function_tool
def confirm_candidate_chart_with_playwright(
    ticker: str,
    no_telegram: bool = True,
    reason: str = "",
) -> str:
    """Run a deep visual chart confirmation with Playwright/ChatGPT for one candidate.

    Use this only for operational cases: a ticker already in portfolio that
    needs portfolio monitoring, a monitored trigger that has fired or is in
    CONFIRMING/BUY_CANDIDATE state, or an open position with an active
    exit/reduce/protection signal. Do not use this just because a ticker appears
    in a scanner top list.

    Args:
        ticker: Stock ticker symbol to confirm visually, for example AMP.MI.
        no_telegram: If true, do not send Telegram during confirmation.
        reason: The exact numeric trigger/state that makes this ticker worth
            confirming now, not a generic "top candidate" reason.
    """
    log_step(
        "FASE PLAYWRIGHT GRAFICO: conferma visuale AI del candidato | "
        f"ticker={ticker} no_telegram={no_telegram} | "
        f"motivo_approfondimento={reason or 'non dichiarato dal modello; usare solo se trigger numerico gia in conferma'}"
    )
    return json.dumps(
        compact_report_payload(confirm_candidate_with_chart_ai(ticker=ticker, no_telegram=no_telegram), limit=2200),
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def load_watchlist(path: str = "portfolio.example.json") -> str:
    """Load a watchlist JSON file.

    Args:
        path: Relative or absolute path to a JSON file containing a watchlist array.
    """
    file_path = Path(path)
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    log_step(f"Tool load_watchlist chiamato | file={file_path}")
    if not file_path.exists():
        return json.dumps({"status": "missing", "file": str(file_path)}, ensure_ascii=False)
    return file_path.read_text(encoding="utf-8")


@function_tool
def load_virtual_portfolio() -> str:
    """Load the current virtual portfolio, if it exists."""
    log_step("Tool load_virtual_portfolio chiamato")
    portfolio = load_portfolio_file()
    if portfolio is None:
        return json.dumps({"status": "missing", "message": "portfolio.json non esiste."}, ensure_ascii=False)
    return json.dumps({"status": "ok", "portfolio": portfolio}, ensure_ascii=False, indent=2)


@function_tool
def add_ticker_to_watchlist(
    ticker: str,
    reason: str = "",
    name: str = "",
    market: str = "",
    priority: str = "normal",
    tags: str = "",
    entry_condition: str = "",
) -> str:
    """Add or update one ticker in the manual watchlist.

    Args:
        ticker: Stock ticker symbol, for example VOD.L or A2A.MI.
        reason: Why the user or agent wants to monitor it.
        name: Optional company name.
        market: Optional market/exchange.
        priority: low, normal, high.
        tags: Optional comma-separated labels.
        entry_condition: Optional concrete entry trigger to monitor, for example close above a level with volume.
    """
    log_step(f"Tool add_ticker_to_watchlist chiamato | ticker={ticker} priority={priority}")
    item = add_watchlist_item(
        ticker=ticker,
        name=name,
        market=market,
        reason=reason,
        priority=priority,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        entry_condition=entry_condition,
    )
    return json.dumps({"status": "ok", "watchlist_item": item}, ensure_ascii=False, indent=2)


@function_tool
def remove_ticker_from_watchlist(ticker: str) -> str:
    """Remove one ticker from the manual watchlist."""
    log_step(f"Tool remove_ticker_from_watchlist chiamato | ticker={ticker}")
    return json.dumps(remove_watchlist_item(ticker), ensure_ascii=False, indent=2)


@function_tool
def list_manual_watchlist() -> str:
    """List all tickers in the manual watchlist."""
    log_step("Tool list_manual_watchlist chiamato")
    return json.dumps({"status": "ok", "watchlist": list_portfolio_watchlist()}, ensure_ascii=False, indent=2)


@function_tool
def scan_mib30_for_candidates(limit: int = 5, create_proposals: bool = False, universe_limit: int = 0) -> str:
    """Scan Italian FTSE MIB tickers and find interesting technical candidates.

    Args:
        limit: Maximum number of candidates to return.
        create_proposals: If true, create pending proposals in portfolio.json. Proposals still require user confirmation.
        universe_limit: Optional number of tickers to analyze for quick tests. Use 0 for full universe.
    """
    log_step(
        "FASE SCANNER FTSE MIB: analisi tecnica locale dei titoli | "
        f"top={limit} create_proposals={create_proposals} universe_limit={universe_limit or 'tutti'}"
    )
    payload = json.loads(scan_mib30_candidates_json(
        limit=limit,
        create_proposals=create_proposals,
        universe_limit=universe_limit or None,
    ))
    created = ensure_candidate_conditions(payload.get("candidates", []), market="FTSE MIB", max_items=limit)
    payload["monitored_conditions_created"] = created
    if created:
        log_step(f"Scanner FTSE MIB: create {len(created)} condizioni monitorate automatiche")
    return json.dumps(compact_scan_payload(payload, limit), ensure_ascii=False, separators=(",", ":"))


@function_tool
def list_commodity_universe() -> str:
    """List instruments loaded from validTickers/MateriePrime.xlsx."""
    log_step("Tool list_commodity_universe chiamato")
    return load_commodity_tickers_json()


@function_tool
def scan_commodities_for_candidates(limit: int = 8, universe_limit: int = 0) -> str:
    """Scan commodity/ETC tickers from MateriePrime.xlsx and find interesting technical candidates.

    Args:
        limit: Maximum number of candidates to return.
        universe_limit: Optional number of instruments to analyze for quick tests. Use 0 for full universe.
    """
    log_step(
        "FASE SCANNER MATERIE PRIME: analisi tecnica locale degli ETC/ETN | "
        f"top={limit} universe_limit={universe_limit or 'tutti'}"
    )
    payload = json.loads(scan_commodity_candidates_json(
        limit=limit,
        universe_limit=universe_limit or None,
    ))
    created = ensure_candidate_conditions(payload.get("candidates", []), market="Materie prime", max_items=limit)
    payload["monitored_conditions_created"] = created
    if created:
        log_step(f"Scanner materie prime: create {len(created)} condizioni monitorate automatiche")
    return json.dumps(compact_scan_payload(payload, limit), ensure_ascii=False, separators=(",", ":"))


@function_tool
def list_etf_universe() -> str:
    """List configured ETF instruments."""
    log_step("Tool list_etf_universe chiamato")
    return load_etf_tickers_json()


@function_tool
def scan_etf_for_candidates(limit: int = 8, universe_limit: int = 0) -> str:
    """Scan configured ETF tickers and find interesting technical candidates.

    Args:
        limit: Maximum number of candidates to return.
        universe_limit: Optional number of instruments to analyze for quick tests. Use 0 for full universe.
    """
    log_step(
        "FASE SCANNER ETF: analisi tecnica locale degli ETF configurati | "
        f"top={limit} universe_limit={universe_limit or 'tutti'}"
    )
    payload = json.loads(scan_etf_candidates_json(
        limit=limit,
        universe_limit=universe_limit or None,
    ))
    created = ensure_candidate_conditions(payload.get("candidates", []), market="ETF", max_items=limit)
    payload["monitored_conditions_created"] = created
    if created:
        log_step(f"Scanner ETF: create {len(created)} condizioni monitorate automatiche")
    return json.dumps(compact_scan_payload(payload, limit), ensure_ascii=False, separators=(",", ":"))


@function_tool
def propose_virtual_portfolio_from_mib30(
    capital: float,
    max_positions: int = 5,
    cash_pct: float = 15,
    universe_limit: int = 0,
) -> str:
    """Create a pending virtual portfolio allocation proposal from FTSE MIB candidates.

    Args:
        capital: Total virtual capital the user wants to invest.
        max_positions: Maximum number of stocks in the proposal.
        cash_pct: Percentage of capital to keep as cash.
        universe_limit: Optional number of tickers to analyze for quick tests. Use 0 for full universe.
    """
    log_step(
        "Tool propose_virtual_portfolio_from_mib30 chiamato | "
        f"capital={capital} max_positions={max_positions} cash_pct={cash_pct} universe_limit={universe_limit}"
    )
    return propose_virtual_allocation_json(
        capital=capital,
        max_positions=max_positions,
        cash_pct=cash_pct,
        universe_limit=universe_limit or None,
    )


@function_tool
def list_portfolio_proposals() -> str:
    """List pending portfolio proposals that require explicit user confirmation."""
    log_step("Tool list_portfolio_proposals chiamato")
    return json.dumps({"status": "ok", "pending": list_pending_proposals()}, ensure_ascii=False, indent=2)


@function_tool
def get_portfolio_operating_status(
    condition_limit: int = DEFAULT_PERIODIC_CONDITION_LIMIT,
) -> str:
    """Return a compact operational view with all positions and only priority conditions.

    Args:
        condition_limit: Maximum number of active priority conditions to include.
    """
    log_step(f"Tool get_portfolio_operating_status chiamato | condition_limit={condition_limit}")
    return json.dumps(
        compact_operating_status(condition_limit=condition_limit),
        ensure_ascii=False,
        separators=(",", ":"),
    )


@function_tool
def set_virtual_portfolio_capital(new_capital: float, reason: str = "") -> str:
    """Update the virtual portfolio capital after explicit user instruction.

    Args:
        new_capital: New total virtual capital.
        reason: Optional reason/audit note.
    """
    log_step(f"Tool set_virtual_portfolio_capital chiamato | new_capital={new_capital}")
    return json.dumps(
        update_portfolio_capital(new_capital=new_capital, reason=reason),
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def record_monitored_condition(
    ticker: str,
    condition: str,
    reason: str,
    action_if_met: str = "rivaluta per possibile proposta",
    status: str = "waiting",
) -> str:
    """Persist a condition that must be monitored and re-evaluated later.

    Args:
        ticker: Stock ticker symbol.
        condition: Concrete condition to monitor, for example close sopra 3.966 con volumi.
        reason: Why the condition matters.
        action_if_met: What the agent should do when the condition is met.
        status: Condition status, usually waiting.
    """
    log_step(f"Tool record_monitored_condition chiamato | ticker={ticker} condition={condition}")
    item = add_monitored_condition(
        ticker=ticker,
        condition=condition,
        reason=reason,
        action_if_met=action_if_met,
        status=status,
    )
    return json.dumps({"status": "ok", "condition": item}, ensure_ascii=False, indent=2)


@function_tool
def list_conditions_to_monitor(
    status: str = "waiting",
    limit: int = DEFAULT_PERIODIC_CONDITION_LIMIT,
) -> str:
    """List a compact, prioritized subset of saved monitoring conditions.

    Args:
        status: Optional status filter, for example waiting. Empty string returns all conditions.
        limit: Maximum number of conditions returned.
    """
    clean_status = status or None
    selected = select_priority_conditions(status=clean_status, limit=limit)
    log_step(f"Tool list_conditions_to_monitor chiamato | status={clean_status} limit={limit}")
    return json.dumps(
        {
            "status": "ok",
            "returned": len(selected),
            "conditions": [compact_condition(item) for item in selected],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


@function_tool
def update_condition_status(condition_id: str, status: str, note: str = "") -> str:
    """Update a monitored condition after re-evaluation.

    Args:
        condition_id: Monitored condition id.
        status: New status: waiting, met, invalidated, archived.
        note: Short reason for the update.
    """
    log_step(f"Tool update_condition_status chiamato | condition_id={condition_id} status={status}")
    return json.dumps(
        update_monitored_condition(condition_id=condition_id, status=status, note=note),
        ensure_ascii=False,
        indent=2,
    )


@function_tool
def create_buy_proposal(
    ticker: str,
    reason: str,
    amount: float | None = None,
    entry_price: float | None = None,
    market: str = "",
    asset_class: str = "",
) -> str:
    """Create a pending virtual buy proposal. User confirmation is still required.

    Args:
        ticker: Stock ticker symbol.
        reason: Why the buy proposal is being created.
        amount: Optional virtual amount to invest.
        entry_price: Optional current or reference entry price.
        market: Optional market label, for example Borsa Italiana or Materie prime / ETC.
        asset_class: Optional asset class label, for example equity or commodity.
    """
    log_step(
        "Tool create_buy_proposal chiamato | "
        f"ticker={ticker} amount={amount} entry_price={entry_price} market={market} asset_class={asset_class}"
    )
    metadata = {}
    if market:
        metadata["market"] = market
    if asset_class:
        metadata["asset_class"] = asset_class
    proposal = add_buy_proposal(ticker=ticker, reason=reason, amount=amount, entry_price=entry_price, metadata=metadata)
    return json.dumps({"status": "ok", "proposal": proposal}, ensure_ascii=False, indent=2)


@function_tool
def create_position_action_proposal(
    ticker: str,
    action_type: str,
    percent: float,
    reason: str,
    reference_price: float | None = None,
) -> str:
    """Create a pending proposal to sell or reduce an existing virtual position.

    Args:
        ticker: Stock ticker symbol already present in the virtual portfolio.
        action_type: sell to close the position, reduce to sell only a percentage.
        percent: Percentage of the position to sell. sell closes the whole position.
        reason: Why the position action is proposed.
        reference_price: Current/reference price used to simulate cash impact.
    """
    log_step(
        "Tool create_position_action_proposal chiamato | "
        f"ticker={ticker} action_type={action_type} percent={percent} reference_price={reference_price}"
    )
    proposal = add_position_action_proposal(
        ticker=ticker,
        action_type=action_type,
        percent=percent,
        reason=reason,
        reference_price=reference_price,
    )
    return json.dumps({"status": "ok", "proposal": proposal}, ensure_ascii=False, indent=2)


@function_tool
def send_monitoring_telegram_summary(extra_note: str = "") -> str:
    """Send a Telegram summary of monitored conditions, pending proposals and portfolio state.

    Args:
        extra_note: Optional short note to include at the end of the Telegram message.
    """
    log_step("Tool send_monitoring_telegram_summary chiamato")
    if scheduled_telegram_tools_suppressed():
        log_step(
            "Invio Telegram intermedio soppresso: "
            "il runner schedulato inviera il riepilogo consolidato finale"
        )
        return json.dumps(
            {
                "status": "skipped",
                "reason": "scheduled_consolidated_summary_pending",
            },
            ensure_ascii=False,
        )
    return json.dumps(send_monitoring_summary(extra_note=extra_note), ensure_ascii=False, indent=2)


@function_tool
def get_portfolio_performance() -> str:
    """Calculate current virtual portfolio performance with P/L per position and portfolio totals."""
    log_step("Tool get_portfolio_performance chiamato")
    return calculate_portfolio_performance_json()


@function_tool
def send_portfolio_performance_telegram(extra_note: str = "") -> str:
    """Send a Telegram message with current virtual portfolio performance."""
    log_step("Tool send_portfolio_performance_telegram chiamato")
    if scheduled_telegram_tools_suppressed():
        log_step(
            "Invio performance Telegram intermedio soppresso: "
            "il runner schedulato inviera il riepilogo consolidato finale"
        )
        return json.dumps(
            {
                "status": "skipped",
                "reason": "scheduled_consolidated_summary_pending",
            },
            ensure_ascii=False,
        )
    return json.dumps(send_performance_summary(extra_note=extra_note), ensure_ascii=False, indent=2)


@function_tool
def analyze_portfolio_positions_deep(
    create_proposals: bool = False,
    auto_apply: bool = False,
    send_telegram: bool = False,
    max_positions: int = 10,
) -> str:
    """Run an on-demand deep analysis only on currently open portfolio positions.

    This uses chart analysis and live news via Playwright/ChatGPT for each open
    position, then returns operational indications: hold, protect, reduce or sell.
    It never scans FTSE MIB, commodities or watchlist tickers.

    Args:
        create_proposals: If true, create pending reduce/sell proposals when the
            analysis finds an operational signal.
        auto_apply: If true, immediately apply created virtual reduce/sell
            proposals. Use only in autonomous virtual mode or when explicitly
            requested by the user.
        send_telegram: If true, send a compact Telegram summary.
        max_positions: Safety limit for the number of open positions to analyze.
    """
    log_step(
        "Tool analyze_portfolio_positions_deep chiamato | "
        "scope=solo posizioni aperte in portafoglio | "
        f"create_proposals={create_proposals} auto_apply={auto_apply} "
        f"send_telegram={send_telegram} max_positions={max_positions}"
    )
    return run_deep_portfolio_analysis_json(
        max_positions=max_positions,
        create_proposals=create_proposals,
        auto_apply=auto_apply,
        send_telegram=send_telegram,
        use_playwright=True,
        live_news=True,
    )


@function_tool
def confirm_portfolio_proposal_tool(proposal_id: str) -> str:
    """Confirm and apply a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to confirm.
    """
    log_step(f"Tool confirm_portfolio_proposal_tool chiamato | proposal_id={proposal_id}")
    result = confirm_portfolio_proposal(proposal_id)
    proposal = result.get("proposal") or {}
    if result.get("status") == "ok" and proposal.get("action") in {
        "buy_virtual_position",
        "sell_virtual_position",
        "reduce_virtual_position",
    }:
        result["news_telegram"] = send_relevant_news_alerts([proposal.get("ticker")])
    return json.dumps(result, ensure_ascii=False, indent=2)


@function_tool
def auto_apply_virtual_proposal_tool(proposal_id: str, max_trade_pct: float = DEFAULT_MAX_AUTO_TRADE_PCT) -> str:
    """Confirm and apply one pending proposal in autonomous virtual mode with a cash percentage limit.

    Args:
        proposal_id: Pending proposal id to apply.
        max_trade_pct: Maximum percentage of current cash allowed for this autonomous virtual action.
    """
    log_step(
        "Tool auto_apply_virtual_proposal_tool chiamato | "
        f"proposal_id={proposal_id} max_trade_pct={max_trade_pct}"
    )
    portfolio = load_portfolio_file()
    if portfolio is None:
        return json.dumps({"status": "missing", "message": "portfolio.json non esiste."}, ensure_ascii=False)

    pending = portfolio.get("pending_proposals", [])
    proposal = next((item for item in pending if item.get("id") == proposal_id), None)
    if not proposal:
        return json.dumps({"status": "missing", "proposal_id": proposal_id}, ensure_ascii=False)

    allowed_actions = {"buy_virtual_position", "sell_virtual_position", "reduce_virtual_position"}
    if proposal.get("action") not in allowed_actions:
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "message": "La modalita autonoma puo applicare solo buy/reduce/sell virtuali.",
            },
            ensure_ascii=False,
            indent=2,
        )

    action_allowed, autonomy_mode = autonomous_action_allowed(proposal.get("action"))
    if not action_allowed:
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "action": proposal.get("action"),
                "portfolio_action_mode": autonomy_mode,
                "message": (
                    "Operazione autonoma bloccata dalla configurazione Controlli. "
                    "La proposta resta pending e non modifica il portafoglio."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    amount = proposal.get("metadata", {}).get("amount")
    if proposal.get("action") == "buy_virtual_position" and amount is None:
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "message": "Importo mancante: proposta non applicabile autonomamente.",
            },
            ensure_ascii=False,
            indent=2,
        )

    cash = float(portfolio.get("cash", 0) or 0)
    max_amount = round(cash * float(max_trade_pct) / 100.0, 2)
    if proposal.get("action") == "buy_virtual_position" and float(amount) > max_amount:
        return json.dumps(
            {
                "status": "blocked",
                "proposal_id": proposal_id,
                "amount": amount,
                "cash": cash,
                "max_allowed": max_amount,
                "message": "Importo oltre il limite autonomo configurato.",
            },
            ensure_ascii=False,
            indent=2,
        )

    result = confirm_portfolio_proposal(proposal_id)
    applied = result.get("proposal") or {}
    if result.get("status") == "ok":
        result["news_telegram"] = send_relevant_news_alerts([applied.get("ticker")])
    return json.dumps(result, ensure_ascii=False, indent=2)


@function_tool
def reject_portfolio_proposal_tool(proposal_id: str) -> str:
    """Reject and archive a pending portfolio proposal.

    Args:
        proposal_id: The proposal id to reject.
    """
    log_step(f"Tool reject_portfolio_proposal_tool chiamato | proposal_id={proposal_id}")
    return json.dumps(reject_portfolio_proposal(proposal_id), ensure_ascii=False, indent=2)


def build_agent(
    model=DEFAULT_MODEL,
    auto_apply_virtual=False,
    max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT,
    periodic=False,
):
    autonomy_mode = load_autonomy_settings()["portfolio_action_mode"]
    mode = "AUTO-VIRTUAL" if auto_apply_virtual and autonomy_mode != "confirmation" else "CONFIRMATION"
    log_step(
        "Creo agente Portfolio Monitor Agent | "
        f"model={model} | parallel_tool_calls=False | max_output_tokens={DEFAULT_MAX_OUTPUT_TOKENS} | mode={mode}"
    )
    if auto_apply_virtual and autonomy_mode != "confirmation":
        autonomy_scope = (
            "acquisti, riduzioni, vendite e ribilanciamenti"
            if autonomy_mode == "full_auto"
            else "sole riduzioni e vendite protettive; gli acquisti autonomi sono bloccati"
        )
        operation_policy = (
            "Modalita AUTONOMA VIRTUALE attiva: puoi applicare da solo operazioni simulate sul solo portafoglio virtuale "
            "con auto_apply_virtual_proposal_tool dopo avere creato una proposta pending motivata. "
            f"La configurazione Controlli e '{autonomy_mode}' e autorizza {autonomy_scope}. "
            "Non puoi operare su broker reali o sistemi esterni. "
            f"Ogni nuova operazione autonoma deve rispettare il limite massimo del {max_auto_trade_pct:.1f}% del cash disponibile "
            "al momento della decisione. "
            "Prima di applicare un acquisto autonomo devi avere analisi tecnica aggiornata, news valutate e motivazione sintetica. "
            "Le news sono parte del processo decisionale: usa analyze_stock_news per verificare catalizzatori, eventi societari, risultati, "
            "guidance, target price, downgrade/upgrade o rischi. Se le news non sono disponibili, dichiaralo nella motivazione e riduci "
            "la confidenza: puoi agire solo se il quadro tecnico e molto chiaro e il rischio e controllato. "
            "Prima di comprare verifica sempre la liquidita: se lo scanner segnala liquidity_ok=false, volume medio o controvalore basso, "
            "non comprare autonomamente e non creare proposta buy; al massimo mantieni monitoraggio o scarta. "
            "Se il segnale e debole o contraddittorio, salva/aggiorna una condizione monitorata invece di applicare. "
            "Quando una condizione monitorata o un trigger di watchlist e verificato e il contesto resta valido, devi creare una proposta "
            "di acquisto e applicarla autonomamente con auto_apply_virtual_proposal_tool. "
            "Questo vale anche per gli strumenti Materie prime / ETC: se un candidato commodity ha trigger verificato, volumi/news non contrari "
            f"e l'esposizione complessiva alle materie prime resta ragionevole, massimo indicativo {DEFAULT_MAX_COMMODITY_ALLOCATION_PCT:.1f}% "
            "del valore portafoglio, devi trattarlo come BUY CANDIDATE operativo e puoi comprarlo nel portafoglio virtuale. "
            "Puoi anche modificare asset gia in portafoglio creando proposte di reduce/sell con create_position_action_proposal "
            "e applicandole con auto_apply_virtual_proposal_tool se i segnali di uscita o protezione sono chiari. "
            "Quando una nuova opportunita e migliore di una posizione aperta debole, puoi ribilanciare: prima riduci o vendi parzialmente "
            "la posizione piu fragile, poi usa il cash per il nuovo ingresso, sempre rispettando max trade e motivando il confronto. "
            "Applica automaticamente soltanto le azioni autorizzate dalla configurazione Controlli. "
            "In modalita protective, acquisti e incrementi devono restare proposte pending da confermare, "
            "mentre riduzioni e vendite protettive possono essere applicate automaticamente. "
            "In modalita full_auto non chiedere conferma: applica se tutte le regole sono rispettate. "
            "Dopo ogni operazione autonoma dichiara proposal_id, ticker, importo e motivo nel risultato; "
            "il runner gestisce la notifica Telegram evitando riepiloghi duplicati. "
        )
    else:
        operation_policy = (
            "Modalita CONFERMA SEMPRE: non modificare mai il portafoglio autonomamente. "
            "Per acquisti, incrementi, riduzioni, vendite e ribilanciamenti puoi solo creare proposte pending, "
            "e applicarle esclusivamente quando l'utente conferma esplicitamente un proposal_id. "
        )
    tools = [
        analyze_stock_chart,
        analyze_stock_news,
        confirm_candidate_chart_with_playwright,
        load_watchlist,
        add_ticker_to_watchlist,
        remove_ticker_from_watchlist,
        list_manual_watchlist,
        load_virtual_portfolio,
        get_portfolio_operating_status,
        set_virtual_portfolio_capital,
        scan_mib30_for_candidates,
        list_commodity_universe,
        scan_commodities_for_candidates,
        list_etf_universe,
        scan_etf_for_candidates,
        evaluate_entry_scenarios,
        propose_virtual_portfolio_from_mib30,
        list_portfolio_proposals,
        record_monitored_condition,
        list_conditions_to_monitor,
        update_condition_status,
        create_buy_proposal,
        create_position_action_proposal,
        send_monitoring_telegram_summary,
        get_portfolio_performance,
        send_portfolio_performance_telegram,
        analyze_portfolio_positions_deep,
        reject_portfolio_proposal_tool,
    ]
    if auto_apply_virtual and autonomy_mode != "confirmation":
        tools.append(auto_apply_virtual_proposal_tool)
    else:
        tools.append(confirm_portfolio_proposal_tool)
    if periodic:
        tools = [
            get_portfolio_operating_status,
            get_portfolio_performance,
            analyze_stock_chart,
            analyze_stock_news,
            evaluate_entry_scenarios,
            confirm_candidate_chart_with_playwright,
            list_manual_watchlist,
            scan_mib30_for_candidates,
            scan_commodities_for_candidates,
            scan_etf_for_candidates,
            record_monitored_condition,
            create_buy_proposal,
            create_position_action_proposal,
            auto_apply_virtual_proposal_tool
            if auto_apply_virtual and autonomy_mode != "confirmation"
            else confirm_portfolio_proposal_tool,
        ]
    periodic_instructions = (
        "Sei il monitor schedulato compatto di un portafoglio virtuale. Rispondi in italiano. "
        "Usa solo i tool necessari e termina appena hai deciso le azioni operative. "
        "Prima leggi stato operativo e performance. Non caricare mai il portafoglio completo. "
        "Analizza al massimo tre posizioni per ciclo, scelte solo tra alert performance, variazioni giornaliere anomale "
        "o segnali concreti di uscita/protezione; non analizzare automaticamente tutte le posizioni. "
        "Rivaluta i trigger prioritari con evaluate_entry_scenarios: Playwright/news live solo per CONFIRMING o BUY_CANDIDATE. "
        "Non usare Playwright sui semplici risultati degli scanner. Gli scanner creano short-list e condizioni, non acquisti diretti. "
        "Per comprare servono prezzo valido, liquidita adeguata, trigger confermato e news non negative. "
        "Per pullback serve evidenza di tenuta/rimbalzo; la sola vicinanza al supporto non basta. "
        f"Limite singola operazione: {max_auto_trade_pct:.1f}% del cash; esposizione commodity indicativa massima "
        f"{DEFAULT_MAX_COMMODITY_ALLOCATION_PCT:.1f}% del portafoglio. "
        f"Modalita autonomia: {autonomy_mode}. "
        + (
            "Puoi creare e applicare operazioni virtuali autorizzate usando proposta e tool di applicazione. "
            if auto_apply_virtual and autonomy_mode != "confirmation"
            else "Crea solo proposte; non applicare modifiche senza conferma. "
        )
        + "Non chiamare tool Telegram: news-evento e riepilogo consolidato sono gestiti dal runner. "
        "Non duplicare condizioni o proposte esistenti. Se non ci sono segnali concreti, non fare operazioni. "
        "Concludi con un risultato molto breve: azioni applicate/proposte, alert e conteggi; niente opzioni successive."
    )
    return Agent(
        name="Portfolio Monitor Agent",
        model=model,
        instructions=periodic_instructions if periodic else (
            "Sei un agente finanziario operativo per monitorare un portafoglio virtuale e una watchlist. "
            "Usa i tool disponibili per raccogliere dati tecnici e news. "
            "Le news non sono un accessorio: devono supportare o indebolire ogni decisione operativa. "
            "Per news e conferme visuali usa Playwright/ChatGPT tramite i tool dedicati, non generare analisi lunghe con il solo modello SDK. "
            "Il modello SDK deve orchestrare, scegliere i tool e sintetizzare decisioni; il grosso di news e analisi grafica deve arrivare da Playwright. "
            "Rispondi sempre in italiano. Non dare consulenza finanziaria personalizzata. "
            + operation_policy +
            "Il capitale virtuale puo invece essere aggiornato quando l'utente lo chiede esplicitamente "
            "con frasi come 'aggiorna il capitale a 20000 euro' o 'il capitale e 20000': usa set_virtual_portfolio_capital "
            "e poi mostra il nuovo stato operativo. "
            "Quando inizi un monitoraggio, una proposta o una domanda sullo stato operativo, usa get_portfolio_operating_status "
            "per costruire una vista unica: posizioni in portafoglio, proposte pending, condizioni monitorate e watchlist. "
            "Quando l'utente chiede di aggiungere un titolo alla watchlist o dice che vuole tenerlo sotto osservazione, "
            "usa add_ticker_to_watchlist. Quando chiede di rimuoverlo, usa remove_ticker_from_watchlist. "
            "La watchlist manuale e diversa dallo scanner: contiene titoli da analizzare piu approfonditamente anche se "
            "non filtrati dall'algoritmo. Quando analizzi opportunita o fai un monitor periodico, considera sempre anche "
            "i titoli della watchlist manuale prima di concludere. "
            "Ogni titolo in watchlist puo avere una entry_condition impostata dall'utente. Se esiste, usala come trigger "
            "principale da verificare; se manca, durante l'analisi proponi o salva una condizione di ingresso concreta "
            "con livello prezzo, conferma volumi e supporto di invalidazione. "
            + ENTRY_SCENARIOS_GUIDE +
            "Le condizioni di ingresso salvate devono essere rivalutate come scenari strutturati con evaluate_entry_scenarios: "
            "BREAKOUT e PULLBACK_SUPPORTO hanno stati WAIT, NEAR_TRIGGER, CONFIRMING, BUY_CANDIDATE, BOUGHT o INVALIDATED. "
            "Quando evaluate_entry_scenarios marca una condizione come met o BUY_CANDIDATE, devi decidere liberamente se creare e applicare "
            "un buy virtuale, ridurre/vendere una posizione esistente per fare spazio, oppure non agire spiegando il motivo. "
            "Non comprare solo perche il prezzo e vicino al supporto: serve tenuta/rimbalzo, volumi non contrari, liquidita adeguata e news non negative. "
            "Se analizzi titoli in watchlist e trovi una condizione gia presente tra le condizioni monitorate, "
            "non crearne una duplicata: cita quella esistente oppure aggiornala solo se cambia davvero il trigger. "
            "Quando l'utente chiede rendimento, performance o guadagno/perdita, usa get_portfolio_performance. "
            "Quando l'utente chiede una analisi approfondita on demand del portafoglio o delle posizioni aperte, "
            "usa analyze_portfolio_positions_deep: deve analizzare solo i titoli gia in portafoglio, con grafici e news via Playwright, "
            "e deve indicare chiaramente cosa fare per ogni posizione. Non usare questo flusso per scannerizzare nuovi titoli "
            "FTSE MIB, Materie prime o watchlist. Se l'utente chiede solo indicazioni, non applicare operazioni; "
            "se chiede anche proposte, crea proposte pending; se la modalita autonoma virtuale e attiva o l'utente chiede "
            "esplicitamente applicazione, puoi applicare le proposte virtuali. Se l'utente chiede di mandare l'analisi su Telegram, "
            "abilita send_telegram. "
            "Durante il monitor periodico valuta la performance del portafoglio e segnala alert di rendimento rilevanti. "
            "Valuta sempre anche le posizioni gia in portafoglio: se emergono segnali di uscita, riduzione o protezione, "
            "devi creare una proposta pending con create_position_action_proposal e motivarla; applicala solo se la policy operativa corrente lo consente. "
            "Se l'utente chiede una proposta o chiede se ci sono titoli da comprare, devi rispondere in modo operativo: "
            "BUY CANDIDATE, WAIT/MONITOR oppure SCARTATO. "
            "Prima di rifare analisi live, consulta load_virtual_portfolio, list_portfolio_proposals e list_conditions_to_monitor "
            "per usare lo stato gia salvato. "
            "Puoi dire BUY CANDIDATE solo dopo che evaluate_entry_scenarios ha portato una condizione numerica in conferma "
            "e, quando disponibile, dopo analisi dettagliata del grafico via Playwright e news live via Playwright, "
            "oppure dopo avere dichiarato che Playwright/news non sono disponibili e spiegato perche il segnale tecnico resta sufficiente; "
            "in quel caso crea una proposta pending se ci sono capitale e condizioni sufficienti, altrimenti chiedi il dato mancante. "
            "Se invece l'utente chiede esplicitamente di procedere con un acquisto anche se il segnale non e confermato, "
            "asseconda la richiesta creando una proposta pending con create_buy_proposal, includendo nel reason i rischi e "
            "specificando che e una forzatura consapevole rispetto al filtro prudenziale. "
            "Applicala solo se la policy operativa corrente lo consente, altrimenti attendi conferma proposal_id. "
            "Quando una condizione non e verificata ma il titolo resta interessante, salva la condizione con record_monitored_condition "
            "e spiega quando andra rivalutata. "
            "Il runner invia automaticamente un riepilogo Telegram quando condizioni monitorate o proposte cambiano "
            "a valle di screening, rivalutazione o proposta; non inviare duplicati se non richiesto esplicitamente. "
            "Quando rivaluti condizioni monitorate, usa prima evaluate_entry_scenarios. Per ogni condizione devi scegliere: mantenerla waiting, marcarla met, "
            "marcarla invalidated oppure archiviarla. Se la condizione e met e il titolo resta valido dopo grafico/news, "
            "crea una proposta pending con create_buy_proposal e, se sei in modalita autonoma virtuale, applicala con auto_apply_virtual_proposal_tool. "
            "Se il contesto tecnico/news e peggiorato, usa update_condition_status "
            "con status invalidated o archived e spiega il motivo. "
            "Quando analizzi un titolo, combina news, momentum, trend, supporti, resistenze, volumi e rischio. "
            "Per buy/sell/reduce cita sempre l'effetto delle news: favorevoli, neutre, negative o non disponibili. "
            "Quando cerchi candidati del mercato FTSE MIB, usa lo scanner MIB30 storico e spiega i criteri usati distinguendo ragioni tecniche e rischi. "
            "Quando l'utente parla di materie prime, commodity, oro, petrolio, gas, metalli o agricoli, "
            "usa list_commodity_universe e scan_commodities_for_candidates: e un universo separato caricato da validTickers/MateriePrime.xlsx. "
            "Per le materie prime chiarisci che molti strumenti sono ETC/ETN quotati a Milano e valuta anche volatilita, volumi e rischio specifico dello strumento. "
            "Quando l'utente parla di ETF, fondi tematici, robotics, automation o ROBO.MI, "
            "usa list_etf_universe e scan_etf_for_candidates: e un universo separato di ETF configurati. "
            "Gli ETF seguono lo stesso processo operativo: scan tecnico locale, filtro liquidita, condizione monitorata, "
            "poi Playwright solo se scatta un trigger o serve una decisione su posizione. "
            f"In modalita autonoma puoi comprare Materie prime / ETC esattamente come le azioni, ma usa prudenza: limite indicativo esposizione commodity "
            f"{DEFAULT_MAX_COMMODITY_ALLOCATION_PCT:.1f}% del valore portafoglio, importo singola operazione entro il limite cash configurato, "
            "liquidita adeguata, news non negative e trigger tecnico verificato o setup pullback con rimbalzo confermato. "
            "Quando devi proporre strumenti da mettere in portafoglio, usa prima lo scanner numerico sui mercati rilevanti: "
            "FTSE MIB e, se richiesto o in monitor autonomo, anche MateriePrime.xlsx e il mercato ETF configurato. "
            "Dopo gli scan confronta i candidati in una short-list unica, mantenendo chiaro il mercato di provenienza. "
            "Non chiamare confirm_candidate_chart_with_playwright direttamente sui migliori candidati dello scanner. "
            "Lo scanner serve solo a creare short-list e condizioni monitorate. "
            "Usa Playwright solo quando evaluate_entry_scenarios segnala uno scenario numerico scattato o in CONFIRMING/BUY_CANDIDATE, "
            "oppure su un titolo gia in portafoglio quando serve monitoraggio operativo, uscita, riduzione o protezione. "
            "Ogni volta che chiami confirm_candidate_chart_with_playwright devi compilare il parametro reason con la condizione precisa: "
            "ticker, scenario, close, trigger/supporto, volume/liquidita e perche lo stato numerico richiede conferma ora. "
            "Non usare motivazioni generiche come score alto, top candidate o watchlist prioritaria se non c'e un trigger numerico in conferma. "
            "Quando approfondisci piu candidati, procedi in sequenza: chiama un solo tool alla volta, attendi il risultato, "
            "riassumi cosa hai imparato e solo dopo decidi se chiamare il tool per il candidato successivo. "
            "Analizza un titolo selezionato alla volta: completa grafico, eventuali news, sintesi e giudizio provvisorio "
            "per quel ticker prima di iniziare qualsiasi tool sul ticker successivo. "
            "Non chiamare mai piu tool Playwright nello stesso passaggio di ragionamento. "
            "Se non approfondisci con Playwright, devi spiegare perche non era necessario. "
            "Se un tool restituisce dati mancanti, dichiaralo chiaramente e continua con i dati disponibili. "
            "Formatta l'output in modo compatto, adatto anche a Telegram. "
            "Alla fine di ogni risposta operativa proponi sempre una sezione 'Opzioni successive' con 3-6 opzioni numerate, "
            "ognuna con un comando concreto che l'utente puo scrivere, per esempio rivalutare condizioni, creare proposta, "
            "mostrare stato operativo, analizzare un ticker, cercare news live, confermare o rifiutare proposte. "
            "Le opzioni devono essere coerenti con lo stato attuale: se non ci sono proposte pending non proporre conferma proposta; "
            "se ci sono condizioni waiting proponi rivalutazione; se il capitale e assente proponi aggiornamento capitale."
        ),
        model_settings=ModelSettings(
            parallel_tool_calls=False,
            max_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            verbosity="low",
        ),
        tools=tools,
    )


def run_agent_once(agent, request, display_request=None, suppress_auto_telegram_summary=False, max_turns=None):
    run_max_turns = int(max_turns or DEFAULT_MAX_TURNS)
    log_step("Prompt operativo inviato all'agente:")
    log_step(display_request or request)
    log_step(f"Invio richiesta all'agente OpenAI SDK e attendo risposta/tool calls... max_turns={run_max_turns}")
    log_step(
        "FASE AI: consegno il contesto all'agente. "
        "Le righe successive 'Tool ... chiamato' indicano quali strumenti usa davvero e su quali ticker."
    )
    before_state = monitoring_state_signature()
    before_portfolio_state = portfolio_content_signature()
    final_output = ""
    try:
        previous_suppression = os.getenv("SUPPRESS_AGENT_TELEGRAM_TOOLS")
        if suppress_auto_telegram_summary:
            os.environ["SUPPRESS_AGENT_TELEGRAM_TOOLS"] = "1"
        try:
            result = Runner.run_sync(agent, request, max_turns=run_max_turns)
        finally:
            if previous_suppression is None:
                os.environ.pop("SUPPRESS_AGENT_TELEGRAM_TOOLS", None)
            else:
                os.environ["SUPPRESS_AGENT_TELEGRAM_TOOLS"] = previous_suppression
        usage = getattr(getattr(result, "context_wrapper", None), "usage", None)
        usage_event = record_token_usage(
            usage,
            model=getattr(agent, "model", DEFAULT_MODEL),
            mode="periodic" if suppress_auto_telegram_summary else "interactive",
            label=display_request or request,
        )
        if usage_event:
            log_step(
                "Consumo token OpenAI SDK | "
                f"requests={usage_event['requests']} input={usage_event['input_tokens']} "
                f"cached={usage_event['cached_input_tokens']} output={usage_event['output_tokens']} "
                f"totale={usage_event['total_tokens']}"
            )
        final_output = str(result.final_output).strip()
        log_step("Risposta finale agente ricevuta")
        print("\n" + final_output + "\n", flush=True)
    except Exception as exc:
        final_output = (
            f"Run interrotta prima della risposta finale: {exc.__class__.__name__}: {exc}. "
            "Le azioni gia eseguite dai tool restano salvate; controllo lo stato operativo e invio eventuale riepilogo."
        )
        log_step(final_output)
        print("\n" + final_output + "\n", flush=True)
        result = SimpleNamespace(final_output=final_output)
        result.interrupted_error = final_output
    after_state = monitoring_state_signature()
    after_portfolio_state = portfolio_content_signature()
    if not suppress_auto_telegram_summary:
        maybe_send_automatic_monitoring_summary(
            request,
            final_output,
            before_state,
            after_state,
            before_portfolio_state,
            after_portfolio_state,
        )
    return result


def build_legacy_periodic_monitor_request(
    scan_limit=5,
    universe_limit=0,
    live_news=True,
    deep_confirm_limit=3,
    auto_apply_virtual=False,
    max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT,
    condition_limit=DEFAULT_PERIODIC_CONDITION_LIMIT,
    run_market_scanners=True,
):
    live_news_hint = (
        "usa news live via Playwright solo per titoli con trigger, rischio rilevante o possibile operazione"
        if live_news
        else "usa solo news in cache con live=False; non avviare Playwright/ChatGPT in questo ciclo"
    )
    universe_hint = f"universe_limit={universe_limit}" if universe_limit else "universo completo"
    if auto_apply_virtual:
        operation_hint = (
            "Modalita AUTONOMA VIRTUALE abilitata: non devi chiedere conferma all'utente. "
            "Puoi applicare operazioni simulate usando auto_apply_virtual_proposal_tool dopo avere creato una proposta pending motivata, "
            "solo se il segnale e chiaro e dopo analisi tecnica/news. "
            "Le news devono confermare, non contraddire, o almeno non invalidare la decisione; se mancano, considera la decisione piu prudente. "
            "La liquidita e filtro obbligatorio: se lo scanner indica liquidity_ok=false o rischi di volume/controvalore basso, non comprare. "
            f"Limite per nuova operazione autonoma: massimo {max_auto_trade_pct:.1f}% del cash disponibile. "
            f"Puoi comprare anche candidati Materie prime / ETC se il trigger e verificato e l'esposizione commodity resta entro circa "
            f"{DEFAULT_MAX_COMMODITY_ALLOCATION_PCT:.1f}% del valore portafoglio. "
            "Se per comprare un candidato migliore serve liberare cash o ridurre rischio, valuta un ribilanciamento virtuale con reduce/sell "
            "su posizioni aperte piu deboli prima del nuovo buy. "
            "Se il segnale non e netto, non applicare: mantieni o crea una condizione monitorata. "
            "Non chiamare direttamente i tool Telegram nel ciclo schedulato: "
            "il runner inviera un unico riepilogo consolidato finale. "
        )
    else:
        operation_hint = "Non applicare mai operazioni al portafoglio senza conferma esplicita dell'utente. "
    scanner_hint = (
        f"Infine esegui gli scanner orari: FTSE MIB con scan_mib30_for_candidates limit={scan_limit}, "
        f"create_proposals=False, {universe_hint}; materie prime con scan_commodities_for_candidates "
        f"limit={scan_limit}, {universe_hint}; ETF con scan_etf_for_candidates limit={scan_limit}, {universe_hint}. "
        "Usa soltanto le short-list compatte restituite e non richiedere gli universi completi. "
        if run_market_scanners
        else
        "In questo ciclo intermedio non eseguire scanner FTSE MIB, materie prime o ETF: "
        "usa le condizioni già salvate. Gli scanner vengono eseguiti nel ciclo orario. "
    )
    return (
        "Esegui un ciclo periodico di monitoraggio operativo. "
        "Obiettivo: controllare posizioni aperte, proposte pending, condizioni monitorate e nuove opportunita da FTSE MIB e materie prime. "
        + operation_hint +
        "Prima chiama get_portfolio_operating_status e get_portfolio_performance. "
        "Se get_portfolio_performance mostra alert rilevanti su P/L posizione o portafoglio, chiama send_portfolio_performance_telegram. "
        "Se ci sono posizioni aperte, analizzale una alla volta con analyze_stock_chart; "
        f"{live_news_hint}. Se emergono segnali concreti di uscita, riduzione, protezione o presa profitto, usa analyze_stock_news "
        f"live={str(bool(live_news))} "
        f"e {'confirm_candidate_chart_with_playwright solo su titoli in portafoglio con decisione operativa concreta o segnale di uscita/riduzione/protezione' if live_news else 'non usare conferma grafica Playwright; resta su analisi tecnica locale/cache'}. "
        "Poi crea una proposta pending "
        "con create_position_action_proposal e applicala se la modalita autonoma virtuale e abilitata. "
        f"Poi rivaluta soltanto le {condition_limit} condizioni waiting a priorita piu alta con "
        f"evaluate_entry_scenarios limit={condition_limit}, "
        f"usando use_playwright={str(bool(live_news))}, live_news={str(bool(live_news))} "
        f"e max_playwright={deep_confirm_limit}. Questo tool fa prima filtri numerici e usa Playwright solo per scenari CONFIRMING. "
        "Se una condizione diventa met/BUY_CANDIDATE, decidi autonomamente se creare una proposta pending motivata e applicarla "
        "se la modalita autonoma virtuale e abilitata; puoi anche vendere o ridurre posizioni esistenti se il ribilanciamento e migliore. "
        "Poi controlla i titoli della watchlist manuale una alla volta con list_manual_watchlist; "
        "per i ticker prioritari o non analizzati di recente usa analyze_stock_chart; "
        f"{'usa news live via Playwright solo se il titolo e vicino a una decisione' if live_news else 'usa solo news in cache e non aprire Playwright'}. "
        "Se un titolo in watchlist ha entry_condition, verifica quella; se non ce l'ha, definisci una condizione di ingresso concreta "
        "usando esplicitamente scenario BREAKOUT oppure PULLBACK_SUPPORTO. "
        + ENTRY_SCENARIOS_GUIDE +
        "Se un titolo in watchlist diventa interessante, crea una condizione monitorata concreta o una proposta motivata. "
        + scanner_hint +
        "Se hai eseguito gli scanner, costruisci una short-list unica e molto breve, distinguendo FTSE MIB, materie prime ed ETF. "
        f"{'Non usare Playwright sui candidati appena usciti dallo scanner. Prima salva o aggiorna condizioni monitorate concrete; Playwright verra usato solo dalla rivalutazione trigger quando lo stato numerico diventa CONFIRMING/BUY_CANDIDATE.' if live_news else 'Non usare Playwright in questo ciclo: limita la valutazione dei candidati a scanner locale, condizioni salvate e cache news.'} "
        "Per le commodity agisci con prudenza: se un candidato e interessante ma non ancora confermato, preferisci salvare un trigger monitorato "
        "con scenario BREAKOUT o PULLBACK_SUPPORTO; crea e applica una proposta solo se tecnica, volumi e news disponibili non sono contrari. "
        "Se un candidato commodity e piu forte di una posizione in portafoglio, valuta ribilanciamento virtuale: reduce/sell della posizione debole "
        "e buy commodity, motivando confronto, rischio e impatto su cash/esposizione. "
        f"{'Budget Playwright massimo ' + str(deep_confirm_limit) + ': deve essere consumato solo da evaluate_entry_scenarios su condizioni in CONFIRMING/BUY_CANDIDATE, non dalla fase scanner.' if live_news else 'Per FTSE MIB e materie prime salva condizioni monitorate concrete quando servono, ma rimanda conferme Playwright a un ciclo con live_news abilitato.'} "
        "Se trovi candidati interessanti ma non ancora comprabili, salva condizioni concrete con record_monitored_condition. "
        "Concludi con una vista compatta: posizioni, proposte pending, condizioni monitorate, nuovi candidati, azioni consigliate. "
        "Se condizioni/proposte/stato sono cambiati, il runner inviera il riepilogo Telegram automatico."
    )


def build_periodic_monitor_request(
    scan_limit=5,
    universe_limit=0,
    live_news=True,
    deep_confirm_limit=3,
    auto_apply_virtual=False,
    max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT,
    condition_limit=DEFAULT_PERIODIC_CONDITION_LIMIT,
    run_market_scanners=True,
):
    scanner_step = (
        f"Esegui una volta i tre scanner locali con limit={scan_limit} e universe_limit={universe_limit}: "
        "FTSE MIB, materie prime ed ETF. Usa le short-list solo per salvare condizioni concrete; "
        "non approfondire i candidati scanner con Playwright in questo ciclo."
        if run_market_scanners
        else "Non eseguire scanner in questo ciclo intermedio."
    )
    autonomy_step = (
        f"Puoi applicare operazioni virtuali autorizzate, massimo {max_auto_trade_pct:.1f}% del cash per operazione."
        if auto_apply_virtual
        else "Crea solo proposte pending; non applicare operazioni."
    )
    news_step = (
        f"Consenti massimo {deep_confirm_limit} conferme Playwright/news, esclusivamente dentro "
        "evaluate_entry_scenarios per CONFIRMING/BUY_CANDIDATE o per una posizione con segnale concreto."
        if live_news
        else "Non usare Playwright; usa soltanto dati locali e news in cache."
    )
    return " ".join(
        [
            "Esegui un ciclo periodico compatto.",
            "1) Chiama get_portfolio_operating_status e get_portfolio_performance.",
            "2) Analizza con analyze_stock_chart al massimo tre posizioni: soltanto quelle con alert, forte variazione "
            "giornaliera o possibile uscita/protezione. Non analizzare tutte le posizioni.",
            "Usa analyze_stock_news solo se una di queste tre richiede davvero una decisione operativa.",
            f"3) Rivaluta al massimo {condition_limit} trigger con evaluate_entry_scenarios "
            f"limit={condition_limit}, use_playwright={bool(live_news)}, live_news={bool(live_news)}, "
            f"max_playwright={deep_confirm_limit}.",
            news_step,
            "4) Controlla la watchlist; approfondisci al massimo un ticker soltanto se vicino a una decisione.",
            f"5) {scanner_step}",
            f"6) {autonomy_step}",
            "Non chiamare tool Telegram: il runner gestisce news-evento e un solo riepilogo consolidato.",
            "Termina con massimo otto righe: azioni, proposte, alert e conteggi. Non aggiungere opzioni successive.",
        ]
    )


def run_periodic_monitor_loop(
    model,
    interval_minutes=DEFAULT_MONITOR_INTERVAL_MINUTES,
    scan_limit=5,
    universe_limit=0,
    live_news=True,
    deep_confirm_limit=3,
    auto_apply_virtual=False,
    max_auto_trade_pct=DEFAULT_MAX_AUTO_TRADE_PCT,
    periodic_max_turns=DEFAULT_PERIODIC_MAX_TURNS,
    once=False,
    skip_market_scanners=False,
):
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
    agent = build_agent(
        model=model,
        auto_apply_virtual=auto_apply_virtual,
        max_auto_trade_pct=max_auto_trade_pct,
        periodic=True,
    )
    interval_seconds = max(1, int(interval_minutes * 60))
    cycle = 1
    while True:
        run_market_scanners = datetime.now().minute < 15 and not skip_market_scanners
        log_step(
            "Ciclo monitor periodico "
            f"#{cycle} | interval_minutes={interval_minutes} scan_limit={scan_limit} "
            f"universe_limit={universe_limit} live_news={live_news} auto_apply_virtual={auto_apply_virtual} "
            f"condition_limit={DEFAULT_PERIODIC_CONDITION_LIMIT} scanners={'on' if run_market_scanners else 'off'}"
        )
        log_monitor_plan(
            scan_limit=scan_limit,
            universe_limit=universe_limit,
            live_news=live_news,
            deep_confirm_limit=deep_confirm_limit,
            auto_apply_virtual=auto_apply_virtual,
            max_auto_trade_pct=max_auto_trade_pct,
            condition_limit=DEFAULT_PERIODIC_CONDITION_LIMIT,
            run_market_scanners=run_market_scanners,
        )
        log_operational_snapshot("prima del ciclo")
        invalidated_liquidity = invalidate_illiquid_monitored_conditions()
        if invalidated_liquidity:
            log_step(f"Trigger invalidati per liquidita insufficiente: {len(invalidated_liquidity)}")
        mark_agent_run_started(
            mode="autonomous_virtual" if auto_apply_virtual else "periodic_monitor",
            interval_minutes=interval_minutes,
            scan_limit=scan_limit,
            universe_limit=universe_limit,
            live_news=live_news,
            auto_apply_virtual=auto_apply_virtual,
            cycle=cycle,
        )
        request = build_periodic_monitor_request(
            scan_limit=scan_limit,
            universe_limit=universe_limit,
            live_news=live_news,
            deep_confirm_limit=deep_confirm_limit,
            auto_apply_virtual=auto_apply_virtual,
            max_auto_trade_pct=max_auto_trade_pct,
            condition_limit=DEFAULT_PERIODIC_CONDITION_LIMIT,
            run_market_scanners=run_market_scanners,
        )
        try:
            before_state = monitoring_state_signature()
            before_portfolio_state = portfolio_content_signature()
            result = run_agent_once(
                agent,
                request,
                display_request=f"monitor periodico ciclo #{cycle}",
                suppress_auto_telegram_summary=True,
                max_turns=min(int(periodic_max_turns), 14),
            )
            exit_performance = calculate_portfolio_performance(record_history=False)
            exit_portfolio = load_portfolio_file()
            exit_rows = build_exit_conditions(exit_performance, exit_portfolio)
            exit_enforcement = enforce_triggered_exits(
                exit_rows,
                portfolio_id=os.getenv("ACTIVE_PORTFOLIO_ID") or "main",
            )
            if exit_enforcement.get("decisions"):
                log_step(
                    "Controllo deterministico stop completato | "
                    f"decisioni={len(exit_enforcement['decisions'])} "
                    f"vendite_applicate={exit_enforcement.get('applied_count', 0)} "
                    f"pending={exit_enforcement.get('pending_count', 0)}"
                )
            if os.getenv("MULTI_PORTFOLIO_CHILD") != "1":
                shared_evaluation = run_shared_portfolio_evaluation()
                shared_portfolios = shared_evaluation.get("portfolios", [])
                log_step(
                    "Analisi condivisa applicata ai portafogli attivi | "
                    f"run_id={shared_evaluation.get('run_id')} "
                    f"ticker_condivisi={shared_evaluation.get('shared_item_count', 0)} "
                    f"portafogli={len(shared_portfolios)} "
                    f"eleggibili={sum(int(item.get('eligible_count') or 0) for item in shared_portfolios)} "
                    f"nuovi_trigger={sum(int(item.get('created_conditions_count') or 0) for item in shared_evaluation.get('applications', []))}"
                )
                run_secondary_portfolio_cycles(
                    model=model,
                    interval_minutes=interval_minutes,
                    scan_limit=scan_limit,
                    universe_limit=universe_limit,
                    live_news=live_news,
                    deep_confirm_limit=deep_confirm_limit,
                    auto_apply_virtual=auto_apply_virtual,
                    max_auto_trade_pct=max_auto_trade_pct,
                    periodic_max_turns=periodic_max_turns,
                )
            auto_entry_decisions = process_autonomous_met_entry_conditions(
                auto_apply_virtual=auto_apply_virtual,
                max_auto_trade_pct=max_auto_trade_pct,
            )
            if auto_entry_decisions:
                applied_count = len([item for item in auto_entry_decisions if item.get("decision") == "applied_buy"])
                skipped_count = len([item for item in auto_entry_decisions if str(item.get("decision", "")).startswith("skip_")])
                log_step(
                    "Post-check autonomia ingressi completato | "
                    f"buy_applicati={applied_count} decisioni_skip={skipped_count}"
                )
            news_notifications = send_relevant_news_alerts()
            if news_notifications.get("sent"):
                log_step(
                    "News rilevanti inviate via Telegram | "
                    f"ticker={','.join(news_notifications['sent'])}"
                )
            elif news_notifications.get("status") == "partial_error":
                log_step(f"Invio news Telegram parziale | errori={news_notifications.get('errors')}")
            after_state = monitoring_state_signature()
            after_portfolio_state = portfolio_content_signature()
            log_operational_snapshot("dopo il ciclo")
            performance = calculate_portfolio_performance()
            has_alerts = bool(performance.get("alerts"))
            should_send, reason, telegram_settings = should_send_monitoring_summary(
                reason="scheduled",
                changed=before_state != after_state,
                portfolio_changed=before_portfolio_state != after_portfolio_state,
                has_alerts=has_alerts,
            )
            is_multi_portfolio_child = os.getenv("MULTI_PORTFOLIO_CHILD") == "1"
            if should_send and not is_multi_portfolio_child:
                log_step(f"Invio riepilogo Telegram fine ciclo | criterio={reason}")
                telegram_result = send_all_portfolios_summary(
                    extra_note=(
                        f"Fine ciclo schedulato #{cycle}. Criterio Telegram: "
                        f"{telegram_settings.get('monitoring_mode')} ({reason}). "
                        f"Prossimo controllo tra {interval_minutes} minuti."
                    )
                )
                if telegram_result.get("status") == "ok":
                    log_step("Riepilogo consolidato di tutti i portafogli inviato su Telegram")
                else:
                    log_step(
                        "Riepilogo Telegram fine ciclo non inviato: "
                        f"{telegram_result.get('message') or telegram_result.get('reason') or telegram_result.get('status')}"
                    )
            elif is_multi_portfolio_child:
                log_step(
                    "Riepilogo Telegram portfolio-specifico saltato: "
                    "verra incluso nel messaggio consolidato del ciclo principale"
                )
            else:
                log_step(f"Riepilogo Telegram fine ciclo saltato | criterio={reason}")
            mark_agent_run_completed(
                interval_minutes=interval_minutes,
                once=once,
                error=getattr(result, "interrupted_error", ""),
            )
        except Exception as exc:
            log_step(f"Errore durante il ciclo monitor: {exc.__class__.__name__}: {exc}")
            log_operational_snapshot("dopo errore")
            mark_agent_run_completed(interval_minutes=interval_minutes, once=once, error=str(exc))
            raise
        if once:
            log_step("Monitor periodico completato in modalita --once")
            return
        log_step(f"Prossimo ciclo tra {interval_minutes} minuti. Interrompi con CTRL+C.")
        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            print("\nMonitor periodico interrotto dall'utente.")
            return
        cycle += 1


def run_secondary_portfolio_cycles(
    model,
    interval_minutes,
    scan_limit,
    universe_limit,
    live_news,
    deep_confirm_limit,
    auto_apply_virtual,
    max_auto_trade_pct,
    periodic_max_turns,
):
    current_id = str(os.getenv("ACTIVE_PORTFOLIO_ID") or "main").strip().lower()
    portfolios = [
        item
        for item in list_portfolios(include_archived=False).get("items", [])
        if item.get("status") == "active" and item.get("id") != current_id
    ]
    if not portfolios:
        return []
    results = []
    for item in portfolios:
        portfolio_id = item["id"]
        command = [
            sys.executable,
            str(PROJECT_ROOT / "agent_portfolio_manager.py"),
            "--model",
            model,
            "--autonomous-monitor",
            "--once",
            "--skip-market-scanners",
            "--monitor-interval-minutes",
            str(interval_minutes),
            "--scan-limit",
            str(scan_limit),
            "--universe-limit",
            str(universe_limit),
            "--deep-confirm-limit",
            str(deep_confirm_limit),
            "--periodic-max-turns",
            str(periodic_max_turns),
            "--max-auto-trade-pct",
            str(max_auto_trade_pct),
        ]
        if live_news:
            command.append("--periodic-live-news")
        environment = {
            **os.environ,
            "ACTIVE_PORTFOLIO_ID": portfolio_id,
            "MULTI_PORTFOLIO_CHILD": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
        log_step(
            "Avvio valutazione portfolio-specifica senza nuovo scan | "
            f"portfolio_id={portfolio_id} nome={item.get('name')}"
        )
        try:
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=max(900, periodic_max_turns * 90),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log_step(
                "Timeout valutazione portfolio-specifica | "
                f"portfolio_id={portfolio_id} timeout={exc.timeout}s"
            )
            results.append(
                {
                    "portfolio_id": portfolio_id,
                    "returncode": -1,
                    "error": f"timeout dopo {exc.timeout}s",
                }
            )
            continue
        stdout_tail = "\n".join((completed.stdout or "").splitlines()[-20:])
        stderr_tail = "\n".join((completed.stderr or "").splitlines()[-10:])
        if stdout_tail:
            print(stdout_tail, flush=True)
        if stderr_tail:
            print(stderr_tail, file=sys.stderr, flush=True)
        result = {
            "portfolio_id": portfolio_id,
            "returncode": completed.returncode,
        }
        results.append(result)
        log_step(
            "Valutazione portfolio-specifica completata | "
            f"portfolio_id={portfolio_id} exit={completed.returncode}"
        )
    return results


def monitoring_state_signature():
    status = portfolio_status_summary()
    conditions = [
        {
            "id": item.get("id"),
            "ticker": item.get("ticker"),
            "status": item.get("status"),
            "condition": item.get("condition"),
            "action_if_met": item.get("action_if_met"),
        }
        for item in status.get("monitored_conditions", [])
    ]
    pending_buy = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "action": item.get("action"),
            "ticker": item.get("ticker"),
            "metadata": item.get("metadata", {}),
        }
        for item in status.get("pending_buy_proposals", [])
    ]
    pending_other = [
        {
            "id": item.get("id"),
            "status": item.get("status"),
            "action": item.get("action"),
            "ticker": item.get("ticker"),
            "metadata": item.get("metadata", {}),
        }
        for item in status.get("pending_other_proposals", [])
    ]
    positions = [
        {
            "ticker": item.get("ticker"),
            "status": item.get("status"),
            "allocated_amount": item.get("allocated_amount"),
            "entry_price": item.get("entry_price"),
            "virtual_quantity": item.get("virtual_quantity"),
        }
        for item in status.get("positions", [])
    ]
    relevant_state = {
        "pending_buy_proposals": pending_buy,
        "pending_other_proposals": pending_other,
        "monitored_conditions": conditions,
        "positions": positions,
        "cash": status.get("cash"),
    }
    return json.dumps(relevant_state, ensure_ascii=False, sort_keys=True)


def portfolio_content_signature():
    status = portfolio_status_summary()
    positions = sorted(
        [
            {
                "ticker": str(item.get("ticker") or "").strip().upper(),
                "status": item.get("status"),
                "virtual_quantity": item.get("virtual_quantity"),
                "allocated_amount": item.get("allocated_amount"),
            }
            for item in status.get("positions", [])
            if item.get("status") == "open"
        ],
        key=lambda item: item["ticker"],
    )
    return json.dumps(positions, ensure_ascii=False, sort_keys=True)


def maybe_send_automatic_monitoring_summary(
    request,
    final_output,
    before_state,
    after_state,
    before_portfolio_state,
    after_portfolio_state,
):
    changed = before_state != after_state
    portfolio_changed = before_portfolio_state != after_portfolio_state
    should_send, reason, telegram_settings = should_send_monitoring_summary(
        reason="automatic",
        changed=changed,
        portfolio_changed=portfolio_changed,
        has_alerts=False,
    )
    if not should_send:
        log_step(
            "Riepilogo Telegram automatico saltato | "
            f"modalita={telegram_settings.get('monitoring_mode')} motivo={reason}"
        )
        return

    combined = f"{request}\n{final_output}".lower()
    trigger_words = [
        "mib30",
        "scanner",
        "screening",
        "rivaluta",
        "monitor",
        "condizioni",
        "proposta",
        "compra",
        "acquista",
    ]
    if not any(word in combined for word in trigger_words):
        return

    log_step(
        "Cambio monitoraggio/proposte rilevato: invio riepilogo Telegram automatico | "
        f"modalita={telegram_settings.get('monitoring_mode')} motivo={reason}"
    )
    result = send_monitoring_summary(
        extra_note=(
            "Riepilogo automatico dopo aggiornamento monitoraggio/proposte. "
            f"Criterio: {telegram_settings.get('monitoring_mode')} ({reason})."
        )
    )
    if result.get("status") == "ok":
        log_step("Riepilogo Telegram automatico inviato")
    else:
        log_step(f"Riepilogo Telegram non inviato: {result.get('message')}")


def build_contextual_request(history, user_text, max_turns=6):
    recent_history = history[-max_turns:]
    resolver_context = resolve_ticker_context(user_text, history=recent_history)
    if not recent_history:
        if resolver_context:
            return "\n".join([resolver_context, "", "Richiesta utente:", user_text])
        return user_text

    lines = [
        "Questa e una sessione interattiva. Usa il contesto recente per risolvere riferimenti come "
        "'questi titoli', 'i candidati', 'il precedente elenco', 'la proposta'.",
        "",
        "Contesto recente:",
    ]
    for item in recent_history:
        lines.append(f"Utente: {item['user']}")
        lines.append(f"Agente: {item['assistant']}")
        lines.append("")
    if resolver_context:
        lines.append(resolver_context)
        lines.append("")
    lines.append("Nuova richiesta utente:")
    lines.append(user_text)
    return "\n".join(lines)


def extract_next_options(text):
    lines = str(text or "").splitlines()
    options = []
    in_section = False
    for line in lines:
        clean = line.strip()
        if not clean:
            if in_section and options:
                break
            continue
        header = clean.lstrip("#").strip().lower()
        if header.startswith("opzioni successive"):
            in_section = True
            continue
        if not in_section:
            continue
        match = re.match(r"^\d+[\.\)]\s+`?(.+?)`?\s*$", clean)
        if match:
            option = match.group(1).strip().strip("`").strip()
            if option:
                options.append(option)
            continue
        if options:
            break
    return options


def print_monitored_conditions_quick():
    conditions = list_monitored_conditions(status=None)
    if not conditions:
        print("Nessun titolo sotto monitoring.")
        return
    print()
    print("Titoli sotto monitoring:")
    for item in conditions:
        print(
            f"- {item.get('ticker')} | stato={item.get('status')} | "
            f"condizione={item.get('condition')} | azione={item.get('action_if_met')}"
        )


def parse_italian_amount(value):
    clean = value.strip().lower().replace("euro", "").replace("eur", "").replace("€", "")
    clean = clean.replace(" ", "")
    if "," in clean and "." in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif "," in clean:
        clean = clean.replace(",", ".")
    elif "." in clean:
        parts = clean.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            clean = "".join(parts)
    return float(clean)


def handle_local_interactive_command(user_text):
    text = user_text.strip()
    lower = text.lower()

    capital_match = re.search(
        r"\b(?:capitale(?:\s+disponibile)?|aggiorna\s+il\s+capitale|il\s+capitale\s+(?:e|è))\D+([0-9][0-9\., ]*)",
        lower,
    )
    if capital_match:
        amount = parse_italian_amount(capital_match.group(1))
        result = update_portfolio_capital(amount, reason=f"richiesta esplicita utente: {text}")
        print()
        print(f"Capitale virtuale aggiornato: EUR {result['old_capital']:.2f} -> EUR {result['new_capital']:.2f}")
        print(f"Liquidita aggiornata: EUR {result['old_cash']:.2f} -> EUR {result['new_cash']:.2f}")
        return True

    buy_intent = re.search(r"\b(compra|compriamo|acquista|acquistiamo|procedi|procediamo)\b", text, flags=re.IGNORECASE)
    ticker_match = re.search(r"\b([A-Z0-9]{1,8}\.[A-Z]{1,4})\b", text, flags=re.IGNORECASE)
    resolved_ticker = resolve_ticker(text)
    if buy_intent and resolved_ticker:
        ticker = resolved_ticker
        amount_area = text[: ticker_match.start()] if ticker_match else text
        amount_candidates = re.findall(r"[0-9][0-9\., ]*", amount_area)
        if not amount_candidates:
            print("Importo non trovato. Esempio: compriamo 10000 euro di Amplifon")
            return True
        amount = parse_italian_amount(amount_candidates[-1])
        portfolio = load_portfolio_file()
        if portfolio is None:
            print("portfolio.json non esiste. Prima inizializza o imposta il capitale virtuale.")
            return True
        cash = float(portfolio.get("cash", 0) or 0)
        if amount > cash:
            print(f"Liquidita insufficiente: richiesta EUR {amount:.2f}, cash disponibile EUR {cash:.2f}.")
            return True
        reason = (
            f"Richiesta esplicita utente: proposta acquisto EUR {amount:.2f} di {ticker}. "
            "Forzatura consapevole: la proposta puo essere creata anche se il filtro prudenziale non e confermato. "
            "Richiede conferma esplicita del proposal_id."
        )
        proposal = add_buy_proposal(ticker=ticker, reason=reason, amount=amount)
        print()
        print("Proposta pending creata su richiesta esplicita.")
        print(f"- proposal_id: {proposal['id']}")
        print(f"- ticker: {ticker}")
        print(f"- importo: EUR {amount:.2f}")
        print("Nessun acquisto applicato: per eseguire devi confermare il proposal_id.")
        should_send, telegram_reason, telegram_settings = should_send_monitoring_summary(
            reason="automatic",
            changed=True,
            portfolio_changed=False,
            has_alerts=False,
        )
        if should_send:
            result = send_monitoring_summary(
                extra_note=(
                    "Riepilogo automatico dopo proposta pending creata da comando esplicito. "
                    f"Criterio: {telegram_settings.get('monitoring_mode')} ({telegram_reason})."
                )
            )
            if result.get("status") == "ok":
                print("Riepilogo monitoraggio inviato su Telegram.")
            else:
                print(f"Telegram non inviato: {result.get('message')}")
        else:
            print(
                "Riepilogo Telegram saltato per configurazione: "
                f"{telegram_settings.get('monitoring_mode')} ({telegram_reason})."
            )
        return True

    if lower in {
        "invia riepilogo telegram",
        "manda riepilogo telegram",
        "telegram monitoring",
        "invia monitoraggio telegram",
    }:
        result = send_monitoring_summary(extra_note="Invio manuale richiesto dall'utente.")
        print()
        if result.get("status") == "ok":
            print("Riepilogo monitoraggio inviato su Telegram.")
        else:
            print(f"Telegram non inviato: {result.get('message')}")
        return True

    return False


def build_startup_options(portfolio):
    options = []
    if portfolio is None:
        options.append("inizializza portafoglio con capitale 20000 euro")
    else:
        options.append("mostra stato operativo del portafoglio")
        conditions = [item for item in portfolio.get("monitored_conditions", []) if item.get("status") == "waiting"]
        pending = [item for item in portfolio.get("pending_proposals", []) if item.get("status") == "pending"]
        positions = [item for item in portfolio.get("positions", []) if item.get("status") == "open"]
        if conditions:
            options.append("rivaluta le condizioni monitorate")
        if pending:
            first_id = pending[0].get("id", "<proposal_id>")
            options.append(f"mostra proposte pending e dettagli proposta {first_id}")
        if positions:
            options.append("rivaluta i titoli in portafoglio e proponi eventuali azioni")
        if not positions:
            options.append("scannerizza il FTSE MIB e cerca candidati per il portafoglio")

    options.extend(
        [
            "analizza un titolo specifico con grafico e news live",
            "cerca news live per un ticker",
        ]
    )
    return options[:6]


def print_next_options(portfolio=None):
    print()
    print("Opzioni successive:")
    options = build_startup_options(portfolio)
    for index, option in enumerate(options, start=1):
        print(f"{index}. {option}")
    return options


def print_interactive_help(portfolio=None):
    print()
    print("Cosa posso fare:")
    print("- creare un portafoglio virtuale partendo da capitale iniziale")
    print("- scannerizzare i titoli FTSE MIB e trovare candidati interessanti")
    print("- decidere se confermare i candidati migliori con analisi visuale grafici via Playwright/ChatGPT")
    print("- proporre acquisti/vendite/ribilanciamenti oppure applicarli se avviato in modalita autonoma virtuale")
    print("- salvare condizioni non ancora verificate e rivalutarle nei controlli successivi")
    print("- mostrare una vista unica con portafoglio, proposte, condizioni monitorate e watchlist")
    print("- aggiornare il capitale virtuale quando lo dichiari esplicitamente")
    print("- mostrare, confermare o rifiutare proposte pending")
    print("- analizzare uno o piu titoli con grafici tecnici")
    print("- cercare news live tramite Playwright/ChatGPT se Chrome e aperto con debug remoto")
    print("- inviare riepilogo Telegram dei titoli monitorati e proposte pending")
    print("- avviare un monitor periodico che controlla portafoglio, condizioni e FTSE MIB")
    print("- avviare un monitor periodico autonomo virtuale che applica decisioni e notifica via Telegram")
    print()
    print("Comandi esempio:")
    print("- cosa posso fare adesso?")
    print("- scannerizza 3 titoli del FTSE MIB e dimmi i migliori")
    print("- il portafoglio e vuoto, voglio investire 10000 euro")
    print("- crea una proposta di portafoglio con 5 titoli e 15% cash")
    print("- mostra proposte pending")
    print("- mostra condizioni da monitorare")
    print("- titoli monitorati")
    print("- mostra stato operativo del portafoglio")
    print("- aggiorna il capitale a 20000 euro")
    print("- conferma proposta 20260723-203433")
    print("- analizza VOD.L con news live")
    print("- invia riepilogo telegram")
    print("- monitor periodico ogni 30 minuti: usa da CLI --daemon-monitor --monitor-interval-minutes 30")
    print("- monitor autonomo virtuale: usa da CLI --autonomous-monitor")
    print()
    print("Regola operativa: in modalita interattiva chiedo conferma; in --autonomous-monitor opero sul portafoglio virtuale e notifico via Telegram.")
    print("Scrivi 'aiuto' per rivedere questa guida, oppure 'esci' per terminare.")
    return print_next_options(portfolio)


def run_interactive_loop(model):
    log_step("Modalita interattiva attiva")
    print("Ciao, sono Autonomous Trading Agent.")
    print("Ti aiuto a costruire e monitorare un portafoglio virtuale con trading automatico, analisi tecnica e news.")
    portfolio = load_portfolio_file()
    if portfolio is None or not portfolio.get("positions"):
        print()
        print("Stato iniziale: il portafoglio non ha posizioni aperte.")
        print("Per partire puoi scrivere, ad esempio: il portafoglio e vuoto, voglio investire 10000 euro")
    current_options = print_interactive_help(portfolio)
    agent = build_agent(model=model)
    history = []
    while True:
        try:
            user_text = input("\nTu> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nUscita dalla modalita interattiva.")
            return
        user_text = user_text.lstrip("\ufeffï»¿")
        if not user_text:
            continue
        if user_text.lower() in {"esci", "exit", "quit", "q"}:
            print("Uscita dalla modalita interattiva.")
            return
        if user_text.lower() in {"aiuto", "help", "?"}:
            current_options = print_interactive_help(load_portfolio_file())
            continue
        if user_text.lower() in {
            "monitoring veloce",
            "titoli monitorati",
            "titoli sotto monitoring",
            "mostra titoli monitorati",
            "mostra condizioni veloci",
        }:
            print_monitored_conditions_quick()
            current_options = print_next_options(load_portfolio_file())
            continue
        if user_text.isdigit():
            option_index = int(user_text)
            if 1 <= option_index <= len(current_options):
                selected_option = current_options[option_index - 1]
                print(f"Opzione selezionata: {selected_option}")
                user_text = selected_option
            else:
                print(f"Opzione {option_index} non disponibile. Scrivi 'aiuto' per vedere le opzioni.")
                continue
        if handle_local_interactive_command(user_text):
            current_options = print_next_options(load_portfolio_file())
            continue
        contextual_request = build_contextual_request(history, user_text)
        result = run_agent_once(agent, contextual_request, display_request=user_text)
        history.append(
            {
                "user": user_text,
                "assistant": str(result.final_output).strip(),
            }
        )
        response_options = extract_next_options(str(result.final_output))
        current_options = response_options or build_startup_options(load_portfolio_file())


def main():
    global DEFAULT_MODEL, DEFAULT_MAX_TURNS, DEFAULT_PERIODIC_MAX_TURNS
    global DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_PERIODIC_CONDITION_LIMIT
    configure_stdout()
    load_env_file()
    DEFAULT_MODEL = os.getenv("OPENAI_AGENT_MODEL", DEFAULT_MODEL)
    DEFAULT_MAX_TURNS = int(os.getenv("OPENAI_AGENT_MAX_TURNS", str(DEFAULT_MAX_TURNS)))
    DEFAULT_PERIODIC_MAX_TURNS = int(os.getenv("OPENAI_PERIODIC_MAX_TURNS", str(DEFAULT_PERIODIC_MAX_TURNS)))
    DEFAULT_MAX_OUTPUT_TOKENS = int(
        os.getenv("OPENAI_AGENT_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))
    )
    DEFAULT_PERIODIC_CONDITION_LIMIT = int(
        os.getenv("OPENAI_PERIODIC_CONDITION_LIMIT", str(DEFAULT_PERIODIC_CONDITION_LIMIT))
    )
    parser = argparse.ArgumentParser(description="Agente OpenAI SDK per watchlist e analisi titoli.")
    parser.add_argument(
        "request",
        nargs="?",
        default="Analizza VOD.L usando analisi tecnica e news disponibili.",
        help="Richiesta da inviare all'agente.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Modello OpenAI da usare.")
    parser.add_argument(
        "--suppress-auto-telegram-summary",
        action="store_true",
        help="Non inviare riepiloghi Telegram automatici a fine run; utile per richieste arrivate da Telegram.",
    )
    parser.add_argument("--interactive", action="store_true", help="Avvia una sessione interattiva con l'agente.")
    parser.add_argument("--stocks", default="", help='Ticker separati da virgola, es. "VOD.L,A2A.MI,AVIO.MI".')
    parser.add_argument("--live-news", action="store_true", help="Permetti al news tool di usare Playwright live.")
    parser.add_argument("--init-portfolio", action="store_true", help="Crea portfolio.json con capitale iniziale.")
    parser.add_argument("--capital", type=float, default=None, help="Capitale iniziale del portafoglio virtuale.")
    parser.add_argument("--overwrite-portfolio", action="store_true", help="Ricrea portfolio.json se esiste gia.")
    parser.add_argument("--scan-mib30", action="store_true", help="Scannerizza il FTSE MIB e chiedi all'agente una sintesi.")
    parser.add_argument("--scan-limit", type=int, default=5, help="Numero massimo candidati FTSE MIB.")
    parser.add_argument(
        "--daemon-monitor",
        action="store_true",
        help="Avvia monitoraggio periodico di portafoglio, condizioni e FTSE MIB.",
    )
    parser.add_argument(
        "--autonomous-monitor",
        action="store_true",
        help="Avvia monitoraggio autonomo virtuale periodico: applica decisioni simulate e notifica via Telegram.",
    )
    parser.add_argument(
        "--monitor-interval-minutes",
        type=int,
        default=DEFAULT_MONITOR_INTERVAL_MINUTES,
        help="Intervallo in minuti tra un ciclo periodico e il successivo.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Esegue un solo ciclo nelle modalita periodiche/test e poi termina.",
    )
    parser.add_argument(
        "--periodic-live-news",
        action="store_true",
        help="Nel monitor periodico consente news live via Playwright per casi rilevanti.",
    )
    parser.add_argument(
        "--auto-apply-virtual",
        action="store_true",
        help="Permette al monitor periodico di applicare autonomamente operazioni simulate sul portafoglio virtuale.",
    )
    parser.add_argument(
        "--max-auto-trade-pct",
        type=float,
        default=DEFAULT_MAX_AUTO_TRADE_PCT,
        help="Percentuale massima del cash usabile per una nuova operazione autonoma virtuale.",
    )
    parser.add_argument(
        "--deep-chart-confirmation",
        action="store_true",
        help="Forza conferma dei migliori candidati con analisi grafica Playwright/ChatGPT.",
    )
    parser.add_argument(
        "--no-auto-deep-confirmation",
        action="store_true",
        help="Disattiva la scelta autonoma dell'agente di approfondire candidati con Playwright.",
    )
    parser.add_argument(
        "--deep-confirm-limit",
        type=int,
        default=3,
        help="Numero massimo di candidati da confermare con Playwright/ChatGPT.",
    )
    parser.add_argument(
        "--periodic-max-turns",
        type=int,
        default=DEFAULT_PERIODIC_MAX_TURNS,
        help="Limite massimo di tool/reasoning turn per il monitor periodico.",
    )
    parser.add_argument(
        "--universe-limit",
        type=int,
        default=0,
        help="Solo per test: analizza al massimo N ticker dell'universo FTSE MIB.",
    )
    parser.add_argument(
        "--skip-market-scanners",
        action="store_true",
        help="Riusa le cache scanner condivise e valuta solo il portafoglio attivo.",
    )
    parser.add_argument(
        "--build-empty-portfolio",
        action="store_true",
        help="Se il portafoglio e vuoto, chiedi capitale e crea proposta allocazione FTSE MIB pending.",
    )
    parser.add_argument("--cash-pct", type=float, default=15, help="Percentuale da lasciare cash nella proposta.")
    parser.add_argument(
        "--create-proposals",
        action="store_true",
        help="Durante lo scan crea proposte pending, da confermare esplicitamente.",
    )
    args = parser.parse_args()
    log_step("Avvio Autonomous Trading Agent")
    log_step(f"Working directory: {PROJECT_ROOT}")

    if args.autonomous_monitor:
        args.daemon_monitor = True
        args.auto_apply_virtual = True

    if args.daemon_monitor:
        mode = "autonomo virtuale" if args.auto_apply_virtual else "solo proposte"
        log_step(f"Modalita monitor periodico attiva | mode={mode}")
        run_periodic_monitor_loop(
            model=args.model,
            interval_minutes=args.monitor_interval_minutes,
            scan_limit=args.scan_limit,
            universe_limit=args.universe_limit,
            live_news=args.periodic_live_news,
            deep_confirm_limit=args.deep_confirm_limit,
            auto_apply_virtual=args.auto_apply_virtual,
            max_auto_trade_pct=args.max_auto_trade_pct,
            periodic_max_turns=args.periodic_max_turns,
            once=args.once,
            skip_market_scanners=args.skip_market_scanners,
        )
        return

    if args.interactive:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
        run_interactive_loop(args.model)
        return

    if args.init_portfolio:
        capital = args.capital
        if capital is None:
            capital_text = input("Capitale iniziale portafoglio virtuale: ").strip().replace(",", ".")
            capital = float(capital_text)
        log_step(f"Inizializzo portafoglio virtuale | capital={capital} overwrite={args.overwrite_portfolio}")
        result = init_portfolio(capital, overwrite=args.overwrite_portfolio)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.build_empty_portfolio:
        capital = args.capital
        portfolio = load_portfolio_file()
        is_empty = portfolio is None or not portfolio.get("positions")
        if not is_empty:
            print("Il portafoglio contiene gia posizioni. Uso --scan-mib30 per analisi o conferme.")
            return
        if capital is None:
            capital_text = input("Il portafoglio e vuoto. Quanto vuoi investire nel portafoglio virtuale? ").strip()
            capital = float(capital_text.replace(",", "."))
        log_step(f"Portafoglio vuoto: preparo proposta iniziale | capital={capital}")
        init_portfolio(capital, overwrite=portfolio is None)
        request = (
            f"Il portafoglio e vuoto e l'utente vuole investire {capital:.2f} EUR. "
            f"Usa propose_virtual_portfolio_from_mib30 con max_positions={args.scan_limit} "
            f"cash_pct={args.cash_pct} e universe_limit={args.universe_limit}. "
        )
        if args.deep_chart_confirmation:
            request += (
                f"Prima di presentare la proposta finale, conferma i primi {args.deep_confirm_limit} "
                "candidati migliori con confirm_candidate_chart_with_playwright(no_telegram=True, reason=...). "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Se la conferma visuale smentisce un candidato, dichiaralo e riduci la convinzione. "
            )
        elif not args.no_auto_deep_confirmation:
            request += (
                f"Prima di presentare la proposta finale, valuta autonomamente i migliori candidati e, "
                f"se serve conferma o se stai allocando capitale, approfondisci fino a {args.deep_confirm_limit} "
                "candidati con confirm_candidate_chart_with_playwright(no_telegram=True, reason=...). "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Riporta quali candidati hai approfondito e quali no, con motivazione. "
            )
        request += (
            "Presenta la proposta pending generata, con importi, percentuali, motivazioni e rischi. "
            "Per ogni candidato analizzato assegna uno stato: BUY CANDIDATE, WAIT/MONITOR o SCARTATO. "
            "Se lo stato e WAIT/MONITOR, salva almeno una condizione concreta con record_monitored_condition. "
            "Ricorda che serve conferma esplicita del proposal_id prima di applicarla."
        )
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")
        agent = build_agent(model=args.model)
        run_agent_once(agent, request, suppress_auto_telegram_summary=args.suppress_auto_telegram_summary)
        return

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY non trovata. Aggiungila al file .env o alle variabili ambiente.")

    request = args.request
    if args.scan_mib30:
        log_step(
            f"Modalita scan FTSE MIB | scan_limit={args.scan_limit} "
            f"universe_limit={args.universe_limit} create_proposals={args.create_proposals}"
        )
        if args.deep_chart_confirmation:
            log_step(f"Conferma grafica Playwright attiva | top={args.deep_confirm_limit}")
        elif not args.no_auto_deep_confirmation:
            log_step(f"Conferma grafica Playwright autonoma consentita | max={args.deep_confirm_limit}")
        proposal_hint = (
            "crea proposte pending per i migliori candidati"
            if args.create_proposals
            else "non creare proposte, mostra solo candidati"
        )
        request = (
            f"Carica il portafoglio virtuale e scannerizza il FTSE MIB con limite {args.scan_limit}; "
            f"usa universe_limit={args.universe_limit}; "
            f"{proposal_hint}. "
        )
        if args.deep_chart_confirmation:
            request += (
                f"Dopo lo scan devi confermare i primi {args.deep_confirm_limit} candidati migliori "
                "chiamando confirm_candidate_chart_with_playwright con no_telegram=True e reason compilato per ciascuno. "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Solo dopo questa conferma visuale puoi indicare quali metteresti in proposta. "
            )
        elif not args.no_auto_deep_confirmation:
            request += (
                f"Dopo lo scan valuta autonomamente se approfondire fino a {args.deep_confirm_limit} candidati "
                "con confirm_candidate_chart_with_playwright(no_telegram=True, reason=...). "
                "Se il risultato deve diventare una proposta o una raccomandazione operativa, approfondisci i migliori candidati. "
                "Lavora un ticker alla volta: completa approfondimento e giudizio del primo candidato prima di passare al secondo. "
                "Se non lo fai, spiega chiaramente perche lo score numerico e sufficiente. "
            )
        request += (
            "Spiega i criteri tecnici, elenca i candidati migliori, riporta per ogni candidato se la conferma "
            "Playwright e stata fatta o no, e indica quali metteresti in proposta. "
            "Per ogni candidato assegna uno stato: BUY CANDIDATE, WAIT/MONITOR o SCARTATO. "
            "Se una condizione d'acquisto non e verificata ma il titolo resta interessante, "
            "salvala con record_monitored_condition."
        )
    if args.stocks:
        log_step(f"Modalita analisi titoli | stocks={args.stocks} live_news={args.live_news}")
        live_hint = "usa live=True per le news" if args.live_news else "usa live=False per le news"
        request = (
            f"Analizza questi titoli: {args.stocks}. "
            f"Per ciascun titolo chiama analyze_stock_chart e analyze_stock_news; {live_hint}. "
            "Poi produci una sintesi comparativa con rischio, momentum, news disponibili e priorita di monitoraggio."
        )

    request = build_contextual_request([], request)
    agent = build_agent(model=args.model)
    run_agent_once(agent, request, suppress_auto_telegram_summary=args.suppress_auto_telegram_summary)


if __name__ == "__main__":
    main()
