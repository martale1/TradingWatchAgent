import re
from datetime import datetime
from pathlib import Path

from finance_tools.common import PROJECT_ROOT
from finance_tools.monitoring_view import first_level_after_keywords, parse_condition_targets


ANALYSIS_ROOT = PROJECT_ROOT / "output" / "stock_ai"
MIN_TAKE_PROFIT_PCT = 3.0
MIN_HOLD_HOURS_BEFORE_TAKE_PROFIT = 24
TAKE_PROFIT_REDUCTION_PCT = 30.0


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_distance(current, level):
    current = safe_float(current)
    level = safe_float(level)
    if current is None or level in {None, 0}:
        return None
    return round((current - level) / level * 100.0, 2)


def position_age_hours(opened_at):
    if not opened_at:
        return None
    try:
        opened = datetime.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        now = datetime.now(opened.tzinfo) if opened.tzinfo else datetime.now()
        return max(0.0, (now - opened).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return None


def normalize_analysis_text(text):
    return (
        str(text or "")
        .replace("â‚¬", "EUR ")
        .replace("Ã ", "a")
        .replace("Ã¨", "e")
        .replace("Ã¹", "u")
        .replace("Ã²", "o")
        .replace("Ã¬", "i")
        .replace("Ã©", "e")
    )


def read_playwright_analysis(ticker):
    path = ANALYSIS_ROOT / ticker / f"{ticker}_analysis.txt"
    if not path.exists():
        return None, "", None
    text = normalize_analysis_text(path.read_text(encoding="utf-8", errors="replace"))
    return path, text, path.stat().st_mtime


def parse_label_level(text, label):
    pattern = rf"{label}\s*:\s*(?:EUR|€)?\s*([0-9]+(?:[,.][0-9]+)?)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return safe_float(match.group(1).replace(",", "."))


def extract_sentence(text, keywords):
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", clean)
    for keyword in keywords:
        for part in parts:
            if keyword.lower() in part.lower():
                return part.strip()
    return parts[-1].strip() if parts else ""


def levels_from_reason(reason, current_price=None):
    stop = first_level_after_keywords(
        reason,
        [
            r"stop\s+stretto\s+sotto",
            r"stop\s+sotto",
            r"invalidatione\s+sotto",
            r"invalidazione\s+sotto",
        ],
    )
    trigger, support = parse_condition_targets(reason)
    resistance = first_level_after_keywords(
        reason,
        [
            r"take\s+profit",
            r"target",
            r"resistenza",
            r"prima\s+resistenza",
        ],
    )

    current = safe_float(current_price)
    if resistance is not None and current is not None and resistance <= current:
        resistance = None
    # Entry triggers are not exit targets. If the original reason only talks about
    # entry/support levels, keep them for stop logic and leave take-profit unset.
    return stop or support, resistance


def explicit_stop_from_reason(reason):
    """Read only a numeric stop written directly after an exit keyword."""
    text = str(reason or "")
    patterns = [
        r"stop\s+stretto\s+sotto\s*(?:EUR\s*)?([0-9]+(?:[,.][0-9]+)?)",
        r"stop\s+inval\.?\s+sotto\s*(?:EUR\s*)?([0-9]+(?:[,.][0-9]+)?)",
        r"stop\s+sotto\s*(?:EUR\s*)?([0-9]+(?:[,.][0-9]+)?)",
        r"invalidazione\s+sotto\s*(?:EUR\s*)?([0-9]+(?:[,.][0-9]+)?)",
        r"invalidatione\s+sotto\s*(?:EUR\s*)?([0-9]+(?:[,.][0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return safe_float(match.group(1).replace(",", "."))
    return None


def should_take_profit(current, target, pnl_pct, opened_at):
    if current is None or target is None or current < target:
        return False, ""
    pnl = safe_float(pnl_pct) or 0.0
    age_hours = position_age_hours(opened_at)
    if age_hours is not None and age_hours < MIN_HOLD_HOURS_BEFORE_TAKE_PROFIT:
        return False, "posizione aperta da meno di 24 ore"
    if pnl < MIN_TAKE_PROFIT_PCT:
        return False, f"profitto {pnl:.2f}% sotto soglia {MIN_TAKE_PROFIT_PCT:.0f}%"
    return True, ""


def build_entry_audit(portfolio, ticker, position):
    """Expose only persisted evidence that led to the initial automatic buy."""
    ticker = str(ticker or "").strip().upper()
    proposals = [
        proposal
        for proposal in (portfolio or {}).get("closed_proposals", [])
        if str(proposal.get("ticker") or "").strip().upper() == ticker
        and proposal.get("action") == "buy_virtual_position"
        and proposal.get("status") == "confirmed"
    ]
    proposals.sort(key=lambda proposal: str(proposal.get("confirmed_at") or proposal.get("created_at") or ""))
    proposal = proposals[0] if proposals else {}
    proposal_metadata = proposal.get("metadata", {}) or {}
    snapshot = position.get("entry_audit_snapshot") or proposal_metadata.get("entry_audit_snapshot") or {}
    conditions = (portfolio or {}).get("monitored_conditions", []) or []
    condition = next(
        (
            candidate
            for candidate in conditions
            if (candidate.get("metadata", {}) or {}).get("auto_proposal_id") == proposal.get("id")
        ),
        None,
    )
    if condition is None and snapshot.get("condition_id"):
        condition = next(
            (candidate for candidate in conditions if candidate.get("id") == snapshot.get("condition_id")),
            None,
        )
    if condition is None and proposal:
        condition = next(
            (
                candidate
                for candidate in conditions
                if str(candidate.get("id") or "") in str(proposal.get("reason") or "")
            ),
            None,
        )
    if condition is None and proposal:
        proposal_time = str(proposal.get("confirmed_at") or proposal.get("created_at") or "")

        def time_distance(candidate):
            evaluated_at = str((candidate.get("metadata", {}) or {}).get("last_entry_scenario_eval_at") or "")
            try:
                return abs((datetime.fromisoformat(proposal_time) - datetime.fromisoformat(evaluated_at)).total_seconds())
            except (TypeError, ValueError):
                return float("inf")

        historical_candidates = [
            candidate
            for candidate in conditions
            if str(candidate.get("ticker") or "").strip().upper() == ticker
            and any(
                str(entry_scenario.get("state") or "").upper() == "BUY_CANDIDATE"
                for entry_scenario in ((candidate.get("metadata", {}) or {}).get("entry_scenarios", []) or [])
            )
        ]
        if historical_candidates:
            nearest = min(historical_candidates, key=time_distance)
            if time_distance(nearest) <= 15 * 60:
                condition = nearest
    condition = condition or {}
    condition_metadata = condition.get("metadata", {}) or {}
    scenarios = condition_metadata.get("entry_scenarios", []) or []
    scenario = next(
        (candidate for candidate in scenarios if str(candidate.get("state") or "").upper() == "BUY_CANDIDATE"),
        {},
    ) or snapshot.get("scenario", {}) or {}
    risk = snapshot.get("risk_validation") or proposal_metadata.get("risk_validation") or {}
    observed_price = safe_float(condition_metadata.get("last_price") or scenario.get("last_price") or snapshot.get("observed_price"))
    entry_min = safe_float(scenario.get("entry_area_min"))
    entry_max = safe_float(scenario.get("entry_area_max"))
    trigger = safe_float(scenario.get("trigger") or snapshot.get("trigger") or proposal_metadata.get("trigger"))
    volume_ratio = safe_float(snapshot.get("volume_ratio") or condition_metadata.get("volume_ratio") or scenario.get("last_volume_ratio"))
    pace_ratio = safe_float(snapshot.get("intraday_volume_pace_ratio") or condition_metadata.get("intraday_volume_pace_ratio"))
    required_volume = safe_float(scenario.get("required_volume_ratio"))
    daily_complete = snapshot.get("daily_bar_complete")
    if daily_complete is None:
        daily_complete = condition_metadata.get("daily_bar_complete")
    effective_volume = volume_ratio if daily_complete is True else pace_ratio
    scenario_type = str(scenario.get("type") or "").upper()
    if scenario_type == "PULLBACK_SUPPORTO" and None not in {observed_price, entry_min, entry_max}:
        price_passed = entry_min <= observed_price <= entry_max
        price_rule = f"Prezzo compreso tra {entry_min:.4f} e {entry_max:.4f}"
    elif scenario_type == "BREAKOUT" and observed_price is not None and trigger is not None:
        price_passed = observed_price >= trigger
        price_rule = f"Prezzo almeno {trigger:.4f}"
    else:
        price_passed = None
        price_rule = "Regola prezzo non ricostruibile"
    volume_passed = (
        effective_volume >= required_volume
        if effective_volume is not None and required_volume is not None
        else None
    )
    chart_confirmed = scenario.get("chart_entry_confirmed")
    if chart_confirmed is None:
        chart_confirmed = snapshot.get("chart_entry_confirmed")
    playwright_completed = scenario.get("playwright_confirmed")
    news_negative = scenario.get("news_negative")
    checks = [
        {
            "label": "Prezzo nella configurazione richiesta",
            "status": "passed" if price_passed is True else "failed" if price_passed is False else "missing",
            "actual": f"Prezzo osservato {observed_price:.4f}" if observed_price is not None else "Prezzo non registrato",
            "rule": price_rule,
        },
        {
            "label": "Conferma volumi",
            "status": "passed" if volume_passed is True else "failed" if volume_passed is False else "missing",
            "actual": f"{'Ritmo intraday' if daily_complete is False else 'Volume finale'} {effective_volume:.3f}x MA10" if effective_volume is not None else "Volume confrontabile non registrato",
            "rule": f"Richiesto almeno {required_volume:.2f}x MA10" if required_volume is not None else "Soglia non registrata",
        },
        {
            "label": "Conferma operativa del grafico",
            "status": "passed" if chart_confirmed is True else "failed" if chart_confirmed is False else "missing",
            "actual": (
                "Ingresso esplicitamente confermato"
                if chart_confirmed is True else "Ingresso esplicitamente respinto"
                if chart_confirmed is False else "Analisi completata, esito operativo non registrato"
                if playwright_completed is True else "Analisi grafica non registrata"
            ),
            "rule": "Il report deve confermare esplicitamente l'ingresso",
        },
        {
            "label": "Controllo news",
            "status": "passed" if news_negative is False else "failed" if news_negative is True else "missing",
            "actual": "Nessuna news negativa" if news_negative is False else "News negative rilevate" if news_negative is True else "Esito news non registrato",
            "rule": "Nessuna notizia negativa rilevante",
        },
        {
            "label": "Controllo rischio e dimensione",
            "status": "passed" if risk.get("allowed") is True else "failed" if risk.get("allowed") is False else "missing",
            "actual": f"Ordine consentito per EUR {safe_float(risk.get('amount')):.2f}" if safe_float(risk.get("amount")) is not None else "Esito rischio non registrato",
            "rule": "Rispetto dei limiti del profilo del portafoglio",
        },
    ]
    if snapshot.get("decision_kind") == "langgraph_automatic":
        score = safe_float(snapshot.get("score"))
        liquidity_ok = snapshot.get("liquidity_ok")
        checks = [
            {
                "label": "Punteggio scanner",
                "status": "passed" if score is not None and score >= 8 else "failed" if score is not None else "missing",
                "actual": f"Score {score:.0f}" if score is not None else "Score non registrato",
                "rule": "Score minimo 8 per candidato automatico",
            },
            {
                "label": "Liquidità dello strumento",
                "status": "passed" if liquidity_ok is True else "failed" if liquidity_ok is False else "missing",
                "actual": "Liquidità sufficiente" if liquidity_ok is True else "Liquidità insufficiente" if liquidity_ok is False else "Liquidità non registrata",
                "rule": "Il filtro di liquidità deve essere superato",
            },
            {
                "label": "Conferma operativa del grafico",
                "status": "passed" if chart_confirmed is True else "failed" if chart_confirmed is False else "missing",
                "actual": "Ingresso confermato" if chart_confirmed is True else "Ingresso non confermato" if chart_confirmed is False else "Esito non registrato",
                "rule": "Il report deve confermare esplicitamente l'ingresso",
            },
            checks[-1],
        ]
    legacy_warning = (
        "ATTENZIONE: questo acquisto e precedente alla correzione del controllo grafico. "
        "Il vecchio codice considerava l'analisi Playwright completata come conferma dell'ingresso, "
        "anche senza un esito operativo esplicito nel report."
        if playwright_completed is True and chart_confirmed is None else None
    )
    return {
        "available": bool(proposal or position),
        "audit_type": (
            "manual_or_explicit" if snapshot.get("decision_kind") in {"explicit_user_override", "explicit_manual_confirmation", "agent_proposal_requiring_confirmation", "manual_or_agent_proposal"}
            else "standardized_snapshot" if snapshot.get("audit_complete") is True
            else "monitored_condition" if condition and scenario
            else "unlinked_historical_entry"
        ),
        "decision_kind": snapshot.get("decision_kind"),
        "proposal_id": proposal.get("id"),
        "confirmed_at": proposal.get("confirmed_at") or position.get("opened_at"),
        "source": proposal_metadata.get("source") or position.get("source"),
        "reason": proposal.get("reason") or position.get("reason"),
        "condition_id": condition.get("id"),
        "condition": condition.get("condition") or snapshot.get("condition"),
        "scenario_type": scenario.get("type"),
        "scenario_description": scenario.get("description"),
        "scenario_reason": scenario.get("last_reason") or condition_metadata.get("scenario_reason"),
        "entry_price": proposal_metadata.get("entry_price") or position.get("entry_price"),
        "observed_price": observed_price,
        "trigger": trigger,
        "support": scenario.get("support") or condition_metadata.get("support_10"),
        "entry_area_min": entry_min,
        "entry_area_max": entry_max,
        "volume_ratio": volume_ratio,
        "intraday_volume_pace_ratio": pace_ratio,
        "required_volume_ratio": required_volume,
        "daily_bar_complete": daily_complete,
        "playwright_completed": playwright_completed,
        "chart_entry_confirmed": chart_confirmed,
        "news_negative": news_negative,
        "risk_allowed": risk.get("allowed"),
        "risk_amount": risk.get("amount"),
        "score": snapshot.get("score"),
        "reasons": snapshot.get("reasons") or [],
        "risks": snapshot.get("risks") or [],
        "checks": checks,
        "legacy_warning": legacy_warning,
        "data_note": "Dati storici registrati al momento della decisione; i campi mancanti non sono ricostruiti.",
    }


def build_exit_conditions(performance, portfolio):
    positions = performance.get("positions", []) if performance else []
    raw_positions = {
        str(item.get("ticker", "")).strip().upper(): item
        for item in (portfolio or {}).get("positions", [])
        if item.get("status") == "open"
    }
    completed_take_profits = {
        (
            str(item.get("ticker") or "").strip().upper(),
            safe_float((item.get("metadata") or {}).get("trigger_level")),
        )
        for item in (portfolio or {}).get("closed_proposals", [])
        if (item.get("metadata") or {}).get("source") == "deterministic_take_profit"
        and item.get("status") == "confirmed"
    }
    rows = []

    for item in positions:
        ticker = str(item.get("ticker", "")).strip().upper()
        current = safe_float(item.get("current_price"))
        entry = safe_float(item.get("entry_price"))
        pnl_pct = safe_float(item.get("pnl_pct"))
        raw = raw_positions.get(ticker, {})
        reason = normalize_analysis_text(raw.get("reason") or item.get("reason") or "")
        opened_at = raw.get("opened_at")
        path, analysis_text, analysis_mtime = read_playwright_analysis(ticker)

        support_1 = parse_label_level(analysis_text, "S1")
        support_2 = parse_label_level(analysis_text, "S2")
        resistance_1 = parse_label_level(analysis_text, "R1")
        resistance_2 = parse_label_level(analysis_text, "R2")
        fallback_support, fallback_resistance = levels_from_reason(reason, current)
        explicit_stop = explicit_stop_from_reason(reason)

        stop_level = explicit_stop or support_1 or fallback_support or (round(entry * 0.95, 4) if entry else None)
        stop_source = (
            "stop definito all'ingresso" if explicit_stop is not None
            else "primo supporto tecnico" if support_1 is not None
            else "supporto della condizione d'ingresso" if fallback_support is not None
            else "protezione automatica -5% dal carico"
        )
        panic_level = support_2
        resistance_level = resistance_1 or fallback_resistance
        take_profit_level = resistance_level
        target_unavailable_reason = ""
        if take_profit_level is not None and stop_level is not None and take_profit_level <= stop_level:
            target_unavailable_reason = "resistenza non valida: non e sopra il livello di uscita"
            take_profit_level = None
        if take_profit_level is not None and entry is not None:
            min_take_profit_price = entry * (1 + MIN_TAKE_PROFIT_PCT / 100.0)
            if take_profit_level < min_take_profit_price:
                target_unavailable_reason = (
                    f"resistenza {take_profit_level:.4f} nota ma troppo vicina al prezzo di carico; "
                    f"take profit minimo {MIN_TAKE_PROFIT_PCT:.0f}%"
                )
                take_profit_level = None
        if resistance_level is None:
            target_unavailable_reason = "nessuna resistenza tecnica disponibile"
        stretch_target = resistance_2 if resistance_2 and resistance_2 != take_profit_level else None

        take_profit_ready, take_profit_blocker = should_take_profit(current, take_profit_level, pnl_pct, opened_at)
        take_profit_executed = (
            take_profit_level is not None
            and (ticker, safe_float(take_profit_level)) in completed_take_profits
        )

        if current is not None and stop_level is not None and current <= stop_level:
            status = "STOP VIOLATO"
            status_kind = "negative"
            primary_action = "Stop violato: vendita totale automatica della posizione."
        elif take_profit_ready and not take_profit_executed:
            status = "TAKE PROFIT"
            status_kind = "positive"
            primary_action = f"Take profit raggiunto: vendita parziale automatica del {TAKE_PROFIT_REDUCTION_PCT:.0f}%."
        elif take_profit_executed:
            status = "TAKE PROFIT ESEGUITO"
            status_kind = "positive"
            primary_action = f"Vendita parziale del {TAKE_PROFIT_REDUCTION_PCT:.0f}% gia eseguita su questo target."
        elif current is not None and take_profit_level is not None and current >= take_profit_level:
            status = "MANTIENI"
            status_kind = "neutral"
            primary_action = f"Target tecnico raggiunto, ma niente take profit: {take_profit_blocker}."
        elif pnl_pct is not None and pnl_pct <= -3:
            status = "SOTTO OSSERVAZIONE"
            status_kind = "warning"
            primary_action = "Perdita oltre soglia: controlla tenuta supporto e rischio posizione."
        elif pnl_pct is not None and pnl_pct >= 5:
            status = "PROTEGGI PROFITTO"
            status_kind = "positive"
            primary_action = "Profitto interessante: valuta trailing stop sopra prezzo di carico."
        else:
            status = "MANTIENI"
            status_kind = "neutral"
            primary_action = "Nessun trigger di uscita immediato."

        explanation_source = "Analisi tecnica Playwright/ChatGPT" if analysis_text else "Proposta originale della posizione"
        known_levels = []
        for label, value in (("S1", support_1), ("S2", support_2), ("R1", resistance_1), ("R2", resistance_2)):
            if value is not None:
                known_levels.append(f"{label} {value:.4f}")
        explanation = (
            "Livelli tecnici rilevati: " + ", ".join(known_levels) + "."
            if known_levels else reason or "Nessun livello tecnico disponibile."
        )
        analysis_updated_at = (
            datetime.fromtimestamp(analysis_mtime).isoformat(timespec="seconds")
            if analysis_mtime is not None else None
        )

        rows.append(
            {
                "ticker": ticker,
                "status": status,
                "status_kind": status_kind,
                "current_price": item.get("current_price"),
                "previous_close": item.get("previous_close"),
                "daily_change_pct": item.get("daily_change_pct"),
                "price_as_of": item.get("price_as_of"),
                "price_currency": item.get("price_currency"),
                "entry_price": item.get("entry_price"),
                "opened_at": item.get("opened_at") or opened_at,
                "pnl_pct": item.get("pnl_pct"),
                "stop_level": round(stop_level, 4) if stop_level is not None else None,
                "stop_source": stop_source,
                "panic_level": round(panic_level, 4) if panic_level is not None else None,
                "resistance_level": round(resistance_level, 4) if resistance_level is not None else None,
                "take_profit_level": round(take_profit_level, 4) if take_profit_level is not None else None,
                "target_unavailable_reason": target_unavailable_reason,
                "stretch_target": round(stretch_target, 4) if stretch_target is not None else None,
                "distance_to_stop_pct": pct_distance(current, stop_level),
                "distance_to_take_profit_pct": pct_distance(current, take_profit_level),
                "stop_action_code": "sell_all" if stop_level is not None else None,
                "take_profit_action_code": (
                    "reduce_position" if take_profit_level is not None else None
                ),
                "take_profit_percent": TAKE_PROFIT_REDUCTION_PCT if take_profit_level is not None else None,
                "take_profit_executed": take_profit_executed,
                "stop_trigger_action": (
                    "Vendita totale della posizione quando il prezzo raggiunge o scende sotto questo livello."
                    if stop_level is not None else None
                ),
                "take_profit_trigger_action": (
                    f"Vendita parziale automatica del {TAKE_PROFIT_REDUCTION_PCT:.0f}% al raggiungimento del livello."
                    if take_profit_level is not None else None
                ),
                "take_profit_action_known": take_profit_level is not None,
                "primary_action": primary_action,
                "explanation": explanation,
                "source": explanation_source,
                "analysis_updated_at": analysis_updated_at,
                "analysis_file": str(path) if path else "",
                "entry_audit": build_entry_audit(portfolio, ticker, raw),
            }
        )

    return rows
