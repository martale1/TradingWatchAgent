import os
import json
from datetime import datetime, timedelta
from pathlib import Path

import telepot

from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_store import list_monitored_conditions, load_portfolio, portfolio_status_summary
from finance_tools.performance_tool import build_performance_summary, calculate_portfolio_performance


TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_TOKEN_FALLBACK_ENV = "TELEGRAM_BOT_TOKEN_CH1"
TELEGRAM_RECEIVER_ENV = "TELEGRAM_RECEIVER_ID"
TELEGRAM_NOTIFICATION_STATE = PROJECT_ROOT / "telegram_notification_state.json"
TELEGRAM_SETTINGS_FILE = PROJECT_ROOT / "telegram_settings.json"
TELEGRAM_MODES = {"always", "changes", "alerts", "disabled"}


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


def format_money(value):
    if value is None:
        return "n/d"
    try:
        return f"EUR {float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def format_signed_money(value):
    if value is None:
        return "n/d"
    try:
        number = float(value)
        sign = "+" if number > 0 else "-" if number < 0 else ""
        return f"{sign} EUR {abs(number):.2f}"
    except (TypeError, ValueError):
        return str(value)


def format_number(value):
    if value is None:
        return "n/d"
    try:
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def format_pct(value):
    if value is None:
        return "n/d"
    try:
        number = float(value)
        sign = "+" if number > 0 else ""
        return f"{sign}{number:.2f}%"
    except (TypeError, ValueError):
        return str(value)


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
    bot.sendMessage(receiver_id, text_message)
    return {"status": "ok", "receiver_id": receiver_id}


def build_monitoring_summary(extra_note=""):
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
        "📊 TradingWatchAgent",
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
            lines.append(f"- {item.get('ticker')}: {item.get('condition')}")

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

    message = build_performance_summary(performance)
    if extra_note:
        message = f"{message}\n\n{str(extra_note).strip()}"
    result = send_telegram_message(message)
    return {**result, "message": message}
