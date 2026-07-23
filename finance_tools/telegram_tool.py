import os

import telepot

from finance_tools.portfolio_store import list_monitored_conditions, portfolio_status_summary


TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_TOKEN_FALLBACK_ENV = "TELEGRAM_BOT_TOKEN_CH1"
TELEGRAM_RECEIVER_ENV = "TELEGRAM_RECEIVER_ID"


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
    conditions = list_monitored_conditions(status=None)
    waiting = [item for item in conditions if item.get("status") == "waiting"]
    met = [item for item in conditions if item.get("status") == "met"]
    invalidated = [item for item in conditions if item.get("status") == "invalidated"]
    pending_buy = status.get("pending_buy_proposals", [])
    positions = status.get("positions", [])

    lines = [
        "TradingWatchAgent - riepilogo monitoraggio",
        "",
        f"Capitale: EUR {float(status.get('initial_capital') or 0):.2f}",
        f"Cash: EUR {float(status.get('cash') or 0):.2f}",
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

    if extra_note:
        lines.append("")
        lines.append(str(extra_note).strip())

    return "\n".join(lines)


def send_monitoring_summary(extra_note=""):
    message = build_monitoring_summary(extra_note=extra_note)
    result = send_telegram_message(message)
    return {**result, "message": message}
