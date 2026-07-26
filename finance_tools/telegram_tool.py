import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import telepot

from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_store import list_monitored_conditions, load_portfolio, portfolio_status_summary
from finance_tools.performance_tool import calculate_portfolio_performance


TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_TOKEN_FALLBACK_ENV = "TELEGRAM_BOT_TOKEN_CH1"
TELEGRAM_RECEIVER_ENV = "TELEGRAM_RECEIVER_ID"
TELEGRAM_NOTIFICATION_STATE = PROJECT_ROOT / "telegram_notification_state.json"
TELEGRAM_SETTINGS_FILE = PROJECT_ROOT / "telegram_settings.json"
TELEGRAM_MODES = {"always", "changes", "alerts", "disabled"}
TELEGRAM_SEND_RETRIES = 2
TELEGRAM_SEND_RETRY_DELAY_SECONDS = 5


def is_transient_telegram_error(exc):
    text = str(exc)
    transient_markers = (
        "NameResolutionError",
        "Failed to resolve",
        "nodename nor servname provided",
        "getaddrinfo failed",
        "api.telegram.org",
        "HTTPSConnectionPool",
        "Max retries exceeded",
        "RemoteDisconnected",
        "Remote end closed connection without response",
        "Connection aborted",
        "Connection reset",
        "Read timed out",
        "timed out",
        "temporarily unavailable",
    )
    return any(marker in text for marker in transient_markers)


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def load_notification_state():
    if not TELEGRAM_NOTIFICATION_STATE.exists():
        return {}
    try:
        return json.loads(TELEGRAM_NOTIFICATION_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_notification_state(state):
    TELEGRAM_NOTIFICATION_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_telegram_settings():
    default = {
        "monitoring_mode": "always",
        "send_performance_alerts": True,
        "max_monitoring_items": 5,
    }
    if not TELEGRAM_SETTINGS_FILE.exists():
        return default
    try:
        data = json.loads(TELEGRAM_SETTINGS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
    merged = {**default, **data}
    if merged.get("monitoring_mode") not in TELEGRAM_MODES:
        merged["monitoring_mode"] = default["monitoring_mode"]
    try:
        merged["max_monitoring_items"] = max(3, min(int(merged.get("max_monitoring_items") or 5), 12))
    except (TypeError, ValueError):
        merged["max_monitoring_items"] = default["max_monitoring_items"]
    merged["send_performance_alerts"] = bool(merged.get("send_performance_alerts"))
    return merged


def save_telegram_settings(settings):
    current = load_telegram_settings()
    merged = {**current, **settings}
    if merged.get("monitoring_mode") not in TELEGRAM_MODES:
        raise ValueError(f"monitoring_mode non valido. Usa uno tra: {', '.join(sorted(TELEGRAM_MODES))}")
    try:
        merged["max_monitoring_items"] = max(3, min(int(merged.get("max_monitoring_items") or 5), 12))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_monitoring_items deve essere un numero tra 3 e 12") from exc
    merged["send_performance_alerts"] = bool(merged.get("send_performance_alerts"))
    TELEGRAM_SETTINGS_FILE.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def should_send_monitoring_summary(reason="manual", changed=False, has_alerts=False):
    settings = load_telegram_settings()
    mode = settings.get("monitoring_mode", "always")
    if reason == "manual":
        return True, "invio manuale", settings
    if mode == "disabled":
        return False, "telegram disattivato", settings
    if mode == "always":
        return True, "modalita invia sempre", settings
    if mode == "changes":
        return bool(changed), "variazioni rilevate" if changed else "nessuna variazione rilevata", settings
    if mode == "alerts":
        return bool(has_alerts), "alert rilevante" if has_alerts else "nessun alert rilevante", settings
    return False, "modalita non gestita", settings


def alert_signature(performance):
    alerts = performance.get("alerts") or []
    if not alerts:
        return ""
    return "|".join(
        sorted(
            ":".join(
                [
                    str(item.get("ticker", "")),
                    str(item.get("type", "")),
                    str(item.get("level", "")),
                ]
            )
            for item in alerts
        )
    )


def should_send_performance_alert(performance, min_interval_minutes=180):
    signature = alert_signature(performance)
    if not signature:
        return False, "nessun alert performance"

    state = load_notification_state()
    perf_state = state.get("performance_alert", {})
    last_signature = perf_state.get("signature", "")
    last_sent_at = perf_state.get("sent_at")
    if signature != last_signature:
        state["performance_alert"] = {"signature": signature, "sent_at": now_iso()}
        save_notification_state(state)
        return True, "alert cambiato"

    if last_sent_at:
        try:
            elapsed = datetime.now() - datetime.fromisoformat(last_sent_at)
            if elapsed < timedelta(minutes=min_interval_minutes):
                return False, f"alert gia inviato da meno di {min_interval_minutes} minuti"
        except ValueError:
            pass

    state["performance_alert"] = {"signature": signature, "sent_at": now_iso()}
    save_notification_state(state)
    return True, "promemoria alert dopo intervallo"


def format_decimal(value, decimals=2):
    if value is None:
        return "n/d"
    try:
        text = f"{float(value):,.{decimals}f}"
        return text.replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(value)


def format_money(value):
    if value is None:
        return "n/d"
    return f"{format_decimal(value, 2)} €"


def format_signed_money(value):
    if value is None:
        return "n/d"
    try:
        number = float(value)
        sign = "+" if number > 0 else "-" if number < 0 else ""
        return f"{sign}{format_decimal(abs(number), 2)} €"
    except (TypeError, ValueError):
        return str(value)


def format_number(value):
    if value is None:
        return "n/d"
    try:
        text = f"{float(value):.4f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


def format_pct(value):
    if value is None:
        return "n/d"
    try:
        number = float(value)
        sign = "+" if number > 0 else ""
        return f"{sign}{format_decimal(number, 2)}%"
    except (TypeError, ValueError):
        return str(value)


def format_plain_pct(value, decimals=1):
    if value is None:
        return "n/d"
    try:
        return f"{format_decimal(float(value), decimals)}%"
    except (TypeError, ValueError):
        return str(value)


def signal_dot(value, neutral_threshold=0.05):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "⚪"
    if number > neutral_threshold:
        return "🟢"
    if number < -neutral_threshold:
        return "🔴"
    return "⚪"


def trend_marker(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "="
    if number > 0:
        return "+"
    if number < 0:
        return "-"
    return "="


def short_condition(text, max_len=96):
    clean = " ".join(str(text or "").split())
    clean = clean.replace(" | azione:", ". Azione:")
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3].rstrip(" ,.;") + "..."


def compact_condition(text):
    clean = short_condition(text, max_len=72)
    replacements = [
        ("chiusura stabile sopra", "close >"),
        ("chiusura sopra", "close >"),
        ("con volumi sostenuti", "volumi ok"),
        ("mantenendo", "stop"),
        ("oppure tenuta del supporto", "oppure supporto"),
        ("oppure tenuta di", "oppure tenuta"),
    ]
    for old, new in replacements:
        clean = clean.replace(old, new)
    return clean


def _scenario_label(kind):
    value = str(kind or "").upper()
    if value == "PULLBACK_SUPPORTO":
        return "PULLBACK supporto"
    if value == "BREAKOUT":
        return "BREAKOUT"
    return value or "trigger"


def _best_entry_scenario(item):
    metadata = item.get("metadata", {}) or {}
    scenarios = metadata.get("entry_scenarios") or []
    preferred_states = ["BUY_CANDIDATE", "CONFIRMING", "NEAR_TRIGGER", "WAIT"]
    for state in preferred_states:
        for scenario in scenarios:
            if str(scenario.get("state", "")).upper() == state:
                return scenario
    return scenarios[0] if scenarios else None


def format_trigger_event(item):
    ticker = item.get("ticker", "n/d")
    metadata = item.get("metadata", {}) or {}
    scenario = _best_entry_scenario(item)
    close = metadata.get("last_price") or metadata.get("close")
    volume_ratio = metadata.get("volume_ratio")
    reason = metadata.get("scenario_reason") or item.get("reason") or ""

    if not scenario:
        return f"- {ticker}: {short_condition(item.get('condition'), max_len=140)}"

    kind = str(scenario.get("type", "")).upper()
    label = _scenario_label(kind)
    state = str(scenario.get("state", metadata.get("scenario_state", "")) or "").upper()
    parts = [f"- {ticker}: {label}"]

    if kind == "BREAKOUT":
        trigger = scenario.get("trigger")
        parts.append(f"close {format_number(close)}")
        parts.append(f"trigger {format_number(trigger)}")
        try:
            price_ok = float(close) >= float(trigger)
        except (TypeError, ValueError):
            price_ok = False
        condition_line = (
            f"  condizione prezzo: close >= trigger {format_number(trigger)}; "
            f"esito: {'OK' if price_ok else 'non ancora'}"
        )
    elif kind == "PULLBACK_SUPPORTO":
        support = scenario.get("support")
        area_min = scenario.get("entry_area_min") or support
        area_max = scenario.get("entry_area_max") or scenario.get("trigger")
        stop = scenario.get("stop")
        parts.append(f"close {format_number(close)}")
        parts.append(f"area {format_number(area_min)}-{format_number(area_max)}")
        parts.append(f"stop {format_number(stop)}")
        try:
            price = float(close)
            area_ok = float(area_min) <= price <= float(area_max)
            support_ok = price >= float(support)
        except (TypeError, ValueError):
            area_ok = False
            support_ok = False
        condition_line = (
            f"  condizione area: {format_number(area_min)}-{format_number(area_max)}; "
            f"esito: {'OK' if area_ok and support_ok else 'non ancora'}"
        )
    else:
        parts.append(f"close {format_number(close)}")
        parts.append(f"livello {format_number(scenario.get('trigger'))}")
        condition_line = (
            f"  condizione: close {format_number(close)} rispetto a livello "
            f"{format_number(scenario.get('trigger'))}"
        )

    if volume_ratio is not None:
        try:
            parts.append(f"vol {float(volume_ratio):.2f}x MA10")
        except (TypeError, ValueError):
            pass
    if state:
        parts.append(f"stato {state}")

    line = " | ".join(parts)
    if volume_ratio is not None:
        try:
            required = float(scenario.get("required_volume_ratio") or 0)
            condition_line += f"; volume {float(volume_ratio):.2f}x MA10"
            if required:
                volume_ok = float(volume_ratio) >= required
                condition_line += f" / soglia {required:.2f}x: {'OK' if volume_ok else 'non ancora'}"
        except (TypeError, ValueError):
            pass
    line += f"\n{condition_line}"
    if reason:
        line += f"\n  motivo: {short_condition(reason, max_len=120)}"
    return line


def format_proposal_action(item):
    status = item.get("status", "n/d")
    action = item.get("action", "n/d")
    ticker = item.get("ticker", "n/d")
    proposal_id = item.get("id", "n/d")
    metadata = item.get("metadata", {})
    amount = metadata.get("amount")
    amount_text = f" {format_money(amount)}" if amount is not None else ""
    when = item.get("confirmed_at") or item.get("rejected_at") or item.get("created_at") or ""
    if status == "confirmed":
        label = "applicata"
    elif status == "rejected":
        label = "rifiutata"
    else:
        label = status
    return f"- {label}: {proposal_id} {action} {ticker}{amount_text} {when}".strip()


def send_telegram_message(text_message):
    token = os.getenv(TELEGRAM_TOKEN_ENV) or os.getenv(TELEGRAM_TOKEN_FALLBACK_ENV)
    receiver_id = os.getenv(TELEGRAM_RECEIVER_ENV)
    if not token or not receiver_id:
        return {
            "status": "missing_config",
            "message": "Configura TELEGRAM_BOT_TOKEN e TELEGRAM_RECEIVER_ID in .env.",
        }
    bot = telepot.Bot(token)
    last_error = None
    for attempt in range(1, TELEGRAM_SEND_RETRIES + 1):
        try:
            bot.sendMessage(receiver_id, text_message)
            return {"status": "ok", "receiver_id": receiver_id, "attempt": attempt}
        except Exception as exc:
            last_error = exc
            if not is_transient_telegram_error(exc) or attempt >= TELEGRAM_SEND_RETRIES:
                break
            time.sleep(TELEGRAM_SEND_RETRY_DELAY_SECONDS)
    status = "telegram_network_error" if is_transient_telegram_error(last_error) else "telegram_error"
    return {
        "status": status,
        "receiver_id": receiver_id,
        "message": str(last_error),
    }


def _condition_sort_key(item):
    metadata = item.get("metadata", {}) or {}
    distance = metadata.get("distance_to_trigger_pct")
    if distance is None:
        scenario = _best_entry_scenario(item) or {}
        last_price = scenario.get("last_price") or metadata.get("last_price")
        trigger = scenario.get("trigger") or metadata.get("resistance_10")
        try:
            distance = abs((float(last_price) - float(trigger)) / float(trigger) * 100.0)
        except (TypeError, ValueError, ZeroDivisionError):
            distance = 999.0
    try:
        return abs(float(distance))
    except (TypeError, ValueError):
        return 999.0


def _condition_brief(item):
    metadata = item.get("metadata", {}) or {}
    scenario = _best_entry_scenario(item) or {}
    ticker = item.get("ticker", "n/d")
    state = metadata.get("scenario_state") or scenario.get("state") or item.get("status") or "waiting"
    close = metadata.get("last_price") or scenario.get("last_price") or metadata.get("close")
    trigger = scenario.get("trigger") or metadata.get("resistance_10")
    volume_ratio = metadata.get("volume_ratio") or scenario.get("last_volume_ratio")
    distance = _condition_sort_key(item)

    bits = [f"- {ticker} [{state}]"]
    if close is not None:
        bits.append(f"px {format_number(close)}")
    if trigger is not None:
        bits.append(f"trigger {format_number(trigger)}")
    if distance != 999.0:
        bits.append(f"gap {format_pct(-distance)}")
    if volume_ratio is not None:
        try:
            bits.append(f"vol {format_decimal(float(volume_ratio), 2)}x MA10")
        except (TypeError, ValueError):
            pass
    return " | ".join(bits)


def _position_brief(item, perf_item=None):
    perf_item = perf_item or {}
    ticker = item.get("ticker", "n/d")
    market_value = perf_item.get("market_value")
    pnl = perf_item.get("pnl")
    pnl_pct = perf_item.get("pnl_pct")
    daily_change_pct = perf_item.get("daily_change_pct")
    close = perf_item.get("current_price")
    marker = signal_dot(pnl_pct)

    first = (
        f"{marker} {ticker}  {format_money(market_value)}"
        f" | P/L {format_signed_money(pnl)} ({format_pct(pnl_pct)})"
    )
    second_parts = []
    if close is not None:
        second_parts.append(f"px {format_number(close)}")
    if daily_change_pct is not None:
        second_parts.append(f"oggi {format_pct(daily_change_pct)}")
    return first + ("\n   " + " | ".join(second_parts) if second_parts else "")


def _recent_action_brief(item):
    action = str(item.get("action", "azione")).replace("_virtual_position", "").replace("_", " ")
    ticker = item.get("ticker", "n/d")
    metadata = item.get("metadata", {}) or {}
    amount = metadata.get("amount")
    when = item.get("confirmed_at") or item.get("rejected_at") or item.get("created_at") or ""
    try:
        when_text = datetime.fromisoformat(str(when)).strftime("%d/%m %H:%M")
    except (TypeError, ValueError):
        when_text = str(when)[:16]
    amount_text = f" | {format_money(amount)}" if amount is not None else ""
    return f"- {ticker}: {action}{amount_text} ({when_text})"


def build_readable_monitoring_summary(extra_note=""):
    settings = load_telegram_settings()
    max_items = int(settings.get("max_monitoring_items") or 5)
    status = portfolio_status_summary()
    performance = calculate_portfolio_performance()
    conditions = list_monitored_conditions(status=None)
    waiting = sorted(
        [item for item in conditions if item.get("status") == "waiting"],
        key=_condition_sort_key,
    )
    met = sorted(
        [item for item in conditions if item.get("status") == "met"],
        key=_condition_sort_key,
    )
    invalidated = [item for item in conditions if item.get("status") == "invalidated"]
    pending_buy = status.get("pending_buy_proposals", [])
    positions = status.get("positions", [])
    portfolio = load_portfolio() or {}
    recent_actions = list(reversed(portfolio.get("closed_proposals", [])))[:3]

    position_perf = {item.get("ticker"): item for item in performance.get("positions", [])}
    total_pnl = float(performance.get("total_pnl") or 0)
    total_pnl_pct = float(performance.get("total_pnl_pct") or 0)

    lines = [
        "📊 Autonomous Trading Agent",
        f"Monitor | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "💼 Portafoglio",
        f"Valore: {format_money(performance.get('total_value'))}",
        f"P/L: {signal_dot(total_pnl_pct)} {format_signed_money(total_pnl)} ({format_pct(total_pnl_pct)})",
        f"Cash: {format_money(status.get('cash'))}",
        f"Posizioni: {len(positions)} | Pending buy: {len(pending_buy)}",
    ]

    if positions:
        lines.extend(["", "📌 Posizioni"])
        for item in positions[:max_items]:
            ticker = item.get("ticker", "n/d")
            lines.append(_position_brief(item, position_perf.get(ticker)))
        if len(positions) > max_items:
            lines.append(f"... altre {len(positions) - max_items} posizioni")

    if met:
        lines.extend(["", f"✅ Trigger scattati ({len(met)})"])
        for item in met[:max_items]:
            lines.append(_condition_brief(item))
        if len(met) > max_items:
            lines.append(f"... altri {len(met) - max_items} trigger scattati")

    if waiting:
        lines.extend(["", f"🎯 Trigger in attesa ({len(waiting)})"])
        for item in waiting[:max_items]:
            lines.append(_condition_brief(item))
        if len(waiting) > max_items:
            lines.append(f"... altri {len(waiting) - max_items} trigger in monitoraggio")

    if invalidated:
        lines.extend(["", f"⚠️ Trigger invalidati: {len(invalidated)}"])
        for item in invalidated[: min(3, max_items)]:
            lines.append(f"- {item.get('ticker')}: {short_condition(item.get('condition'), max_len=80)}")

    if pending_buy:
        lines.extend(["", "📝 Proposte pending"])
        for item in pending_buy[:max_items]:
            amount = item.get("metadata", {}).get("amount")
            amount_text = f" | {format_money(amount)}" if amount is not None else ""
            lines.append(f"- {item.get('ticker')} {item.get('id')}{amount_text}")

    if recent_actions:
        lines.extend(["", "🧾 Azioni recenti"])
        for item in recent_actions:
            lines.append(_recent_action_brief(item))

    if extra_note:
        lines.extend(["", "ℹ️ Nota", short_condition(extra_note, max_len=160)])

    return "\n".join(lines)


def build_readable_performance_summary(performance=None, extra_note=""):
    perf = performance or calculate_portfolio_performance()
    if perf.get("status") != "ok":
        return perf.get("message", "Performance non disponibile.")

    total_pnl = float(perf.get("total_pnl") or 0)
    total_pnl_pct = float(perf.get("total_pnl_pct") or 0)
    lines = [
        "📊 Autonomous Trading Agent",
        f"Performance | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "💼 Totale",
        f"Valore: {format_money(perf.get('total_value'))}",
        f"P/L: {signal_dot(total_pnl_pct)} {format_signed_money(total_pnl)} ({format_pct(total_pnl_pct)})",
        f"Cash: {format_money(perf.get('cash'))} ({format_plain_pct(perf.get('cash_pct'))})",
        f"Investito: {format_money(perf.get('invested_amount'))} ({format_plain_pct(perf.get('exposure_pct'))})",
        "",
        "📌 Posizioni",
    ]

    positions = perf.get("positions") or []
    if not positions:
        lines.append("nessuna posizione aperta")
    for item in positions[:10]:
        lines.append(_position_brief({"ticker": item.get("ticker")}, item))

    best = perf.get("best_position")
    worst = perf.get("worst_position")
    if best or worst:
        lines.append("")
        if best:
            lines.append(f"Best: {best.get('ticker')} {format_pct(best.get('pnl_pct'))}")
        if worst:
            lines.append(f"Worst: {worst.get('ticker')} {format_pct(worst.get('pnl_pct'))}")

    alerts = perf.get("alerts") or []
    if alerts:
        lines.extend(["", "⚠️ Alert"])
        for alert in alerts[:5]:
            lines.append(f"- {short_condition(alert.get('message'), max_len=90)}")

    if extra_note:
        lines.extend(["", "ℹ️ Nota", short_condition(extra_note, max_len=160)])

    return "\n".join(lines)


def build_monitoring_summary(extra_note=""):
    return build_readable_monitoring_summary(extra_note=extra_note)

    settings = load_telegram_settings()
    max_items = int(settings.get("max_monitoring_items") or 5)
    status = portfolio_status_summary()
    performance = calculate_portfolio_performance()
    conditions = list_monitored_conditions(status=None)
    waiting = [item for item in conditions if item.get("status") == "waiting"]
    met = [item for item in conditions if item.get("status") == "met"]
    invalidated = [item for item in conditions if item.get("status") == "invalidated"]
    pending_buy = status.get("pending_buy_proposals", [])
    positions = status.get("positions", [])
    portfolio = load_portfolio() or {}
    recent_actions = list(reversed(portfolio.get("closed_proposals", [])))[:5]

    position_perf = {item.get("ticker"): item for item in performance.get("positions", [])}
    total_pnl = float(performance.get("total_pnl") or 0)
    total_pnl_pct = float(performance.get("total_pnl_pct") or 0)

    lines = [
        "📊 Autonomous Trading Agent",
        f"🕒 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "💼 PORTAFOGLIO",
        f"Valore  {format_money(performance.get('total_value'))}",
        f"P/L     {format_signed_money(total_pnl)} ({format_pct(total_pnl_pct)})",
        f"Cash    {format_money(status.get('cash'))}",
        f"Posiz.  {len(positions)} | Pending {len(pending_buy)}",
        "",
        "📌 POSIZIONI",
    ]

    if positions:
        for item in positions[:max_items]:
            ticker = item.get("ticker", "n/d")
            perf_item = position_perf.get(ticker, {})
            pnl = perf_item.get("pnl")
            pnl_pct = perf_item.get("pnl_pct")
            daily_change_pct = perf_item.get("daily_change_pct")
            close = perf_item.get("current_price")
            close_text = f"px {format_number(close)}" if close is not None else "px n/d"
            daily_text = f" oggi {format_pct(daily_change_pct)}" if daily_change_pct is not None else ""
            lines.append(
                f"{trend_marker(pnl)} {ticker} | {close_text} | P/L {format_pct(pnl_pct)} |{daily_text}"
            )
        if len(positions) > max_items:
            lines.append(f"... altre {len(positions) - max_items} posizioni")
    else:
        lines.append("nessuna")

    lines.append("")
    lines.append(f"🎯 TRIGGER IN ATTESA ({len(waiting)})")
    for item in waiting[:max_items]:
        lines.append(f"• {item.get('ticker')}: {compact_condition(item.get('condition'))}")
    if len(waiting) > max_items:
        lines.append(f"... altri {len(waiting) - max_items} trigger")

    if met:
        lines.append("")
        lines.append(f"✅ TRIGGER SCATTATI ({len(met)})")
        for item in met[:max_items]:
            lines.append(format_trigger_event(item))

    if invalidated:
        lines.append("")
        lines.append(f"⚠️ TRIGGER INVALIDATI ({len(invalidated)})")
        for item in invalidated[:max_items]:
            lines.append(f"- {item.get('ticker')}: {short_condition(item.get('condition'))}")

    if pending_buy:
        lines.append("")
        lines.append("📝 PROPOSTE PENDING")
        for item in pending_buy[:max_items]:
            amount = item.get("metadata", {}).get("amount")
            amount_text = f" {format_money(amount)}" if amount is not None else ""
            lines.append(f"- {item.get('id')} {item.get('ticker')}{amount_text}")
        if len(pending_buy) > max_items:
            lines.append(f"... altre {len(pending_buy) - max_items} proposte")

    lines.append("")
    lines.append("🧾 AZIONI RECENTI")
    if recent_actions:
        for item in recent_actions[:3]:
            lines.append(format_proposal_action(item))
    else:
        lines.append("nessuna modifica applicata/rifiutata")

    if extra_note:
        lines.append("")
        lines.append("ℹ️ NOTA")
        lines.append(short_condition(extra_note, max_len=180))

    return "\n".join(lines)


def send_monitoring_summary(extra_note=""):
    message = build_monitoring_summary(extra_note=extra_note)
    result = send_telegram_message(message)
    return {**result, "message": message}


def send_performance_summary(extra_note="", force=False, min_interval_minutes=180):
    performance = calculate_portfolio_performance()
    if not force:
        allowed, reason = should_send_performance_alert(performance, min_interval_minutes=min_interval_minutes)
        if not allowed:
            return {"status": "skipped", "reason": reason, "message": ""}

    message = build_readable_performance_summary(performance, extra_note=extra_note)
    result = send_telegram_message(message)
    return {**result, "message": message}
