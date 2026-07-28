import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_store import load_portfolio
from finance_tools.telegram_tool import load_telegram_settings, send_telegram_message


STATE_FILE = PROJECT_ROOT / "output" / "stock_ai" / "telegram_news_state.json"
REPORT_ROOT = PROJECT_ROOT / "output" / "stock_ai"
TRADE_ACTIONS = {"buy_virtual_position", "sell_virtual_position", "reduce_virtual_position"}
NO_RELEVANT_PATTERNS = (
    "nessuna news rilevante",
    "nessun aggiornamento recente",
    "non risultano notizie",
    "nessuna nuova comunicazione",
    "nessun report",
    "cache non presente",
    "news non disponibile",
)
ERROR_PATTERNS = (
    "traceback (most recent call last)",
    "timeouterror:",
    "rate limit",
    "run interrotta",
)


def _parse_iso(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def is_relevant_news_report(report):
    text = str(report or "").strip()
    if not text:
        return False
    lower = text.lower()
    return not any(pattern in lower for pattern in (*NO_RELEVANT_PATTERNS, *ERROR_PATTERNS))


def _load_state():
    if not STATE_FILE.exists():
        return {"sent": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"sent": {}}
    except (OSError, json.JSONDecodeError):
        return {"sent": {}}


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    sent = state.get("sent") or {}
    state["sent"] = dict(list(sent.items())[-200:])
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _eligible_tickers(max_trade_age_hours=24):
    portfolio = load_portfolio() or {}
    tickers = {}
    for position in portfolio.get("positions", []):
        ticker = str(position.get("ticker") or "").strip().upper()
        if ticker and position.get("status") == "open":
            tickers[ticker] = "titolo in portafoglio"

    cutoff = datetime.now() - timedelta(hours=max_trade_age_hours)
    for proposal in portfolio.get("closed_proposals", []):
        if proposal.get("status") != "confirmed" or proposal.get("action") not in TRADE_ACTIONS:
            continue
        when = _parse_iso(proposal.get("confirmed_at") or proposal.get("created_at"))
        if when is None or when < cutoff:
            continue
        ticker = str(proposal.get("ticker") or "").strip().upper()
        if ticker:
            label = {
                "buy_virtual_position": "titolo acquistato",
                "sell_virtual_position": "titolo venduto",
                "reduce_virtual_position": "posizione ridotta",
            }[proposal.get("action")]
            tickers[ticker] = label
    return tickers


def _compact_report(report, max_chars=2900):
    lines = [line.strip() for line in str(report or "").splitlines() if line.strip()]
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n… report abbreviato"
    return text


def send_relevant_news_alerts(tickers=None, max_report_age_hours=24):
    settings = load_telegram_settings()
    if settings.get("monitoring_mode") == "disabled":
        return {"status": "skipped", "reason": "telegram disattivato", "sent": []}

    eligible = _eligible_tickers()
    requested = {str(ticker).strip().upper() for ticker in (tickers or eligible) if str(ticker).strip()}
    selected = {ticker: reason for ticker, reason in eligible.items() if ticker in requested}
    if not selected:
        return {"status": "skipped", "reason": "nessun titolo operativo interessato", "sent": []}

    cutoff = datetime.now() - timedelta(hours=max_report_age_hours)
    state = _load_state()
    sent_state = state.setdefault("sent", {})
    sent = []
    errors = []

    for ticker, reason in selected.items():
        path = REPORT_ROOT / ticker.replace("/", "_") / f"{ticker}_news.txt"
        if not path.exists() or datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            continue
        report = path.read_text(encoding="utf-8", errors="replace").strip()
        if not is_relevant_news_report(report):
            continue
        signature = hashlib.sha256(f"{ticker}\n{report}".encode("utf-8")).hexdigest()
        if sent_state.get(ticker, {}).get("signature") == signature:
            continue

        message = (
            f"📰 News rilevanti — {ticker}\n"
            f"Motivo notifica: {reason}\n\n"
            f"{_compact_report(report)}"
        )
        result = send_telegram_message(message)
        if result.get("status") == "ok":
            sent_state[ticker] = {
                "signature": signature,
                "sent_at": datetime.now().isoformat(timespec="seconds"),
                "report_modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
            sent.append(ticker)
        else:
            errors.append({"ticker": ticker, "status": result.get("status"), "message": result.get("message")})

    if sent:
        _save_state(state)
    return {
        "status": "ok" if not errors else "partial_error",
        "sent": sent,
        "errors": errors,
        "eligible": sorted(selected),
    }
