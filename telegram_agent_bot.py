import argparse
import html
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import telepot

from finance_tools.chart_tool import generate_chart_context
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.telegram_tool import (
    TELEGRAM_RECEIVER_ENV,
    TELEGRAM_TOKEN_ENV,
    TELEGRAM_TOKEN_FALLBACK_ENV,
)


STATE_FILE = PROJECT_ROOT / "telegram_agent_state.json"
MAX_TELEGRAM_MESSAGE = 3900


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
            lines.append(f"• {bullet.group(1)}")
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def send_text(bot, chat_id, text, parse=True):
    for chunk in split_message(text):
        if parse:
            bot.sendMessage(chat_id, telegram_html(chunk), parse_mode="HTML", disable_web_page_preview=True)
        else:
            bot.sendMessage(chat_id, chunk, disable_web_page_preview=True)


def send_photo(bot, chat_id, path, caption=""):
    with Path(path).open("rb") as image:
        if caption:
            bot.sendPhoto(chat_id, image, caption=telegram_html(caption[:1024]), parse_mode="HTML")
        else:
            bot.sendPhoto(chat_id, image)


def extract_ticker(text, history=None):
    matches = re.findall(r"\b[A-Z]{1,6}(?:[.-][A-Z]{1,4})?\b", str(text or "").upper())
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

    send_text(bot, chat_id, f"📊 **{ticker}**\nGenero e invio i grafici tecnici...")
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
    return output.strip()


def build_agent_context(history, message):
    lines = [
        "Questa richiesta arriva da Telegram.",
        "Rispondi in modo compatto, chiaro e adatto a Telegram.",
        "Usa sezioni brevi, bullet con trattino, pochi emoji funzionali e niente tabelle Markdown.",
        "Usa grassetto solo per ticker, stato e decisioni importanti.",
        "Se l'utente chiede stato, segnali di uscita, performance, watchlist o condizioni, usa i tool del portafoglio.",
        "Se l'utente chiede analisi live con Playwright, falla solo se necessario e avvisa che puo richiedere tempo.",
        "",
        "Contesto recente Telegram:",
    ]
    for item in history[-8:]:
        role = "Utente" if item.get("role") == "user" else "Agente"
        lines.append(f"{role}: {item.get('content', '')}")
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
        raise RuntimeError(f"Agente terminato con exit code {result.returncode}\n\n{output}")
    return extract_agent_answer(output)


def handle_command(text):
    command = text.strip().lower()
    if command in {"/start", "start", "aiuto", "/help"}:
        return (
            "TradingWatchAgent Telegram attivo.\n\n"
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


def main():
    parser = argparse.ArgumentParser(description="Telegram bridge per TradingWatchAgent.")
    parser.add_argument("--poll-seconds", type=float, default=3.0, help="Intervallo polling Telegram.")
    parser.add_argument("--timeout", type=int, default=900, help="Timeout massimo richiesta agente.")
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
    send_text(bot, allowed_chat_id, "TradingWatchAgent Telegram bridge avviato. Scrivi 'aiuto' per i comandi.")

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
                else:
                    answer = run_agent(text, state.get("history", []), timeout=args.timeout)

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
