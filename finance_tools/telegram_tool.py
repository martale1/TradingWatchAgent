import os

import telepot

from finance_tools.portfolio_store import list_monitored_conditions, portfolio_status_summary


TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_TOKEN_FALLBACK_ENV = "TELEGRAM_BOT_TOKEN_CH1"
TELEGRAM_RECEIVER_ENV = "TELEGRAM_RECEIVER_ID"


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
        f"Condizioni waiting: {len(waiting)}",
    ]
    for item in waiting[:10]:
        lines.append(f"- {item.get('ticker')}: {item.get('condition')}")

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
        lines.append("Proposte da confermare:")
        for item in pending_buy[:10]:
            amount = item.get("metadata", {}).get("amount")
            amount_text = f" EUR {float(amount):.2f}" if amount is not None else ""
            lines.append(f"- {item.get('id')} {item.get('ticker')}{amount_text}")

    if extra_note:
        lines.append("")
        lines.append(str(extra_note).strip())

    return "\n".join(lines)


def send_monitoring_summary(extra_note=""):
    message = build_monitoring_summary(extra_note=extra_note)
    result = send_telegram_message(message)
    return {**result, "message": message}
