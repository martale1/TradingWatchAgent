import re

from finance_tools.performance_tool import latest_quote

MONEY_PREFIX = r"(?:EUR|€)?"


def parse_condition_levels(condition):
    levels = []
    for match in re.finditer(rf"{MONEY_PREFIX}\s*([0-9]+(?:[,.][0-9]+)?)", str(condition or "")):
        try:
            levels.append(float(match.group(1).replace(",", ".")))
        except ValueError:
            continue
    return levels


def first_level_after_keywords(condition, keywords):
    text = str(condition or "")
    for keyword in keywords:
        pattern = rf"{keyword}[^0-9€]*{MONEY_PREFIX}\s*([0-9]+(?:[,.][0-9]+)?)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                return None
    return None


def parse_condition_targets(condition):
    trigger = first_level_after_keywords(
        condition,
        [
            r"chiusura\s+stabile\s+sopra",
            r"chiusura\s+sopra",
            r"breakout\s+sopra",
            r"recupero\s+di",
            r"sopra",
        ],
    )
    support = first_level_after_keywords(
        condition,
        [
            r"supporto",
            r"tenuta\s+del\s+supporto",
            r"tenuta\s+di",
            r"mantenendo",
        ],
    )
    levels = parse_condition_levels(condition)
    if trigger is None and levels:
        trigger = max(levels)
    if support is None and len(levels) > 1:
        support = min(levels)
    return trigger, support


def trigger_status(current_price, trigger_level, support_level):
    if current_price is None or trigger_level is None:
        return "n/d", "neutral"
    if current_price >= trigger_level:
        return "TRIGGER RAGGIUNTO", "positive"
    distance_pct = ((trigger_level - current_price) / trigger_level * 100.0) if trigger_level else None
    if distance_pct is not None and distance_pct <= 1:
        return "MOLTO VICINO", "warning"
    if distance_pct is not None and distance_pct <= 3:
        return "VICINO", "warning"
    if support_level is not None and current_price <= support_level:
        return "SOTTO SUPPORTO", "negative"
    return "LONTANO", "neutral"


def progress_between_support_and_trigger(current_price, support_level, trigger_level):
    if current_price is None or support_level is None or trigger_level is None or trigger_level == support_level:
        return None
    return max(0.0, min(1.0, (current_price - support_level) / (trigger_level - support_level)))


def enrich_monitored_conditions(conditions):
    rows = []
    for item in conditions:
        ticker = str(item.get("ticker", "")).strip().upper()
        condition = item.get("condition", "")
        levels = parse_condition_levels(condition)
        trigger_level, support_level = parse_condition_targets(condition)
        current_price = None
        previous_close = None
        daily_change_pct = None
        price_status = "ok"
        try:
            quote = latest_quote(ticker)
            current_price = quote.get("current_price")
            previous_close = quote.get("previous_close")
            daily_change_pct = quote.get("daily_change_pct")
        except Exception as exc:
            price_status = str(exc)

        nearest_level = None
        distance = None
        distance_pct = None
        if current_price is not None and levels:
            nearest_level = min(levels, key=lambda level: abs(current_price - level))
            distance = current_price - nearest_level
            distance_pct = (distance / nearest_level * 100.0) if nearest_level else None

        status_label, status_kind = trigger_status(current_price, trigger_level, support_level)
        rows.append(
            {
                "id": item.get("id"),
                "ticker": ticker,
                "status": item.get("status"),
                "condition": condition,
                "action_if_met": item.get("action_if_met"),
                "updated_at": item.get("updated_at"),
                "current_price": round(current_price, 4) if current_price is not None else None,
                "previous_close": round(previous_close, 4) if previous_close is not None else None,
                "daily_change_pct": round(daily_change_pct, 2) if daily_change_pct is not None else None,
                "levels": levels,
                "nearest_level": round(nearest_level, 4) if nearest_level is not None else None,
                "nearest_distance": round(distance, 4) if distance is not None else None,
                "nearest_distance_pct": round(distance_pct, 2) if distance_pct is not None else None,
                "trigger_level": round(trigger_level, 4) if trigger_level is not None else None,
                "support_level": round(support_level, 4) if support_level is not None else None,
                "trigger_distance": round(current_price - trigger_level, 4)
                if current_price is not None and trigger_level is not None
                else None,
                "trigger_distance_pct": round((current_price - trigger_level) / trigger_level * 100.0, 2)
                if current_price is not None and trigger_level
                else None,
                "support_distance_pct": round((current_price - support_level) / support_level * 100.0, 2)
                if current_price is not None and support_level
                else None,
                "trigger_status": status_label,
                "trigger_status_kind": status_kind,
                "trigger_progress": progress_between_support_and_trigger(current_price, support_level, trigger_level),
                "price_status": price_status,
            }
        )
    return rows
