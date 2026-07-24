import re
from pathlib import Path

from finance_tools.common import PROJECT_ROOT
from finance_tools.monitoring_view import parse_condition_levels


ANALYSIS_ROOT = PROJECT_ROOT / "output" / "stock_ai"


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
    levels = parse_condition_levels(reason)
    if not levels:
        return None, None
    current = safe_float(current_price)
    below = [level for level in levels if current is not None and level < current]
    above = [level for level in levels if current is not None and level > current]
    support = max(below) if below else min(levels)
    resistance = min(above) if above else max(levels)
    return support, resistance


def build_exit_conditions(performance, portfolio):
    positions = performance.get("positions", []) if performance else []
    raw_positions = {
        str(item.get("ticker", "")).strip().upper(): item
        for item in (portfolio or {}).get("positions", [])
        if item.get("status") == "open"
    }
    rows = []

    for item in positions:
        ticker = str(item.get("ticker", "")).strip().upper()
        current = safe_float(item.get("current_price"))
        entry = safe_float(item.get("entry_price"))
        pnl_pct = safe_float(item.get("pnl_pct"))
        raw = raw_positions.get(ticker, {})
        reason = normalize_analysis_text(raw.get("reason") or item.get("reason") or "")
        path, analysis_text, _ = read_playwright_analysis(ticker)

        support_1 = parse_label_level(analysis_text, "S1")
        support_2 = parse_label_level(analysis_text, "S2")
        resistance_1 = parse_label_level(analysis_text, "R1")
        resistance_2 = parse_label_level(analysis_text, "R2")
        fallback_support, fallback_resistance = levels_from_reason(reason, current)

        stop_level = support_1 or fallback_support or (round(entry * 0.95, 4) if entry else None)
        panic_level = support_2
        take_profit_level = resistance_1 or fallback_resistance
        stretch_target = resistance_2 if resistance_2 and resistance_2 != take_profit_level else None

        if current is not None and stop_level is not None and current <= stop_level:
            status = "USCITA DA VALUTARE"
            status_kind = "negative"
            primary_action = "Prezzo sotto il primo supporto: valuta vendita o riduzione."
        elif current is not None and take_profit_level is not None and current >= take_profit_level:
            status = "TAKE PROFIT"
            status_kind = "positive"
            primary_action = "Prezzo sopra la prima resistenza: valuta presa profitto parziale."
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

        explanation_source = "Playwright/ChatGPT" if analysis_text else "fallback da proposta/posizione"
        explanation = extract_sentence(
            analysis_text,
            ["sotto", "support", "resistenza", "operativita", "scenario"],
        )
        if not explanation:
            explanation = reason or "Condizione generata dai livelli tecnici disponibili."

        rows.append(
            {
                "ticker": ticker,
                "status": status,
                "status_kind": status_kind,
                "current_price": item.get("current_price"),
                "entry_price": item.get("entry_price"),
                "pnl_pct": item.get("pnl_pct"),
                "stop_level": round(stop_level, 4) if stop_level is not None else None,
                "panic_level": round(panic_level, 4) if panic_level is not None else None,
                "take_profit_level": round(take_profit_level, 4) if take_profit_level is not None else None,
                "stretch_target": round(stretch_target, 4) if stretch_target is not None else None,
                "distance_to_stop_pct": pct_distance(current, stop_level),
                "distance_to_take_profit_pct": pct_distance(current, take_profit_level),
                "primary_action": primary_action,
                "explanation": explanation,
                "source": explanation_source,
                "analysis_file": str(path) if path else "",
            }
        )

    return rows
