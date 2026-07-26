import os
from datetime import datetime

from finance_tools.chart_tool import generate_snapshot_context
from finance_tools.commodity_scanner import load_commodity_tickers
from finance_tools.etf_scanner import load_etf_tickers
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai
from finance_tools.liquidity import liquidity_metrics
from finance_tools.news_tool import get_news_report
from finance_tools.portfolio_store import (
    add_monitored_condition,
    list_monitored_conditions,
    load_portfolio,
    update_monitored_condition,
)


MIN_MONITOR_SCORE = 5
BREAKOUT_NEAR_PCT = float(os.getenv("BREAKOUT_NEAR_PCT", "3"))
PULLBACK_ENTRY_DISTANCE_PCT = float(os.getenv("PULLBACK_ENTRY_DISTANCE_PCT", "2.5"))
PULLBACK_STOP_BUFFER_PCT = float(os.getenv("PULLBACK_STOP_BUFFER_PCT", "1.2"))
MIN_CONFIRM_VOLUME_RATIO = float(os.getenv("MIN_CONFIRM_VOLUME_RATIO", "0.8"))

SCENARIO_WAIT = "WAIT"
SCENARIO_NEAR_TRIGGER = "NEAR_TRIGGER"
SCENARIO_CONFIRMING = "CONFIRMING"
SCENARIO_BUY_CANDIDATE = "BUY_CANDIDATE"
SCENARIO_BOUGHT = "BOUGHT"
SCENARIO_INVALIDATED = "INVALIDATED"

NEGATIVE_NEWS_TERMS = {
    "profit warning",
    "downgrade",
    "sell rating",
    "taglio target",
    "taglia il target",
    "indagine",
    "sanzione",
    "perdita netta",
    "debito in aumento",
    "crollo",
    "warning",
}


def _commodity_tickers():
    try:
        return {str(item.get("ticker", "")).strip().upper() for item in load_commodity_tickers() if item.get("ticker")}
    except Exception:
        return set()


def _etf_tickers():
    try:
        return {str(item.get("ticker", "")).strip().upper() for item in load_etf_tickers() if item.get("ticker")}
    except Exception:
        return set()


def _fmt_level(value):
    if value is None:
        return None
    try:
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return None


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _short_text(value, limit=700):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def _has_negative_news(report):
    text = str(report or "").lower()
    return any(term in text for term in NEGATIVE_NEWS_TERMS)


def _has_active_condition(ticker):
    ticker = ticker.strip().upper()
    for item in list_monitored_conditions(status=None):
        if str(item.get("ticker", "")).strip().upper() == ticker:
            return item.get("status") in {"waiting", "met"}
    return False


def build_entry_scenarios_from_candidate(candidate):
    trigger = _to_float(candidate.get("resistance_10"))
    support = _to_float(candidate.get("support_10"))
    scenarios = []
    if trigger:
        scenarios.append(
            {
                "type": "BREAKOUT",
                "state": SCENARIO_WAIT,
                "trigger": trigger,
                "support": support,
                "stop": support,
                "required_volume_ratio": MIN_CONFIRM_VOLUME_RATIO,
                "description": (
                    f"chiusura sopra {_fmt_level(trigger)} con volumi in recupero o sopra MA10; "
                    f"invalidazione sotto {_fmt_level(support)}"
                    if support
                    else f"chiusura sopra {_fmt_level(trigger)} con volumi in recupero o sopra MA10"
                ),
            }
        )
    if support:
        entry_max = support * (1 + PULLBACK_ENTRY_DISTANCE_PCT / 100.0)
        stop = support * (1 - PULLBACK_STOP_BUFFER_PCT / 100.0)
        scenarios.append(
            {
                "type": "PULLBACK_SUPPORTO",
                "state": SCENARIO_WAIT,
                "trigger": entry_max,
                "entry_area_min": support,
                "entry_area_max": entry_max,
                "support": support,
                "stop": stop,
                "target": trigger,
                "required_volume_ratio": MIN_CONFIRM_VOLUME_RATIO,
                "description": (
                    f"ingresso in area {_fmt_level(support)}-{_fmt_level(entry_max)} solo su tenuta/rimbalzo "
                    f"del supporto, stop sotto {_fmt_level(stop)} e news non negative"
                ),
            }
        )
    return scenarios


def build_entry_condition_from_candidate(candidate):
    trigger = _fmt_level(candidate.get("resistance_10"))
    support = _fmt_level(candidate.get("support_10"))
    if not trigger and not support:
        return ""
    if trigger and support:
        return (
            f"SCENARIO BREAKOUT: chiusura sopra {trigger} con volumi in recupero o sopra media; "
            f"SCENARIO PULLBACK_SUPPORTO: ingresso solo su tenuta/rimbalzo del supporto {support}, "
            f"con stop sotto supporto e news non negative"
        )
    if trigger:
        return f"SCENARIO BREAKOUT: chiusura sopra {trigger} con volumi in recupero o sopra media"
    return f"SCENARIO PULLBACK_SUPPORTO: ingresso solo su tenuta/rimbalzo del supporto {support}, con stop sotto supporto"


def ensure_candidate_conditions(candidates, market, min_score=MIN_MONITOR_SCORE, max_items=None):
    """Persist waiting entry conditions for interesting scanner candidates.

    The dashboard trigger view is based on monitored_conditions, not on raw scanner output.
    This helper bridges the two so both FTSE MIB and commodities can appear there.
    """
    if load_portfolio() is None:
        return []

    created = []
    selected = candidates if max_items is None else candidates[: int(max_items)]
    for candidate in selected:
        ticker = str(candidate.get("ticker", "")).strip().upper()
        if not ticker or _has_active_condition(ticker):
            continue
        score = int(candidate.get("score") or 0)
        if score < int(min_score):
            continue
        if candidate.get("liquidity_ok") is False:
            continue
        scenarios = build_entry_scenarios_from_candidate(candidate)
        condition = build_entry_condition_from_candidate(candidate)
        if not condition:
            continue
        reasons = "; ".join((candidate.get("reasons") or [])[:3]) or "candidato emerso dallo scanner tecnico"
        risks = "; ".join((candidate.get("risks") or [])[:2])
        reason = f"{market}: score {score}. {reasons}"
        if risks:
            reason += f". Rischi da verificare: {risks}"
        created.append(
            add_monitored_condition(
                ticker=ticker,
                condition=condition,
                reason=reason,
                action_if_met="rivaluta grafico e news per possibile proposta autonoma di ingresso",
                metadata={
                    "market": market,
                    "score": score,
                    "source": "scanner_auto_monitor",
                    "entry_scenarios": scenarios,
                    "scenario_state": SCENARIO_WAIT,
                    "support_10": candidate.get("support_10"),
                    "resistance_10": candidate.get("resistance_10"),
                    "close": candidate.get("close"),
                    "change_1d_pct": candidate.get("change_1d_pct"),
                    "liquidity_ok": candidate.get("liquidity_ok"),
                    "avg_volume": candidate.get("avg_volume"),
                    "volume_ma10": candidate.get("volume_ma10"),
                    "turnover_eur": candidate.get("turnover_eur"),
                },
            )
        )
    return created


def _scenario_from_legacy_condition(item, snapshot):
    metadata = item.get("metadata", {}) or {}
    candidate = {
        "resistance_10": metadata.get("resistance_10") or snapshot.get("resistance_10"),
        "support_10": metadata.get("support_10") or snapshot.get("support_10"),
    }
    scenarios = build_entry_scenarios_from_candidate(candidate)
    return scenarios


def _volume_ratio(snapshot):
    volume = _to_float(snapshot.get("volume"))
    volume_ma10 = _to_float(snapshot.get("volume_ma10"))
    if not volume or not volume_ma10:
        return None
    return volume / volume_ma10


def _evaluate_breakout(scenario, snapshot, liquidity):
    close = _to_float(snapshot.get("close"))
    trigger = _to_float(scenario.get("trigger"))
    support = _to_float(scenario.get("support"))
    volume_ratio = _volume_ratio(snapshot)
    if not liquidity.get("liquidity_ok"):
        return SCENARIO_INVALIDATED, "liquidita insufficiente"
    if close is None or trigger is None:
        return SCENARIO_WAIT, "dati prezzo/trigger incompleti"
    if support is not None and close < support:
        return SCENARIO_INVALIDATED, f"close sotto supporto {support:.4f}"
    if close >= trigger and (volume_ratio is None or volume_ratio >= MIN_CONFIRM_VOLUME_RATIO):
        return SCENARIO_CONFIRMING, "breakout numerico verificato, serve conferma Playwright/news"
    if close >= trigger * (1 - BREAKOUT_NEAR_PCT / 100.0):
        return SCENARIO_NEAR_TRIGGER, "prezzo vicino al trigger breakout"
    return SCENARIO_WAIT, "breakout non ancora vicino"


def _evaluate_pullback(scenario, snapshot, liquidity):
    close = _to_float(snapshot.get("close"))
    support = _to_float(scenario.get("support"))
    entry_max = _to_float(scenario.get("entry_area_max"))
    stop = _to_float(scenario.get("stop"))
    volume_ratio = _volume_ratio(snapshot)
    rsi = _to_float(snapshot.get("rsi"))
    if not liquidity.get("liquidity_ok"):
        return SCENARIO_INVALIDATED, "liquidita insufficiente"
    if close is None or support is None:
        return SCENARIO_WAIT, "dati prezzo/supporto incompleti"
    if stop is not None and close < stop:
        return SCENARIO_INVALIDATED, f"close sotto stop {stop:.4f}"
    if close < support:
        return SCENARIO_INVALIDATED, f"supporto {support:.4f} perso"
    in_entry_area = entry_max is not None and support <= close <= entry_max
    momentum_ok = rsi is None or 35 <= rsi <= 68
    volume_ok = volume_ratio is None or volume_ratio >= MIN_CONFIRM_VOLUME_RATIO
    if in_entry_area and momentum_ok and volume_ok:
        return SCENARIO_CONFIRMING, "pullback su supporto in area utile, serve conferma Playwright/news"
    if in_entry_area:
        return SCENARIO_NEAR_TRIGGER, "prezzo in area supporto ma conferme ancora incomplete"
    return SCENARIO_WAIT, "prezzo non in area pullback"


def evaluate_condition_entry_scenarios(item, use_playwright=False, live_news=True, max_playwright=0):
    ticker = str(item.get("ticker", "")).strip().upper()
    metadata = item.get("metadata", {}) or {}
    market_text = f"{metadata.get('market', '')} {metadata.get('asset_class', '')}".lower()
    commodity_tickers = _commodity_tickers()
    etf_tickers = _etf_tickers()
    if ticker in commodity_tickers or "materie" in market_text or "commodity" in market_text:
        asset_class = "commodity"
    elif ticker in etf_tickers or "etf" in market_text:
        asset_class = "etf"
    else:
        asset_class = "equity"
    snapshot = generate_snapshot_context(ticker, period="1y")["snapshot"]
    liquidity = liquidity_metrics(snapshot, asset_class=asset_class)
    scenarios = metadata.get("entry_scenarios") or _scenario_from_legacy_condition(item, snapshot)
    evaluated = []
    needs_playwright = False
    best_state = SCENARIO_WAIT
    best_reason = ""

    print(
        "[scenario] VALUTO TRIGGER "
        f"{ticker} | mercato={asset_class} close={snapshot.get('close')} "
        f"oggi={snapshot.get('change_1d_pct')}% volume_ratio={_volume_ratio(snapshot)} "
        f"liquidita_ok={liquidity.get('liquidity_ok')} | condizione={item.get('condition')}",
        flush=True,
    )

    for scenario in scenarios:
        scenario = dict(scenario)
        kind = str(scenario.get("type", "")).upper()
        if kind == "PULLBACK_SUPPORTO":
            state, reason = _evaluate_pullback(scenario, snapshot, liquidity)
        else:
            state, reason = _evaluate_breakout(scenario, snapshot, liquidity)
        print(
            "[scenario] "
            f"{ticker} | scenario={kind or 'BREAKOUT'} stato={state} motivo={reason} "
            f"trigger={scenario.get('trigger')} supporto={scenario.get('support')} stop={scenario.get('stop')}",
            flush=True,
        )
        scenario["state"] = state
        scenario["last_reason"] = reason
        scenario["last_price"] = snapshot.get("close")
        scenario["last_volume_ratio"] = _volume_ratio(snapshot)
        scenario["last_evaluated_at"] = datetime.now().isoformat(timespec="seconds")
        if state == SCENARIO_CONFIRMING:
            needs_playwright = True
            best_state = SCENARIO_CONFIRMING
            best_reason = reason
        elif best_state == SCENARIO_WAIT and state in {SCENARIO_NEAR_TRIGGER, SCENARIO_INVALIDATED}:
            best_state = state
            best_reason = reason
        evaluated.append(scenario)

    chart_confirmation = None
    news_confirmation = None
    if use_playwright and needs_playwright and max_playwright > 0:
        print(
            "[scenario] USO PLAYWRIGHT "
            f"{ticker} | motivo=stato CONFIRMING: {best_reason}; "
            "serve conferma visuale grafico e news live/non negative prima di BUY_CANDIDATE",
            flush=True,
        )
        chart_confirmation = confirm_candidate_with_chart_ai(ticker, no_telegram=True)
        news_confirmation = get_news_report(ticker, live=live_news)
        chart_ok = chart_confirmation.get("status") == "ok"
        news_report = news_confirmation.get("report", "")
        news_negative = _has_negative_news(news_report)
        if chart_ok and not news_negative:
            best_state = SCENARIO_BUY_CANDIDATE
            best_reason = "scenario confermato da grafico Playwright e news non negative"
            for scenario in evaluated:
                if scenario.get("state") == SCENARIO_CONFIRMING:
                    scenario["state"] = SCENARIO_BUY_CANDIDATE
                    scenario["playwright_confirmed"] = True
                    scenario["news_negative"] = False
        else:
            best_state = SCENARIO_NEAR_TRIGGER
            best_reason = "conferma Playwright/news non sufficiente per comprare"
    elif needs_playwright:
        print(
            "[scenario] SALTO PLAYWRIGHT "
            f"{ticker} | motivo=budget Playwright esaurito o disabilitato "
            f"(use_playwright={use_playwright}, max_playwright={max_playwright}); resta in valutazione numerica",
            flush=True,
        )
    else:
        print(
            "[scenario] SALTO PLAYWRIGHT "
            f"{ticker} | motivo=nessuno scenario in stato CONFIRMING; stato migliore={best_state or SCENARIO_WAIT}",
            flush=True,
        )

    new_status = item.get("status", "waiting")
    if best_state == SCENARIO_BUY_CANDIDATE:
        new_status = "met"
    elif best_state == SCENARIO_INVALIDATED and all(s.get("state") == SCENARIO_INVALIDATED for s in evaluated):
        new_status = "invalidated"

    updated_metadata = {
        "entry_scenarios": evaluated,
        "scenario_state": best_state,
        "scenario_reason": best_reason,
        "last_entry_scenario_eval_at": datetime.now().isoformat(timespec="seconds"),
        "last_price": snapshot.get("close"),
        "change_1d_pct": snapshot.get("change_1d_pct"),
        "volume": snapshot.get("volume"),
        "volume_ma10": snapshot.get("volume_ma10"),
        "volume_ratio": _volume_ratio(snapshot),
        "support_10": snapshot.get("support_10"),
        "resistance_10": snapshot.get("resistance_10"),
        "liquidity_ok": liquidity.get("liquidity_ok"),
        "liquidity_warnings": liquidity.get("liquidity_warnings"),
        "asset_class": asset_class,
    }
    if chart_confirmation:
        updated_metadata["last_playwright_chart_file"] = chart_confirmation.get("analysis_file")
        updated_metadata["last_playwright_chart_summary"] = _short_text(chart_confirmation.get("report"), 900)
    if news_confirmation:
        updated_metadata["last_news_file"] = news_confirmation.get("file")
        updated_metadata["last_news_source"] = news_confirmation.get("source")
        updated_metadata["last_news_summary"] = _short_text(news_confirmation.get("report"), 900)

    update_monitored_condition(
        condition_id=item.get("id"),
        status=new_status,
        note=f"{best_state}: {best_reason}",
        metadata=updated_metadata,
    )
    print(
        "[scenario] ESITO TRIGGER "
        f"{ticker} | status_salvato={new_status} scenario_state={best_state} motivo={best_reason or 'nessun cambio'} "
        f"playwright_usato={bool(chart_confirmation or news_confirmation)}",
        flush=True,
    )
    return {
        "condition_id": item.get("id"),
        "ticker": ticker,
        "status": new_status,
        "scenario_state": best_state,
        "reason": best_reason,
        "current_price": snapshot.get("close"),
        "change_1d_pct": snapshot.get("change_1d_pct"),
        "volume_ratio": _volume_ratio(snapshot),
        "liquidity_ok": liquidity.get("liquidity_ok"),
        "needs_playwright": needs_playwright,
        "playwright_used": bool(chart_confirmation or news_confirmation),
        "scenarios": evaluated,
    }


def evaluate_monitored_entry_scenarios(tickers=None, use_playwright=True, live_news=True, max_playwright=2):
    """Evaluate saved entry scenarios and use Playwright only near real decisions."""
    selected = {str(t).strip().upper() for t in (tickers or []) if str(t).strip()}
    results = []
    used_playwright = 0
    print(
        "[scenario] INIZIO RIVALUTAZIONE TRIGGER | "
        f"tickers={sorted(selected) if selected else 'tutti waiting'} "
        f"use_playwright={use_playwright} live_news={live_news} max_playwright={max_playwright}",
        flush=True,
    )
    for item in list_monitored_conditions(status="waiting"):
        ticker = str(item.get("ticker", "")).strip().upper()
        if selected and ticker not in selected:
            continue
        allow_playwright = use_playwright and used_playwright < int(max_playwright)
        print(
            "[scenario] CANDIDATO A RIVALUTAZIONE "
            f"{ticker} | allow_playwright={allow_playwright} "
            f"playwright_usati={used_playwright}/{max_playwright}",
            flush=True,
        )
        result = evaluate_condition_entry_scenarios(
            item,
            use_playwright=allow_playwright,
            live_news=live_news,
            max_playwright=max(0, int(max_playwright) - used_playwright),
        )
        if result.get("playwright_used"):
            used_playwright += 1
        results.append(result)
    print(
        "[scenario] FINE RIVALUTAZIONE TRIGGER | "
        f"valutati={len(results)} playwright_usati={used_playwright}/{max_playwright}",
        flush=True,
    )
    return {
        "status": "ok",
        "evaluated": len(results),
        "playwright_used": used_playwright,
        "results": results,
    }


def invalidate_illiquid_monitored_conditions():
    """Invalidate existing waiting trigger conditions when liquidity is clearly too low."""
    commodity_tickers = _commodity_tickers()
    etf_tickers = _etf_tickers()
    invalidated = []
    for item in list_monitored_conditions(status="waiting"):
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        metadata = item.get("metadata", {}) or {}
        market_text = f"{metadata.get('market', '')} {metadata.get('asset_class', '')}".lower()
        if ticker in commodity_tickers or "materie" in market_text or "commodity" in market_text:
            asset_class = "commodity"
        elif ticker in etf_tickers or "etf" in market_text:
            asset_class = "etf"
        else:
            asset_class = "equity"
        try:
            snapshot = generate_snapshot_context(ticker, period="1y")["snapshot"]
            liquidity = liquidity_metrics(snapshot, asset_class=asset_class)
        except Exception as exc:
            continue
        if liquidity.get("liquidity_ok"):
            continue
        note = "Trigger invalidato automaticamente per liquidita insufficiente: " + "; ".join(
            liquidity.get("liquidity_warnings") or []
        )
        result = update_monitored_condition(
            condition_id=item.get("id"),
            status="invalidated",
            note=note,
            metadata={
                "liquidity_ok": False,
                "liquidity_checked_at_source": "invalidate_illiquid_monitored_conditions",
                "avg_volume": liquidity.get("avg_volume"),
                "turnover_eur": liquidity.get("turnover_eur"),
            },
        )
        invalidated.append({"ticker": ticker, "condition_id": item.get("id"), "result": result, "liquidity": liquidity})
    return invalidated
