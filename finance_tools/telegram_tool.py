import os
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import telepot

from finance_tools.common import PROJECT_ROOT
from finance_tools.agent_run_state import load_agent_run_state, parse_iso
from finance_tools.portfolio_store import list_monitored_conditions, load_portfolio, portfolio_status_summary
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.portfolio_registry import (
    DEFAULT_PORTFOLIO_ID,
    atomic_write_json,
    load_portfolio_config,
    portfolio_runtime_path,
    portfolio_state_path,
    update_portfolio_config,
)


TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_TOKEN_FALLBACK_ENV = "TELEGRAM_BOT_TOKEN_CH1"
TELEGRAM_RECEIVER_ENV = "TELEGRAM_RECEIVER_ID"
TELEGRAM_NOTIFICATION_STATE = PROJECT_ROOT / "telegram_notification_state.json"
TELEGRAM_SETTINGS_FILE = PROJECT_ROOT / "telegram_settings.json"
TELEGRAM_MODES = {"always", "changes", "portfolio_changes", "alerts", "disabled"}
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


def active_portfolio_id(portfolio_id=None):
    return str(
        portfolio_id
        or os.getenv("ACTIVE_PORTFOLIO_ID")
        or DEFAULT_PORTFOLIO_ID
    ).strip().lower()


def portfolio_display_label(portfolio_id=None):
    resolved_id = active_portfolio_id(portfolio_id)
    config = load_portfolio_config(resolved_id) or {}
    name = str(config.get("name") or resolved_id).strip()
    return resolved_id, f"{name} [{resolved_id}]"


def notification_state_path(portfolio_id=None):
    resolved_id = active_portfolio_id(portfolio_id)
    runtime_path = portfolio_runtime_path(resolved_id)
    if runtime_path.parent.exists():
        return runtime_path.parent / "telegram_notification_state.json"
    return TELEGRAM_NOTIFICATION_STATE


def load_notification_state(portfolio_id=None):
    path = notification_state_path(portfolio_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_notification_state(state, portfolio_id=None):
    path = notification_state_path(portfolio_id)
    atomic_write_json(path, state)


def load_telegram_settings(portfolio_id=None):
    default = {
        "monitoring_mode": "always",
        "send_performance_alerts": True,
        "max_monitoring_items": 5,
    }
    resolved_id = active_portfolio_id(portfolio_id)
    config = load_portfolio_config(resolved_id)
    portfolio_settings = (config or {}).get("telegram") or {}
    if portfolio_settings.get("inherit_global", True):
        if not TELEGRAM_SETTINGS_FILE.exists():
            data = {}
        else:
            try:
                data = json.loads(TELEGRAM_SETTINGS_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
    else:
        data = portfolio_settings
    merged = {**default, **data}
    if merged.get("monitoring_mode") not in TELEGRAM_MODES:
        merged["monitoring_mode"] = default["monitoring_mode"]
    try:
        merged["max_monitoring_items"] = max(3, min(int(merged.get("max_monitoring_items") or 5), 12))
    except (TypeError, ValueError):
        merged["max_monitoring_items"] = default["max_monitoring_items"]
    merged["send_performance_alerts"] = bool(merged.get("send_performance_alerts"))
    return merged


def save_telegram_settings(settings, portfolio_id=None):
    resolved_id = active_portfolio_id(portfolio_id)
    current = load_telegram_settings(resolved_id)
    merged = {**current, **settings}
    if merged.get("monitoring_mode") not in TELEGRAM_MODES:
        raise ValueError(f"monitoring_mode non valido. Usa uno tra: {', '.join(sorted(TELEGRAM_MODES))}")
    try:
        merged["max_monitoring_items"] = max(3, min(int(merged.get("max_monitoring_items") or 5), 12))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_monitoring_items deve essere un numero tra 3 e 12") from exc
    merged["send_performance_alerts"] = bool(merged.get("send_performance_alerts"))
    config = load_portfolio_config(resolved_id)
    if config:
        update_portfolio_config(
            resolved_id,
            {
                "telegram": {
                    **merged,
                    "inherit_global": False,
                }
            },
        )
    else:
        atomic_write_json(TELEGRAM_SETTINGS_FILE, merged)
    return merged


def should_send_monitoring_summary(
    reason="manual",
    changed=False,
    portfolio_changed=False,
    has_alerts=False,
):
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
    if mode == "portfolio_changes":
        return (
            bool(portfolio_changed),
            "composizione o quantita portafoglio variata"
            if portfolio_changed
            else "nessuna variazione a titoli o quantita del portafoglio",
            settings,
        )
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


def _scenario_dot(state):
    value = str(state or "").upper()
    if value == "BUY_CANDIDATE":
        return "🟢"
    if value in {"CONFIRMING", "NEAR_TRIGGER"}:
        return "🟡"
    if value in {"INVALIDATED", "REJECTED"}:
        return "🔴"
    if value in {"BOUGHT", "MET"}:
        return "✅"
    return "🔵"


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
            chunks = split_telegram_message(text_message)
            for chunk in chunks:
                bot.sendMessage(receiver_id, chunk)
            return {
                "status": "ok",
                "receiver_id": receiver_id,
                "attempt": attempt,
                "chunks": len(chunks),
            }
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


def split_telegram_message(text_message, limit=3900):
    text = str(text_message or "")
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        addition = len(line) + 1
        if current and current_len + addition > limit:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if addition > limit:
            for start in range(0, len(line), limit):
                part = line[start : start + limit]
                if current:
                    chunks.append("\n".join(current))
                    current = []
                    current_len = 0
                chunks.append(part)
            continue
        current.append(line)
        current_len += addition
    if current:
        chunks.append("\n".join(current))
    return chunks


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


def _condition_operational_note(item, position_tickers=None, pending_buy_tickers=None):
    position_tickers = position_tickers or set()
    pending_buy_tickers = pending_buy_tickers or set()
    ticker = str(item.get("ticker", "")).strip().upper()
    metadata = item.get("metadata", {}) or {}
    auto_decision = metadata.get("auto_decision")
    auto_reason = metadata.get("auto_decision_reason")

    if auto_decision:
        return f"azione: {short_condition(auto_reason or str(auto_decision), max_len=120)}"
    if ticker in position_tickers:
        return "azione: gia in portafoglio; in autonomia completa puo diventare incremento posizione"
    if ticker in pending_buy_tickers:
        return "azione: proposta buy gia pending"
    return "azione: setup da valutare per proposta/acquisto in base alla modalita autonomia"


def _condition_brief(item, include_details=False, position_tickers=None, pending_buy_tickers=None):
    metadata = item.get("metadata", {}) or {}
    scenario = _best_entry_scenario(item) or {}
    ticker = item.get("ticker", "n/d")
    state = metadata.get("scenario_state") or scenario.get("state") or item.get("status") or "waiting"
    close = (
        metadata.get("current_price")
        or metadata.get("last_price")
        or scenario.get("last_price")
        or metadata.get("close")
    )
    trigger = metadata.get("trigger_price") or scenario.get("trigger") or metadata.get("resistance_10")
    volume_ratio = (
        metadata.get("volume_ratio_ma10")
        or metadata.get("volume_ratio")
        or scenario.get("last_volume_ratio")
    )
    reason = metadata.get("scenario_reason") or metadata.get("reason") or scenario.get("reason")
    distance = _condition_sort_key(item)

    bits = [f"{_scenario_dot(state)} {ticker} [{state}]"]
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
    line = " | ".join(bits)
    if not include_details:
        ticker_key = str(ticker or "").strip().upper()
        if ticker_key in (position_tickers or set()):
            action = "🔵 INCREMENTO/RIBILANCIAMENTO se confermato"
        elif ticker_key in (pending_buy_tickers or set()):
            action = "⏳ BUY gia pending"
        else:
            action = "🟢 BUY se confermato"
        return f"{line} | azione: {action}"
    details = [line]
    condition_text = short_condition(item.get("condition"), max_len=110)
    if condition_text:
        details.append(f"  condizione: {condition_text}")
    if reason:
        details.append(f"  esito: {short_condition(reason, max_len=110)}")
    details.append(f"  {_condition_operational_note(item, position_tickers, pending_buy_tickers)}")
    return "\n".join(details)


def _invalidated_condition_brief(item):
    ticker = item.get("ticker", "n/d")
    notes = item.get("notes") or []
    invalidation_note = ""
    for entry in reversed(notes):
        note = str(entry.get("note") or "").strip()
        if "invalidat" in note.lower():
            invalidation_note = note
            break
    if invalidation_note:
        cause = invalidation_note.split(":", 1)[-1].strip()
    else:
        metadata = item.get("metadata", {}) or {}
        if metadata.get("liquidity_ok") is False:
            cause = "liquidita insufficiente"
        else:
            cause = str(item.get("reason") or "condizione non piu valida").strip()

    return f"🔴 {ticker}: INVALIDATO\n  motivo: {cause}"


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


def _action_timestamp(item):
    when = item.get("confirmed_at") or item.get("rejected_at") or item.get("created_at")
    try:
        return datetime.fromisoformat(str(when))
    except (TypeError, ValueError):
        return None


def _last_run_actions(actions, run_started_at=None, window_seconds=180):
    stamped = []
    for item in actions:
        when = _action_timestamp(item)
        if when:
            stamped.append((when, item))
    if not stamped:
        return []
    if run_started_at:
        return [item for when, item in stamped if when >= run_started_at]
    stamped.sort(key=lambda pair: pair[0])
    latest = stamped[-1][0]
    lower_bound = latest - timedelta(seconds=window_seconds)
    return [item for when, item in stamped if when >= lower_bound]


def _action_effect_brief(item):
    status = item.get("status", "n/d")
    action = item.get("action", "azione")
    ticker = item.get("ticker", "n/d")
    metadata = item.get("metadata", {}) or {}
    amount = metadata.get("amount")
    entry_price = metadata.get("entry_price")
    scenario_state = metadata.get("scenario_state")
    condition = metadata.get("condition")
    reason = item.get("reason") or metadata.get("scenario_reason")

    if status == "confirmed":
        if action == "buy_virtual_position":
            head = f"- {ticker}: BUY applicato"
            if amount is not None:
                head += f" {format_money(amount)}"
            if entry_price is not None:
                head += f" @ {format_number(entry_price)}"
        elif action in {"sell_virtual_position", "reduce_virtual_position"}:
            head = f"- {ticker}: SELL/RIDUZIONE applicata"
            if amount is not None:
                head += f" {format_money(amount)}"
        else:
            head = f"- {ticker}: {str(action).replace('_', ' ')} applicata"
    elif status == "skipped":
        decision = str(metadata.get("decision") or "nessuna modifica").replace("_", " ")
        head = f"- {ticker}: nessuna modifica ({decision})"
    elif status == "rejected":
        head = f"- {ticker}: proposta rifiutata"
    else:
        head = f"- {ticker}: {str(action).replace('_', ' ')} [{status}]"

    details = [head]
    if scenario_state:
        details.append(f"  stato: {scenario_state}")
    if condition:
        details.append(f"  trigger: {short_condition(condition, max_len=135)}")
    elif reason:
        details.append(f"  motivo: {short_condition(reason, max_len=135)}")
    if reason and condition:
        details.append(f"  motivo: {short_condition(reason, max_len=135)}")
    return "\n".join(details)


def _portfolio_change_brief(item):
    """Return one unambiguous portfolio mutation for the consolidated Telegram message."""
    action = item.get("action")
    ticker = item.get("ticker", "n/d")
    metadata = item.get("metadata", {}) or {}
    reason = str(item.get("reason") or "")
    price = metadata.get("entry_price") if action == "buy_virtual_position" else metadata.get("reference_price")
    price_text = f" @ {format_number(price)}" if price is not None else ""
    if action == "buy_virtual_position":
        verb = "INCREMENTATO" if "INCREMENTO" in reason.upper() else "COMPRATO"
        return f"- {verb} {ticker}{price_text}"
    if action == "sell_virtual_position":
        return f"- VENDUTO {ticker}{price_text}"
    if action == "reduce_virtual_position":
        percent = metadata.get("percent")
        percent_text = f" {format_number(percent)}%" if percent is not None else ""
        if metadata.get("source") == "deterministic_take_profit":
            return f"- TAKE PROFIT {ticker}: venduto{percent_text}{price_text}"
        return f"- RIDOTTO {ticker}: venduto{percent_text}{price_text}"
    return None


def _portfolio_changes_since_last_summary(portfolio_id):
    notification_state = load_notification_state(portfolio_id)
    last_sent_at = parse_iso((notification_state.get("consolidated_summary") or {}).get("sent_at"))
    cutoff = last_sent_at or (datetime.now() - timedelta(hours=24))
    portfolio = load_portfolio(portfolio_state_path(portfolio_id)) or {}
    actions = [
        item
        for item in portfolio.get("closed_proposals", [])
        if (_action_timestamp(item) or datetime.min) > cutoff
    ]
    return [
        line
        for item in actions
        if item.get("status") == "confirmed"
        for line in [_portfolio_change_brief(item)]
        if line
    ]


def build_readable_monitoring_summary(extra_note="", portfolio_id=None):
    resolved_id, portfolio_label = portfolio_display_label(portfolio_id)
    path = portfolio_state_path(resolved_id)
    settings = load_telegram_settings(resolved_id)
    max_items = int(settings.get("max_monitoring_items") or 5)
    status = portfolio_status_summary(path)
    performance = calculate_portfolio_performance(path, record_history=False)
    conditions = list_monitored_conditions(status=None, path=path)
    waiting = sorted(
        [item for item in conditions if item.get("status") == "waiting"],
        key=_condition_sort_key,
    )
    met = sorted(
        [item for item in conditions if item.get("status") == "met"],
        key=_condition_sort_key,
    )
    invalidated_all = sorted(
        [item for item in conditions if item.get("status") == "invalidated"],
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    invalidated_by_ticker = {}
    for item in invalidated_all:
        ticker = str(item.get("ticker") or "").strip().upper()
        if ticker and ticker not in invalidated_by_ticker:
            invalidated_by_ticker[ticker] = item
    invalidated = list(invalidated_by_ticker.values())
    pending_buy = status.get("pending_buy_proposals", [])
    positions = status.get("positions", [])
    position_tickers = {
        str(item.get("ticker", "")).strip().upper()
        for item in positions
        if item.get("status") == "open"
    }
    pending_buy_tickers = {
        str(item.get("ticker", "")).strip().upper()
        for item in pending_buy
        if item.get("status") == "pending"
    }
    portfolio = load_portfolio(path) or {}
    run_state = load_agent_run_state()
    run_started_at = parse_iso(run_state.get("last_started_at"))
    last_run_actions = _last_run_actions(
        portfolio.get("closed_proposals", []),
        run_started_at=run_started_at,
    )
    recent_actions = []

    position_perf = {item.get("ticker"): item for item in performance.get("positions", [])}
    total_pnl = float(performance.get("total_pnl") or 0)
    total_pnl_pct = float(performance.get("total_pnl_pct") or 0)

    lines = [
        "📊 Autonomous Trading Agent",
        f"Monitor | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Portafoglio | {portfolio_label}",
        "",
        "💼 Portafoglio",
        f"Valore: {format_money(performance.get('total_value'))}",
        f"P/L: {signal_dot(total_pnl_pct)} {format_signed_money(total_pnl)} ({format_pct(total_pnl_pct)})",
        f"Cash: {format_money(status.get('cash'))}",
        f"Posizioni: {len(positions)} | Pending buy: {len(pending_buy)}",
    ]

    if positions:
        lines.extend(["", "📌 Posizioni"])
        for item in positions:
            ticker = item.get("ticker", "n/d")
            lines.append(_position_brief(item, position_perf.get(ticker)))

    if last_run_actions:
        lines.extend(["", f"Effetti ultimo run ({len(last_run_actions)})"])
        for item in last_run_actions:
            lines.append(_action_effect_brief(item))
    else:
        lines.extend(["", "Effetti ultimo run", "Nessuna modifica al portafoglio registrata nell'ultimo ciclo."])

    if met:
        lines.extend(["", f"✅ Setup confermati / trigger operativi ({len(met)})"])
        for item in met[:max_items]:
            lines.append(
                _condition_brief(
                    item,
                    include_details=True,
                    position_tickers=position_tickers,
                    pending_buy_tickers=pending_buy_tickers,
                )
            )
        if len(met) > max_items:
            lines.append(f"... altri {len(met) - max_items} setup confermati")

    if waiting:
        lines.extend(["", f"🎯 Trigger in attesa ({len(waiting)})"])
        lines.append("🟢 operativo/acquisto | 🟡 vicino o in conferma | 🔵 attesa/incremento")
        for item in waiting[:max_items]:
            lines.append(
                _condition_brief(
                    item,
                    position_tickers=position_tickers,
                    pending_buy_tickers=pending_buy_tickers,
                )
            )
        if len(waiting) > max_items:
            lines.append(f"... altri {len(waiting) - max_items} trigger in monitoraggio")

    if invalidated:
        lines.extend(["", f"⚠️ Trigger invalidati: {len(invalidated)}"])
        visible_invalidated = invalidated[: min(3, max_items)]
        for item in visible_invalidated:
            lines.append(_invalidated_condition_brief(item))
        if len(invalidated) > len(visible_invalidated):
            lines.append(f"... altri {len(invalidated) - len(visible_invalidated)} trigger invalidati")

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


def build_readable_performance_summary(performance=None, extra_note="", portfolio_id=None):
    perf = performance or calculate_portfolio_performance()
    if perf.get("status") != "ok":
        return perf.get("message", "Performance non disponibile.")

    _, portfolio_label = portfolio_display_label(portfolio_id)
    total_pnl = float(perf.get("total_pnl") or 0)
    total_pnl_pct = float(perf.get("total_pnl_pct") or 0)
    lines = [
        "📊 Autonomous Trading Agent",
        f"Performance | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Portafoglio | {portfolio_label}",
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


def build_all_portfolios_summary(extra_note=""):
    from finance_tools.portfolio_summary import build_portfolios_summary

    summary = build_portfolios_summary(include_archived=False)
    totals = summary.get("totals") or {}
    rows = summary.get("items") or []
    total_pnl = float(totals.get("pnl") or 0)
    total_pnl_pct = float(totals.get("pnl_pct") or 0)
    lines = [
        "📊 Autonomous Trading Agent",
        f"Riepilogo portafogli | {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "💼 Totale portafogli virtuali",
        f"Portafogli attivi: {sum(1 for row in rows if row.get('status') == 'active')}",
        f"Capitale iniziale: {format_money(totals.get('initial_capital'))}",
        f"Patrimonio: {format_money(totals.get('total_value'))}",
        f"Titoli: {format_money(totals.get('positions_value'))}",
        f"Cash: {format_money(totals.get('cash'))}",
        f"P/L: {signal_dot(total_pnl_pct)} {format_signed_money(total_pnl)} ({format_pct(total_pnl_pct)})",
        "",
        "COSA È CAMBIATO, PORTAFOGLIO PER PORTAFOGLIO",
    ]

    for row in rows:
        portfolio_id = row.get("portfolio_id")
        lines.append(f"{row.get('name') or portfolio_id} [{portfolio_id}]")
        changes = _portfolio_changes_since_last_summary(portfolio_id)
        lines.extend(changes or ["- NESSUNA MODIFICA"])

    for index, row in enumerate(rows, start=1):
        pnl = float(row.get("pnl") or 0)
        pnl_pct = float(row.get("pnl_pct") or 0)
        lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━━━━━",
                f"{index}. {row.get('name') or row.get('portfolio_id')} [{row.get('portfolio_id')}]",
                f"Profilo: {row.get('risk_profile') or 'n/d'} | Stato: {row.get('status') or 'n/d'}",
                f"Patrimonio: {format_money(row.get('total_value'))}",
                f"P/L: {signal_dot(pnl_pct)} {format_signed_money(pnl)} ({format_pct(pnl_pct)})",
                f"Titoli: {format_money(row.get('positions_value'))} ({format_plain_pct(row.get('exposure_pct'))})",
                f"Cash: {format_money(row.get('cash'))} ({format_plain_pct(row.get('cash_pct'))})",
                f"Posizioni: {row.get('positions_count') or 0}",
            ]
        )
        positions = row.get("positions") or []
        if positions:
            lines.append("Posizioni:")
            for position in positions:
                position_pnl = float(position.get("pnl") or 0)
                position_pnl_pct = float(position.get("pnl_pct") or 0)
                daily = position.get("daily_change_pct")
                position_line = (
                    f"{signal_dot(position_pnl_pct)} {position.get('ticker')}: "
                    f"{format_money(position.get('market_value'))} | "
                    f"P/L {format_signed_money(position_pnl)} ({format_pct(position_pnl_pct)})"
                )
                if daily is not None:
                    position_line += f" | oggi {format_pct(daily)}"
                lines.append(position_line)
        else:
            lines.append("Posizioni: nessuna")
        if row.get("quote_errors_count"):
            lines.append(f"⚠️ Prezzi non disponibili: {row['quote_errors_count']}")

    if extra_note:
        lines.extend(["", "ℹ️ Nota", short_condition(extra_note, max_len=200)])
    return "\n".join(lines)


def build_monitoring_summary(extra_note="", portfolio_id=None):
    return build_readable_monitoring_summary(
        extra_note=extra_note,
        portfolio_id=portfolio_id,
    )


def send_monitoring_summary(extra_note="", portfolio_id=None):
    message = build_monitoring_summary(
        extra_note=extra_note,
        portfolio_id=portfolio_id,
    )
    result = send_telegram_message(message)
    return {**result, "message": message}


def send_all_portfolios_summary(extra_note=""):
    message = build_all_portfolios_summary(extra_note=extra_note)
    result = send_telegram_message(message)
    if result.get("status") == "ok":
        from finance_tools.portfolio_registry import list_portfolios

        sent_at = now_iso()
        for item in (list_portfolios(include_archived=False).get("items") or []):
            portfolio_id = item.get("id")
            state = load_notification_state(portfolio_id)
            state["consolidated_summary"] = {"sent_at": sent_at}
            save_notification_state(state, portfolio_id)
    return {**result, "message": message}


def send_performance_summary(
    extra_note="",
    force=False,
    min_interval_minutes=180,
    portfolio_id=None,
):
    resolved_id = active_portfolio_id(portfolio_id)
    path = portfolio_state_path(resolved_id)
    performance = calculate_portfolio_performance(path, record_history=False)
    if not force:
        allowed, reason = should_send_performance_alert(performance, min_interval_minutes=min_interval_minutes)
        if not allowed:
            return {"status": "skipped", "reason": reason, "message": ""}

    message = build_readable_performance_summary(
        performance,
        extra_note=extra_note,
        portfolio_id=resolved_id,
    )
    result = send_telegram_message(message)
    return {**result, "message": message}
