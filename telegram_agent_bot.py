import argparse
import html
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import telepot

from finance_tools.chart_tool import generate_chart_context
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.portfolio_store import portfolio_status_summary
from finance_tools.ticker_resolver import resolve_ticker, resolve_ticker_context
from finance_tools.telegram_tool import (
    TELEGRAM_RECEIVER_ENV,
    TELEGRAM_TOKEN_ENV,
    TELEGRAM_TOKEN_FALLBACK_ENV,
    format_trigger_event,
    is_transient_telegram_error,
)


STATE_FILE = PROJECT_ROOT / "telegram_agent_state.json"
MAX_TELEGRAM_MESSAGE = 3900
AGENT_SEMAPHORE = threading.Semaphore(1)
TELEGRAM_CONFLICT_BACKOFF_SECONDS = 30
TELEGRAM_NETWORK_BACKOFF_SECONDS = 10
TELEGRAM_SEND_RETRIES = 2
TELEGRAM_SEND_RETRY_DELAY_SECONDS = 5


def log(message):
    print(f"[telegram-agent] {message}", flush=True)


def load_state():
    if not STATE_FILE.exists():
        return {"offset": 0, "history": []}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"offset": 0, "history": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def split_message(text):
    text = str(text or "").strip()
    if not text:
        return ["Risposta vuota."]
    chunks = []
    while len(text) > MAX_TELEGRAM_MESSAGE:
        cut = text.rfind("\n", 0, MAX_TELEGRAM_MESSAGE)
        if cut < 1000:
            cut = MAX_TELEGRAM_MESSAGE
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    chunks.append(text)
    return chunks


def telegram_html(text):
    escaped = html.escape(str(text or "").strip())
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    lines = []
    for raw_line in escaped.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        heading = re.match(r"^#{2,4}\s+(.+)$", line)
        if heading:
            lines.append(f"<b>{heading.group(1)}</b>")
            continue
        numbered = re.match(r"^(\d+)\.\s+(.+)$", line)
        if numbered:
            lines.append(f"{numbered.group(1)}. {numbered.group(2)}")
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            lines.append(f"- {bullet.group(1)}")
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def telegram_call_with_retry(operation):
    last_error = None
    for attempt in range(1, TELEGRAM_SEND_RETRIES + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if not is_transient_telegram_network_error(exc) or attempt >= TELEGRAM_SEND_RETRIES:
                raise
            log(
                "Invio Telegram non riuscito per errore rete transitorio; "
                f"tentativo {attempt}/{TELEGRAM_SEND_RETRIES}. Riprovo tra {TELEGRAM_SEND_RETRY_DELAY_SECONDS}s."
            )
            time.sleep(TELEGRAM_SEND_RETRY_DELAY_SECONDS)
    raise last_error


def send_text(bot, chat_id, text, parse=True):
    for chunk in split_message(text):
        if parse:
            telegram_call_with_retry(
                lambda: bot.sendMessage(chat_id, telegram_html(chunk), parse_mode="HTML", disable_web_page_preview=True)
            )
        else:
            telegram_call_with_retry(lambda: bot.sendMessage(chat_id, chunk, disable_web_page_preview=True))


def send_photo(bot, chat_id, path, caption=""):
    with Path(path).open("rb") as image:
        if caption:
            telegram_call_with_retry(
                lambda: bot.sendPhoto(chat_id, image, caption=telegram_html(caption[:1024]), parse_mode="HTML")
            )
        else:
            telegram_call_with_retry(lambda: bot.sendPhoto(chat_id, image))


def is_getupdates_conflict(exc):
    text = str(exc)
    return "409" in text and "terminated by other getUpdates request" in text


def is_transient_telegram_network_error(exc):
    return is_transient_telegram_error(exc)


def extract_ticker(text, history=None):
    resolved = resolve_ticker(text, history=history)
    if resolved:
        return resolved

    upper_text = str(text or "").upper()
    matches = re.findall(r"\b[A-Z]{1,6}(?:[.-][A-Z]{1,4})?\b", upper_text)
    ignored = {
        "EUR", "MACD", "RSI", "ADX", "DI", "AI", "WILLIAMS",
        "IL", "LO", "LA", "LE", "GLI", "DEL", "DEI", "DI", "DA", "SU", "PER",
        "MI", "TU", "SI", "NO", "OK",
        "TITOLO", "GRAFICO", "GRAFICI", "MANDAMI", "MANDA", "INVIA", "APRIMI",
        "PREZZO", "VOLUMI", "VOLUME", "USCIRE", "ENTRARE", "SEGNALE", "SEGNALI",
    }
    for match in matches:
        if match not in ignored and ("." in match or "-" in match):
            return match
    for match in matches:
        if match not in ignored and len(match) >= 2:
            return match
    for item in reversed(history or []):
        ticker = extract_ticker(item.get("content", ""), history=[])
        if ticker:
            return ticker
    return ""


def is_chart_request(text):
    command = str(text or "").lower()
    chart_words = ("grafico", "grafici", "chart", "immagine")
    return any(word in command for word in chart_words)


def handle_chart_request(bot, chat_id, text, history):
    ticker = extract_ticker(text, history=history)
    if not ticker:
        send_text(bot, chat_id, "Dimmi anche il ticker, per esempio: mandami il grafico di CPR.MI")
        return "Richiesto grafico ma ticker mancante."

    context = resolve_ticker_context(text, history=history)
    prefix = f"{context}\n" if context else ""
    send_text(bot, chat_id, f"{prefix}Grafico **{ticker}**\nGenero e invio i grafici tecnici...")
    result = generate_chart_context(ticker=ticker, days=70, period="1y")
    if result.get("status") != "ok":
        raise RuntimeError(f"Errore generazione grafici {ticker}: {result}")

    files = result.get("files", [])
    labels = {
        "price_alligator": "Prezzo, trend e livelli",
        "momentum": "Volumi, RSI, Stocastico, Williams e MACD",
        "adx": "ADX e direzionalita",
    }
    sent = 0
    for file_path in files:
        name = Path(file_path).stem.lower()
        caption_label = next((label for key, label in labels.items() if key in name), "Grafico tecnico")
        send_photo(bot, chat_id, file_path, caption=f"{ticker} - {caption_label}")
        sent += 1

    snapshot = result.get("snapshot", {})
    close = snapshot.get("close")
    rsi = snapshot.get("rsi")
    macd = snapshot.get("macd")
    macd_signal = snapshot.get("macd_signal")
    adx = snapshot.get("adx")
    summary = (
        f"{ticker} - grafici inviati: {sent}\n"
        f"Close: {close if close is not None else 'n/d'} | "
        f"RSI: {rsi if rsi is not None else 'n/d'} | "
        f"MACD: {macd if macd is not None else 'n/d'} / Signal {macd_signal if macd_signal is not None else 'n/d'} | "
        f"ADX: {adx if adx is not None else 'n/d'}"
    )
    send_text(bot, chat_id, summary)
    return summary


def extract_agent_answer(output):
    marker = "[agent] Risposta finale agente ricevuta"
    if marker in output:
        return output.split(marker, 1)[1].strip()
    interrupted = re.search(r"Run interrotta prima della risposta finale:.*", output or "", flags=re.DOTALL)
    if interrupted:
        first_line = interrupted.group(0).splitlines()[0]
        if "InternalServerError" in first_line or "Error code: 500" in first_line:
            return (
                "L'agente AI ha avuto un errore temporaneo lato OpenAI durante l'elaborazione.\n"
                "Il bot Telegram resta attivo e il portafoglio locale non e stato bloccato.\n"
                "Per stato, performance, trigger e grafici posso rispondere direttamente senza rilanciare l'agente."
            )
        return first_line

    clean_lines = [
        line for line in str(output or "").splitlines()
        if line.strip() and not line.lstrip().startswith("[agent]")
    ]
    if clean_lines:
        return "\n".join(clean_lines[-20:]).strip()
    return "L'agente non ha prodotto una risposta leggibile. Controlla i log dalla GUI."


def build_agent_context(history, message):
    resolver_context = resolve_ticker_context(message, history=history)
    lines = [
        "Questa richiesta arriva da Telegram.",
        "Rispondi in modo compatto, chiaro e adatto a Telegram.",
        "Usa sezioni brevi, bullet con trattino, pochi emoji funzionali e niente tabelle Markdown.",
        "Usa grassetto solo per ticker, stato e decisioni importanti.",
        "Se l'utente chiede stato, segnali di uscita, performance, watchlist o condizioni, usa i tool del portafoglio.",
        "Se l'utente chiede analisi live con Playwright, falla solo se necessario e avvisa che puo richiedere tempo.",
        "Regola operativa: in modalita autonomous_virtual l'agente puo applicare operazioni virtuali di acquisto, vendita, riduzione o ribilanciamento quando i trigger sono confermati; l'utente viene notificato via Telegram.",
        "Non dire che l'agente non esegue vendite automatiche: valeva solo per la vecchia modalita con conferma utente.",
        "",
        "Contesto recente Telegram:",
    ]
    for item in history[-8:]:
        role = "Utente" if item.get("role") == "user" else "Agente"
        lines.append(f"{role}: {item.get('content', '')}")
    if resolver_context:
        lines.extend(["", resolver_context])
    lines.extend(["", "Nuova richiesta Telegram:", message])
    return "\n".join(lines)


def run_agent(message, history, timeout):
    prompt = build_agent_context(history, message)
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "agent_portfolio_manager.py"),
        "--suppress-auto-telegram-summary",
        prompt,
    ]
    log("Invio richiesta all'agente...")
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    output = result.stdout.strip() if result.stdout else result.stderr.strip()
    if result.returncode != 0:
        raise RuntimeError(f"Agente terminato con exit code {result.returncode}: {extract_agent_answer(output)}")
    return extract_agent_answer(output)


def process_agent_request_async(bot, chat_id, text, history, timeout):
    if not AGENT_SEMAPHORE.acquire(blocking=False):
        send_text(
            bot,
            chat_id,
            "Agente gia impegnato in una richiesta lunga. Puoi comunque farmi domande rapide su portafoglio, trigger o grafici.",
        )
        return
    try:
        answer = run_agent(text, history, timeout=timeout)
        send_text(bot, chat_id, answer)
    except subprocess.TimeoutExpired:
        send_text(
            bot,
            chat_id,
            "Timeout: l'agente ha impiegato troppo. Il bot resta attivo; riprova con una richiesta piu specifica o controlla i log.",
        )
    except Exception as exc:
        send_text(bot, chat_id, f"Errore agente: {exc}")
    finally:
        AGENT_SEMAPHORE.release()


def handle_command(text):
    command = text.strip().lower()
    if command in {"/start", "start", "aiuto", "/help"}:
        return (
            "Autonomous Trading Agent Telegram attivo.\n\n"
            "Puoi chiedere ad esempio:\n"
            "- quali segnali attendi per uscire da CPR.MI?\n"
            "- mostra stato operativo\n"
            "- mostra performance\n"
            "- quali titoli stai monitorando?\n"
            "- aggiungi VOD.L alla watchlist con priorita high\n"
            "- mandami il grafico di CPR.MI\n"
            "- analizza AMP.MI\n\n"
            "Le operazioni restano sul portafoglio virtuale."
        )
    return None


def fmt_money(value):
    try:
        return f"{float(value):,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "n/d"


def fmt_pct(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/d"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


def is_local_status_request(text):
    command = str(text or "").lower().strip()
    return any(
        phrase in command
        for phrase in (
            "stato operativo",
            "portafoglio",
            "performance",
            "rendimento",
            "titoli monitorati",
            "monitorati",
            "condizioni monitorate",
            "trigger monitorati",
        )
    )


def build_local_status_answer(text):
    command = str(text or "").lower()
    status = portfolio_status_summary()
    performance = calculate_portfolio_performance(record_history=False)
    if status.get("status") != "ok":
        return "Portafoglio non disponibile in questo momento."

    positions = status.get("positions", [])
    conditions = status.get("monitored_conditions", [])
    waiting = [item for item in conditions if item.get("status") == "waiting"]
    met = [item for item in conditions if item.get("status") == "met"]
    pending = status.get("pending_buy_proposals", []) + status.get("pending_other_proposals", [])

    if "performance" in command or "rendimento" in command:
        lines = [
            "**Performance portafoglio**",
            f"Valore: {fmt_money(performance.get('total_value'))}",
            f"P/L: {fmt_money(performance.get('total_pnl'))} ({fmt_pct(performance.get('total_pnl_pct'))})",
            f"Cash: {fmt_money(status.get('cash'))}",
            "",
            "**Posizioni**",
        ]
        perf_by_ticker = {item.get("ticker"): item for item in performance.get("positions", [])}
        for pos in positions[:8]:
            ticker = pos.get("ticker", "n/d")
            perf = perf_by_ticker.get(ticker, {})
            lines.append(
                f"- {ticker}: {fmt_money(perf.get('market_value'))} | "
                f"P/L {fmt_money(perf.get('pnl'))} ({fmt_pct(perf.get('pnl_pct'))}) | "
                f"oggi {fmt_pct(perf.get('daily_change_pct'))}"
            )
        if not positions:
            lines.append("- nessuna posizione aperta")
        return "\n".join(lines)

    lines = [
        "**Stato operativo**",
        f"Capitale: {fmt_money(status.get('initial_capital'))}",
        f"Cash: {fmt_money(status.get('cash'))}",
        f"Valore: {fmt_money(performance.get('total_value'))}",
        f"P/L: {fmt_money(performance.get('total_pnl'))} ({fmt_pct(performance.get('total_pnl_pct'))})",
        f"Posizioni: {len(positions)} | Pending: {len(pending)}",
        f"Trigger waiting: {len(waiting)} | Trigger scattati: {len(met)}",
    ]

    if positions:
        lines.extend(["", "**Posizioni aperte**"])
        for pos in positions[:8]:
            lines.append(f"- {pos.get('ticker')}: investito {fmt_money(pos.get('allocated_amount'))}, entry {pos.get('entry_price', 'n/d')}")

    if waiting:
        lines.extend(["", "**Primi trigger in monitoraggio**"])
        for item in waiting[:6]:
            lines.append(f"- {item.get('ticker')}: {item.get('condition', 'n/d')}")
        if len(waiting) > 6:
            lines.append(f"- altri {len(waiting) - 6} trigger")

    return "\n".join(lines)


def is_status_or_trigger_question(text):
    command = str(text or "").lower()
    keywords = (
        "trigger",
        "scatta",
        "segnale",
        "segnali",
        "uscita",
        "uscire",
        "entrata",
        "entrare",
        "compra",
        "comprerai",
        "cosa farai",
        "quando",
        "condizione",
        "condizioni",
    )
    return any(word in command for word in keywords)


def find_ticker_items(ticker):
    ticker = str(ticker or "").upper().strip()
    status = portfolio_status_summary()
    positions = [
        item for item in status.get("positions", [])
        if str(item.get("ticker", "")).upper() == ticker and item.get("status", "open") == "open"
    ]
    conditions = [
        item for item in status.get("monitored_conditions", [])
        if str(item.get("ticker", "")).upper() == ticker and item.get("status") in {"waiting", "met"}
    ]
    proposals = [
        item for item in (status.get("pending_buy_proposals", []) + status.get("pending_other_proposals", []))
        if str(item.get("ticker", "")).upper() == ticker
    ]
    return status, positions, conditions, proposals


def handle_fast_portfolio_question(text, history):
    if not is_status_or_trigger_question(text):
        return None
    ticker = extract_ticker(text, history=history)
    if not ticker:
        return None

    status, positions, conditions, proposals = find_ticker_items(ticker)
    if status.get("status") != "ok":
        return "Portafoglio non disponibile in questo momento."
    if not positions and not conditions and not proposals:
        return None

    lines = [f"**{ticker}** - risposta rapida"]
    if positions:
        pos = positions[0]
        lines.append(
            "In portafoglio: si | "
            f"entry {pos.get('entry_price', 'n/d')} | "
            f"allocato {pos.get('allocated_amount', 'n/d')} EUR"
        )
    else:
        lines.append("In portafoglio: no")

    if conditions:
        lines.append("")
        lines.append("**Condizioni monitorate**")
        for item in conditions[:3]:
            rendered = format_trigger_event(item).replace("\n  ", "\n")
            lines.append(rendered)
        if len(conditions) > 3:
            lines.append(f"... altre {len(conditions) - 3} condizioni")
    else:
        lines.append("")
        lines.append("Nessuna condizione monitorata salvata per questo ticker.")

    if proposals:
        lines.append("")
        lines.append("**Proposte pending**")
        for item in proposals[:3]:
            lines.append(
                f"- {item.get('id')}: {item.get('action')} "
                f"{item.get('amount', 'n/d')} EUR | stato {item.get('status', 'n/d')}"
            )

    lines.append("")
    lines.append("**Cosa fa l'agente quando scatta**")
    lines.append(
        "- rivaluta grafico/indicatori e news solo se il trigger e in conferma o il titolo e in portafoglio;"
    )
    lines.append(
        "- se il segnale resta valido, in modalita autonoma puo creare e applicare una operazione virtuale;"
    )
    lines.append(
        "- se il segnale peggiora, mantiene monitoraggio, riduce/vende una posizione o invalida il trigger."
    )
    lines.append("")
    lines.append("Risposta locale veloce: non ho lanciato Playwright ne il modello AI.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Telegram bridge per Autonomous Trading Agent.")
    parser.add_argument("--poll-seconds", type=float, default=3.0, help="Intervallo polling Telegram.")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout massimo richiesta agente.")
    parser.add_argument("--once", action="store_true", help="Legge eventuali messaggi una sola volta e termina.")
    args = parser.parse_args()

    load_env_file()
    token = __import__("os").getenv(TELEGRAM_TOKEN_ENV) or __import__("os").getenv(TELEGRAM_TOKEN_FALLBACK_ENV)
    receiver_id = __import__("os").getenv(TELEGRAM_RECEIVER_ENV)
    if not token or not receiver_id:
        raise SystemExit("Configura TELEGRAM_BOT_TOKEN e TELEGRAM_RECEIVER_ID in .env")

    allowed_chat_id = str(receiver_id)
    bot = telepot.Bot(token)
    state = load_state()
    log(f"Bridge Telegram avviato | allowed_chat_id={allowed_chat_id}")
    send_text(bot, allowed_chat_id, "Autonomous Trading Agent Telegram bridge avviato. Scrivi 'aiuto' per i comandi.")

    while True:
        try:
            updates = bot.getUpdates(offset=int(state.get("offset", 0) or 0), timeout=20)
            for update in updates:
                state["offset"] = int(update["update_id"]) + 1
                message = update.get("message") or update.get("edited_message") or {}
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = (message.get("text") or "").strip()
                if not text:
                    continue
                if chat_id != allowed_chat_id:
                    log(f"Ignoro messaggio da chat non autorizzata: {chat_id}")
                    continue

                log(f"Messaggio ricevuto: {text}")
                shortcut = handle_command(text)
                if shortcut:
                    answer = shortcut
                elif is_chart_request(text):
                    answer = handle_chart_request(bot, chat_id, text, state.get("history", []))
                elif is_local_status_request(text):
                    answer = build_local_status_answer(text)
                elif (fast_answer := handle_fast_portfolio_question(text, state.get("history", []))):
                    answer = fast_answer
                else:
                    answer = (
                        "Richiesta presa in carico. Ti rispondo qui appena l'agente termina; "
                        "nel frattempo il bot resta disponibile per domande rapide."
                    )
                    send_text(bot, chat_id, answer)
                    history_snapshot = list(state.get("history", []))
                    worker = threading.Thread(
                        target=process_agent_request_async,
                        args=(bot, chat_id, text, history_snapshot, args.timeout),
                        daemon=True,
                    )
                    worker.start()
                    history = state.setdefault("history", [])
                    history.extend([
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": answer[:1500]},
                    ])
                    state["history"] = history[-12:]
                    save_state(state)
                    continue

                send_text(bot, chat_id, answer)
                history = state.setdefault("history", [])
                history.extend([
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": answer[:1500]},
                ])
                state["history"] = history[-12:]
                save_state(state)

            save_state(state)
        except KeyboardInterrupt:
            log("Interrotto dall'utente.")
            break
        except Exception as exc:
            if is_getupdates_conflict(exc):
                log(
                    "Conflitto Telegram getUpdates: esiste un altro bot polling con lo stesso token. "
                    f"Non invio errore in chat; riprovo tra {TELEGRAM_CONFLICT_BACKOFF_SECONDS}s."
                )
                time.sleep(TELEGRAM_CONFLICT_BACKOFF_SECONDS)
                continue
            if is_transient_telegram_network_error(exc):
                log(
                    "Errore rete Telegram transitorio. "
                    f"Non invio errore in chat; riprovo tra {TELEGRAM_NETWORK_BACKOFF_SECONDS}s. Dettaglio: {exc}"
                )
                time.sleep(TELEGRAM_NETWORK_BACKOFF_SECONDS)
                continue
            log(f"Errore: {exc}")
            try:
                send_text(bot, allowed_chat_id, f"Errore bridge Telegram: {exc}")
            except Exception:
                pass
            time.sleep(max(args.poll_seconds, 5))

        if args.once:
            break
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
