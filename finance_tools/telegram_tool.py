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


def format_number(value):
    if value is None:
        return "n/d"
    try:
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


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

    lines = [
        "TradingWatchAgent - riepilogo monitoraggio",
        "",
        f"Capitale: EUR {float(status.get('initial_capital') or 0):.2f}",
        f"Cash: EUR {float(status.get('cash') or 0):.2f}",
        f"Valore portafoglio: EUR {float(performance.get('total_value') or 0):.2f}",
        f"P/L totale: EUR {float(performance.get('total_pnl') or 0):.2f} ({float(performance.get('total_pnl_pct') or 0):.2f}%)",
        f"Posizioni aperte: {len(positions)}",
        f"Proposte buy pending: {len(pending_buy)}",
        "",
    ]

    lines.append("Posizioni aperte:")
    if positions:
        for item in positions[:10]:
            ticker = item.get("ticker", "n/d")
            amount = format_money(item.get("allocated_amount"))
            entry = format_number(item.get("entry_price"))
            qty = format_number(item.get("virtual_quantity"))
            lines.append(f"- {ticker}: {amount}, entry {entry}, qty {qty}")
        if len(positions) > 10:
            lines.append(f"- ... altre {len(positions) - 10} posizioni")
    else:
        lines.append("- nessuna")

    lines.append("")
    lines.append(f"Titoli monitorati / condizioni waiting: {len(waiting)}")
    for item in waiting[:10]:
        action = item.get("action_if_met")
        action_text = f" | azione: {action}" if action else ""
        lines.append(f"- {item.get('ticker')}: {item.get('condition')}{action_text}")
    if len(waiting) > 10:
        lines.append(f"- ... altri {len(waiting) - 10} titoli monitorati")

    if met:
        lines.append("")
        lines.append(f"Condizioni scattate: {len(met)}")
        for item in met[:10]:
            lines.append(f"- {item.get('ticker')}: {item.get('condition')}")

    if invalidated:
        lines.append("")
        lines.append(f"Condizioni invalidate: {len(invalidated)}")
        for item in invalidated[:10]:
            lines.append(f"- {item.get('ticker')}: {item.get('condition')}")

    if pending_buy:
        lines.append("")
        lines.append("Proposte pending:")
        for item in pending_buy[:10]:
            amount = item.get("metadata", {}).get("amount")
            amount_text = f" {format_money(amount)}" if amount is not None else ""
            lines.append(f"- {item.get('id')} {item.get('ticker')}{amount_text}")
        if len(pending_buy) > 10:
            lines.append(f"- ... altre {len(pending_buy) - 10} proposte")

    lines.append("")
    lines.append("Azioni agente recenti:")
    if recent_actions:
        for item in recent_actions:
            lines.append(format_proposal_action(item))
    else:
        lines.append("- nessuna modifica applicata/rifiutata")

    if extra_note:
        lines.append("")
        lines.append(str(extra_note).strip())

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
