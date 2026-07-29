import json
from datetime import datetime
from pathlib import Path

from finance_tools.chart_tool import generate_chart_context, generate_snapshot_context
from finance_tools.autonomy_settings import autonomous_action_allowed
from finance_tools.common import PROJECT_ROOT
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai
from finance_tools.news_tool import get_news_report
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.portfolio_store import (
    PORTFOLIO_FILE,
    add_position_action_proposal,
    confirm_proposal,
    load_portfolio,
)
from finance_tools.telegram_tool import send_telegram_message


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(message):
    print(f"{_now()} [portfolio-deep] {message}", flush=True)


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _compact_text(text, limit=1100):
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rsplit(" ", 1)[0] + "..."


def _read_file(path):
    file_path = Path(path) if path else None
    if not file_path:
        return ""
    if not file_path.is_absolute():
        file_path = PROJECT_ROOT / file_path
    if not file_path.exists():
        return ""
    return file_path.read_text(encoding="utf-8", errors="replace")


def _find_perf_row(performance, ticker):
    symbol = str(ticker or "").strip().upper()
    for item in performance.get("positions", []):
        if str(item.get("ticker", "")).strip().upper() == symbol:
            return item
    return {}


def _classify_position(ticker, position, performance_row, snapshot, chart_report, news_report):
    pnl_pct = _safe_float(performance_row.get("pnl_pct"))
    daily_pct = _safe_float(performance_row.get("daily_change_pct"))
    close = _safe_float(snapshot.get("close") or performance_row.get("current_price"))
    entry = _safe_float(position.get("entry_price") or performance_row.get("entry_price"))
    rsi = _safe_float(snapshot.get("rsi"))
    macd = _safe_float(snapshot.get("macd"))
    macd_signal = _safe_float(snapshot.get("macd_signal"))
    adx = _safe_float(snapshot.get("adx"))
    plus_di = _safe_float(snapshot.get("plus_di"))
    minus_di = _safe_float(snapshot.get("minus_di"))
    support = _safe_float(snapshot.get("support_10") or snapshot.get("support_30"))
    resistance = _safe_float(snapshot.get("resistance_10") or snapshot.get("resistance_30"))
    volume = _safe_float(snapshot.get("volume"))
    volume_ma10 = _safe_float(snapshot.get("volume_ma10"))
    volume_ratio = (volume / volume_ma10) if volume_ma10 else None

    combined_text = f"{chart_report}\n{news_report}".lower()
    negative_words = [
        "downgrade",
        "target price tagliato",
        "rating sell",
        "profit warning",
        "guidance tagliata",
        "risultati sotto",
        "multa",
        "indagine",
        "notizie negative",
        "scenario negativo",
    ]
    positive_words = [
        "upgrade",
        "target price alzato",
        "rating buy",
        "risultati sopra",
        "guidance alzata",
        "notizie positive",
        "scenario positivo",
    ]
    has_negative_news = any(word in combined_text for word in negative_words)
    has_positive_news = any(word in combined_text for word in positive_words)
    macd_bearish = macd < macd_signal
    trend_bearish = minus_di > plus_di and adx >= 20
    overbought = rsi >= 72
    near_resistance = resistance and close and ((resistance / close - 1) * 100) <= 2.0
    near_support = support and close and ((close / support - 1) * 100) <= 2.5

    action = "mantieni"
    percent = 0
    priority = "normale"
    reasons = []

    if has_negative_news and (pnl_pct <= 0 or daily_pct <= -1):
        action = "riduci"
        percent = 50
        priority = "alta"
        reasons.append("news/lettura AI negativa con prezzo debole")
    if pnl_pct <= -6 or (support and close and close < support):
        action = "vendi"
        percent = 100
        priority = "alta"
        reasons.append("perdita ampia o supporto operativo violato")
    elif pnl_pct <= -3 and (macd_bearish or trend_bearish):
        action = "riduci"
        percent = max(percent, 50)
        priority = "media"
        reasons.append("P/L negativo con conferme tecniche deboli")
    elif pnl_pct >= 6 and (overbought or near_resistance):
        action = "riduci"
        percent = max(percent, 30)
        priority = "media"
        reasons.append("presa profitto parziale: titolo esteso o vicino a resistenza")
    elif pnl_pct >= 2 and near_resistance and not has_positive_news:
        action = "proteggi"
        percent = 0
        priority = "normale"
        reasons.append("valutare stop dinamico/trailing stop vicino a resistenza")

    if action == "mantieni":
        if has_positive_news and not trend_bearish:
            reasons.append("news/lettura AI non negativa e quadro tecnico ancora costruttivo")
        elif near_support:
            reasons.append("vicino al supporto: mantenere solo se il supporto continua a reggere")
        else:
            reasons.append("nessun segnale operativo forte di uscita o riduzione")

    return {
        "ticker": ticker,
        "action": action,
        "percent": percent,
        "priority": priority,
        "reason": "; ".join(reasons),
        "reference_price": round(close, 4) if close else None,
        "levels": {
            "entry": round(entry, 4) if entry else None,
            "support": round(support, 4) if support else None,
            "resistance": round(resistance, 4) if resistance else None,
            "rsi": round(rsi, 2) if rsi else None,
            "adx": round(adx, 2) if adx else None,
            "volume_ma10_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
            "daily_change_pct": performance_row.get("daily_change_pct"),
            "pnl_pct": performance_row.get("pnl_pct"),
        },
    }


def _build_telegram_message(result):
    lines = [
        "Analisi approfondita portafoglio",
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        "",
        f"Posizioni analizzate: {len(result.get('items', []))}",
    ]
    for item in result.get("items", []):
        decision = item.get("decision", {})
        levels = decision.get("levels", {})
        action = decision.get("action", "n/d").upper()
        proposal = item.get("proposal")
        lines.extend(
            [
                "",
                f"{item.get('ticker')} - {action}",
                f"P/L: {levels.get('pnl_pct', 'n/d')}% | oggi: {levels.get('daily_change_pct', 'n/d')}%",
                f"Prezzo: {levels.get('reference_price') or decision.get('reference_price') or 'n/d'}",
                f"Supporto: {levels.get('support', 'n/d')} | Resistenza: {levels.get('resistance', 'n/d')}",
                f"Motivo: {_compact_text(decision.get('reason'), 260)}",
            ]
        )
        if proposal:
            lines.append(f"Proposta: {proposal.get('id')} {proposal.get('action')}")
    return "\n".join(lines)


def run_deep_portfolio_analysis(
    max_positions=10,
    create_proposals=False,
    auto_apply=False,
    send_telegram=False,
    use_playwright=True,
    live_news=True,
    period="1y",
    days=70,
    progress_callback=None,
    portfolio_path=None,
    portfolio_id="main",
):
    """Analyze only open portfolio positions with chart AI/news and action hints."""
    def progress(stage, message, ticker=None, current=None, total=None, percent=None):
        if progress_callback:
            progress_callback(
                {
                    "stage": stage,
                    "message": message,
                    "ticker": ticker,
                    "current": current,
                    "total": total,
                    "percent": percent,
                }
            )

    progress("starting", "Carico il portafoglio virtuale e le posizioni aperte.", percent=2)
    _log(
        "avvio analisi approfondita on demand | "
        f"solo_posizioni_portafoglio=True max_positions={max_positions} "
        f"use_playwright={use_playwright} live_news={live_news} "
        f"create_proposals={create_proposals} auto_apply={auto_apply}"
    )
    resolved_path = portfolio_path or PORTFOLIO_FILE
    portfolio = load_portfolio(resolved_path)
    if portfolio is None:
        progress("error", "Il file portfolio.json non esiste.", percent=100)
        return {"status": "missing_portfolio", "message": "portfolio.json non esiste.", "items": []}

    positions = [item for item in portfolio.get("positions", []) if item.get("status") == "open"]
    positions = positions[: max(1, int(max_positions or 1))]
    performance = calculate_portfolio_performance(
        resolved_path,
        record_history=False,
    )
    result = {
        "status": "ok",
        "mode": "portfolio_deep_on_demand",
        "portfolio_id": portfolio_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "only_open_positions": True,
        "create_proposals": bool(create_proposals),
        "auto_apply": bool(auto_apply),
        "items": [],
    }
    if not positions:
        result["summary"] = "Nessuna posizione aperta da analizzare."
        _log(result["summary"])
        progress("completed", result["summary"], current=0, total=0, percent=100)
        return result

    for index, position in enumerate(positions, start=1):
        ticker = str(position.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        base_percent = 5 + ((index - 1) / len(positions)) * 88
        ticker_span = 88 / len(positions)
        progress(
            "technical",
            f"{ticker}: scarico prezzi e preparo indicatori e grafici tecnici.",
            ticker=ticker,
            current=index,
            total=len(positions),
            percent=round(base_percent),
        )
        _log(f"{index}/{len(positions)} {ticker} - preparo dati tecnici")
        chart_context = generate_chart_context(ticker, days=days, period=period) if use_playwright else generate_snapshot_context(ticker, period=period)
        snapshot = chart_context.get("snapshot", {})

        chart_ai = {"status": "skipped", "report": "Playwright grafico disattivato per questa esecuzione."}
        if use_playwright:
            progress(
                "chart_ai",
                f"{ticker}: controllo cache grafico AI; se non recente uso Playwright/ChatGPT.",
                ticker=ticker,
                current=index,
                total=len(positions),
                percent=round(base_percent + ticker_span * 0.28),
            )
            _log(
                f"{ticker} - grafico AI richiesto: controllo cache recente, "
                "poi eventuale Playwright/ChatGPT"
            )
            chart_ai = confirm_candidate_with_chart_ai(ticker=ticker, no_telegram=True)
            if chart_ai.get("source") == "cached_playwright_chart_ai":
                progress(
                    "chart_ai_cached",
                    f"{ticker}: riuso analisi grafica AI recente, niente nuova chiamata Playwright.",
                    ticker=ticker,
                    current=index,
                    total=len(positions),
                    percent=round(base_percent + ticker_span * 0.4),
                )
                _log(f"{ticker} - grafico AI riusato da cache recente")
        chart_report = chart_ai.get("report") or _read_file(chart_ai.get("analysis_file"))

        news = {"status": "skipped", "report": "News live disattivate per questa esecuzione."}
        if live_news:
            progress(
                "news",
                f"{ticker}: controllo cache news; se non recente uso Playwright/ChatGPT.",
                ticker=ticker,
                current=index,
                total=len(positions),
                percent=round(base_percent + ticker_span * 0.58),
            )
            _log(
                f"{ticker} - news richieste: controllo cache recente, "
                "poi eventuale Playwright/ChatGPT"
            )
            news = get_news_report(ticker=ticker, live=True)
            if news.get("source") == "cached_live_file":
                progress(
                    "news_cached",
                    f"{ticker}: riuso report news recente, niente nuova chiamata Playwright.",
                    ticker=ticker,
                    current=index,
                    total=len(positions),
                    percent=round(base_percent + ticker_span * 0.7),
                )
                _log(f"{ticker} - news riusate da cache recente")
        news_report = news.get("report") or _read_file(news.get("file"))

        progress(
            "decision",
            f"{ticker}: integro indicatori, grafico, news e rischio della posizione.",
            ticker=ticker,
            current=index,
            total=len(positions),
            percent=round(base_percent + ticker_span * 0.82),
        )
        perf_row = _find_perf_row(performance, ticker)
        decision = _classify_position(ticker, position, perf_row, snapshot, chart_report, news_report)
        _log(
            f"{ticker} - decisione={decision['action']} percent={decision['percent']} "
            f"priorita={decision['priority']} motivo={decision['reason']}"
        )

        proposal = None
        applied = None
        if create_proposals and decision["action"] in {"riduci", "vendi"}:
            progress(
                "proposal",
                f"{ticker}: preparo la proposta operativa {decision['action']}.",
                ticker=ticker,
                current=index,
                total=len(positions),
                percent=round(base_percent + ticker_span * 0.9),
            )
            proposal = add_position_action_proposal(
                ticker=ticker,
                action_type="sell" if decision["action"] == "vendi" else "reduce",
                percent=decision["percent"],
                reference_price=decision["reference_price"],
                reason=f"Analisi approfondita on demand: {decision['reason']}",
                metadata={"source": "portfolio_deep_on_demand", "priority": decision["priority"]},
                path=resolved_path,
            )
            _log(f"{ticker} - proposta creata {proposal.get('id')} action={proposal.get('action')}")
            if auto_apply:
                allowed, autonomy_mode = autonomous_action_allowed(
                    proposal.get("action"),
                    portfolio_id=portfolio_id,
                )
                if allowed:
                    applied = confirm_proposal(
                        proposal["id"],
                        path=resolved_path,
                    )
                    _log(
                        f"{ticker} - proposta applicata automaticamente {proposal.get('id')} "
                        f"modalita={autonomy_mode}"
                    )
                else:
                    applied = {
                        "status": "blocked",
                        "portfolio_action_mode": autonomy_mode,
                        "message": "Applicazione automatica bloccata dalla configurazione Controlli.",
                    }
                    _log(
                        f"{ticker} - proposta lasciata pending: applicazione automatica "
                        f"non consentita in modalita={autonomy_mode}"
                    )

        result["items"].append(
            {
                "ticker": ticker,
                "position": position,
                "performance": perf_row,
                "snapshot": snapshot,
                "chart_files": chart_context.get("files", []),
                "chart_analysis_file": chart_ai.get("analysis_file"),
                "news_file": news.get("file"),
                "decision": decision,
                "proposal": proposal,
                "applied": applied,
                "chart_report_preview": _compact_text(chart_report, 800),
                "news_report_preview": _compact_text(news_report, 800),
            }
        )
        progress(
            "ticker_completed",
            f"{ticker}: analisi completata, decisione {decision['action'].upper()}.",
            ticker=ticker,
            current=index,
            total=len(positions),
            percent=round(base_percent + ticker_span),
        )

    actions = [item for item in result["items"] if item["decision"]["action"] != "mantieni"]
    result["summary"] = (
        f"Analizzate {len(result['items'])} posizioni aperte. "
        f"Indicazioni operative: {len(actions)}. "
        + (
            ", ".join(f"{item['ticker']}={item['decision']['action']}" for item in actions)
            if actions
            else "Nessuna azione immediata suggerita."
        )
    )
    _log(result["summary"])

    if send_telegram:
        progress("telegram", "Invio il riepilogo dell'analisi su Telegram.", percent=96)
        _log("invio riepilogo Telegram analisi approfondita portafoglio")
        result["telegram"] = send_telegram_message(_build_telegram_message(result))
    progress("completed", result["summary"], current=len(result["items"]), total=len(positions), percent=100)
    return result


def run_deep_portfolio_analysis_json(**kwargs):
    return json.dumps(run_deep_portfolio_analysis(**kwargs), ensure_ascii=False, indent=2)
