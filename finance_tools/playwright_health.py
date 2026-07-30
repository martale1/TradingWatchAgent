import os
from datetime import datetime

from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_registry import atomic_write_json, read_json


STATE_FILE = PROJECT_ROOT / "output" / "playwright_health.json"


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def load_playwright_health():
    return read_json(
        STATE_FILE,
        {
            "status": "unknown",
            "message": "Connessione Playwright/ChatGPT non ancora verificata.",
            "last_checked_at": None,
            "last_error_at": None,
            "last_recovered_at": None,
        },
    )


def _send_alert(message):
    try:
        from finance_tools.telegram_tool import send_telegram_message

        return send_telegram_message(message)
    except Exception as exc:
        return {"status": "error", "message": f"{exc.__class__.__name__}: {exc}"}


def record_playwright_failure(operation, detail="", ticker="", portfolio_id=""):
    portfolio_id = portfolio_id or os.getenv("ACTIVE_PORTFOLIO_ID", "main")
    previous = load_playwright_health()
    timestamp = now_iso()
    clean_detail = " ".join(str(detail or "").split())[-900:]
    message = (
        "Playwright non riesce a collegarsi al Chrome dedicato o a ottenere "
        "la risposta ChatGPT."
    )
    state = {
        **previous,
        "status": "error",
        "message": message,
        "operation": str(operation or "playwright"),
        "ticker": str(ticker or "").strip().upper(),
        "portfolio_id": str(portfolio_id or "").strip().lower(),
        "detail": clean_detail,
        "last_checked_at": timestamp,
        "last_error_at": timestamp,
    }
    if previous.get("status") != "error":
        telegram = _send_alert(
            "\n".join(
                [
                    "🚨 Autonomous Trading Agent",
                    "Errore Playwright / ChatGPT",
                    "",
                    message,
                    f"Operazione: {state['operation']}",
                    f"Ticker: {state['ticker'] or 'n/d'}",
                    f"Portafoglio: {state['portfolio_id'] or 'globale'}",
                    "",
                    "Controlla la finestra Chrome sulla porta 9222 e, se necessario, riavviala.",
                ]
            )
        )
        state["last_alert_at"] = timestamp
        state["last_alert_result"] = telegram.get("status")
    atomic_write_json(STATE_FILE, state)
    return state


def record_playwright_success(operation, ticker="", portfolio_id=""):
    portfolio_id = portfolio_id or os.getenv("ACTIVE_PORTFOLIO_ID", "main")
    previous = load_playwright_health()
    timestamp = now_iso()
    recovered = previous.get("status") == "error"
    state = {
        **previous,
        "status": "ok",
        "message": "Connessione Playwright/ChatGPT operativa.",
        "operation": str(operation or "playwright"),
        "ticker": str(ticker or "").strip().upper(),
        "portfolio_id": str(portfolio_id or "").strip().lower(),
        "detail": "",
        "last_checked_at": timestamp,
    }
    if recovered:
        telegram = _send_alert(
            "\n".join(
                [
                    "✅ Autonomous Trading Agent",
                    "Playwright / ChatGPT ripristinato",
                    "",
                    "La connessione al Chrome dedicato e la risposta ChatGPT sono nuovamente operative.",
                ]
            )
        )
        state["last_recovered_at"] = timestamp
        state["last_recovery_alert_result"] = telegram.get("status")
    atomic_write_json(STATE_FILE, state)
    return state
