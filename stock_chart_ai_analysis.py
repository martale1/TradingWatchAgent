import argparse
import os
import sys
from pathlib import Path

import telepot
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from finance_charts.technical_charts import create_chart_bundle


CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_TOKEN_FALLBACK_ENV = "TELEGRAM_BOT_TOKEN_CH1"
TELEGRAM_RECEIVER_ENV = "TELEGRAM_RECEIVER_ID"
DEFAULT_STOCKS = ["VOD.L"]


def configure_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def safe_print(*values):
    print(*values, flush=True)


def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def parse_stock_list(value):
    if not value:
        return DEFAULT_STOCKS
    return [item.strip().upper() for item in value.replace(";", ",").split(",") if item.strip()]


def build_prompt(ticker, snapshot):
    return f"""Analizza i grafici tecnici allegati del titolo {ticker}.

Dati numerici calcolati dal codice:
- Data ultima barra: {snapshot['date']}
- Close: {snapshot['close']:.4f}
- Variazione 1D: {snapshot['change_1d_pct']:+.2f}%
- RSI: {snapshot['rsi']:.2f}
- Stoch K: {snapshot['stoch_k']:.2f}
- Stoch D: {snapshot['stoch_d']:.2f}
- Williams %R: {snapshot['williams_r']:.2f}
- MACD: {snapshot['macd']:.4f}
- MACD Signal: {snapshot['macd_signal']:.4f}
- ADX: {snapshot['adx']:.2f}
- DI+: {snapshot['plus_di']:.2f}
- DI-: {snapshot['minus_di']:.2f}
- Volume: {snapshot['volume']:.0f}
- Volume MA10: {snapshot['volume_ma10']:.0f}
- Volume MA5: {snapshot['volume_ma5']:.0f}
- Supporto breve, minimo 10 sedute: {snapshot['support_10']:.4f} ({snapshot['support_10_dist_pct']:+.2f}% dal close)
- Supporto medio, minimo 30 sedute: {snapshot['support_30']:.4f} ({snapshot['support_30_dist_pct']:+.2f}% dal close)
- Resistenza breve, massimo 10 sedute: {snapshot['resistance_10']:.4f} ({snapshot['resistance_10_dist_pct']:+.2f}% dal close)
- Resistenza media, massimo 30 sedute: {snapshot['resistance_30']:.4f} ({snapshot['resistance_30_dist_pct']:+.2f}% dal close)

Rispondi in italiano, compatto per Telegram, con questo formato:

{ticker} - ANALISI TECNICA

Trend:
[trend principale e qualita del trend]

Momentum:
[MACD, RSI, Stocastico, Williams %R]

Volumi:
[lettura dei volumi rispetto alle medie]

ADX / Direzionalita:
[ADX, DI+, DI-]

Supporti:
- S1: [livello]
- S2: [livello]

Resistenze:
- R1: [livello]
- R2: [livello]

Scenario:
[rialzista/neutrale/ribassista e cosa deve succedere per conferma]

Operativita prudente:
[max 4 righe, no raccomandazioni aggressive]

Regole:
- Usa i grafici allegati e i dati numerici qui sopra.
- Per Supporti e Resistenze usa prima i livelli numerici calcolati sopra; puoi aggiungere una breve nota grafica se utile.
- Indica sempre che non e consulenza finanziaria."""


def find_prompt_box(page):
    selectors = [
        "textarea[data-testid='prompt-textarea']",
        "div[contenteditable='true'][data-testid='prompt-textarea']",
        "textarea",
        "div[contenteditable='true']",
    ]
    for selector in selectors:
        locator = page.locator(selector).last
        try:
            locator.wait_for(state="visible", timeout=8000)
            return locator
        except PlaywrightTimeoutError:
            continue
    raise RuntimeError("Prompt box not found. Check login or ChatGPT UI.")


def attach_images(page, image_paths):
    safe_print("Allego immagini a ChatGPT:")
    for image_path in image_paths:
        safe_print(f"- {image_path}")
    file_input = page.locator("input[type='file']").first
    try:
        file_input.set_input_files([str(path) for path in image_paths], timeout=5000)
    except (PlaywrightError, PlaywrightTimeoutError):
        add_buttons = [
            "button[aria-label*='Allega']",
            "button[aria-label*='Attach']",
            "button:has-text('+')",
        ]
        for selector in add_buttons:
            try:
                page.locator(selector).first.click(timeout=3000)
                break
            except (PlaywrightError, PlaywrightTimeoutError):
                continue
        file_input.set_input_files([str(path) for path in image_paths], timeout=10000)
    page.wait_for_timeout(6000)


def send_prompt(page, prompt):
    initial_count = page.locator("[data-message-author-role='assistant']").count()
    box = find_prompt_box(page)
    box.click()
    box.fill(prompt)
    for selector in [
        "[data-testid='send-button']",
        "button[aria-label='Invia prompt']",
        "button[aria-label='Send prompt']",
        "button[aria-label*='Invia']",
        "button[aria-label*='Send']",
    ]:
        button = page.locator(selector).last
        try:
            button.wait_for(state="visible", timeout=3000)
            if button.is_enabled():
                button.click()
                return initial_count
        except (PlaywrightError, PlaywrightTimeoutError):
            continue
    page.keyboard.press("Enter")
    return initial_count


def wait_for_response(page, initial_count, timeout_seconds=180):
    last_text = ""
    stable_reads = 0
    elapsed = 0
    safe_print("Attendo risposta ChatGPT...")
    while elapsed < timeout_seconds:
        page.wait_for_timeout(3000)
        elapsed += 3
        messages = page.locator("[data-message-author-role='assistant']")
        count = messages.count()
        if count <= initial_count:
            if elapsed % 15 == 0:
                safe_print(f"Nessuna nuova risposta dopo {elapsed}s...")
            continue
        try:
            text = messages.nth(count - 1).inner_text(timeout=5000).strip()
        except PlaywrightError:
            continue
        if text and text == last_text:
            stable_reads += 1
        else:
            stable_reads = 0
            last_text = text
            safe_print(f"Risposta in corso: {len(last_text)} caratteri")
        if last_text and stable_reads >= 2:
            return last_text
    safe_print("Timeout risposta.")
    return last_text


def send_telegram_message(text_message):
    token = os.getenv(TELEGRAM_TOKEN_ENV) or os.getenv(TELEGRAM_TOKEN_FALLBACK_ENV)
    receiver_id = os.getenv(TELEGRAM_RECEIVER_ENV)
    if not token or not receiver_id:
        safe_print("Telegram non inviato: variabili .env mancanti.")
        return
    telepot.Bot(token).sendMessage(receiver_id, text_message)
    safe_print("Messaggio Telegram inviato.")


def send_telegram_photo(photo_path, caption=""):
    token = os.getenv(TELEGRAM_TOKEN_ENV) or os.getenv(TELEGRAM_TOKEN_FALLBACK_ENV)
    receiver_id = os.getenv(TELEGRAM_RECEIVER_ENV)
    if not token or not receiver_id:
        safe_print("Foto Telegram non inviata: variabili .env mancanti.")
        return
    with open(photo_path, "rb") as handle:
        telepot.Bot(token).sendPhoto(receiver_id, handle, caption=caption[:1024])
    safe_print("Grafico prezzo inviato su Telegram.")


def analyze_with_chatgpt(context, ticker, image_paths, prompt, debug_screenshot_path=None):
    page = context.new_page()
    try:
        page.goto(CHATGPT_URL, wait_until="domcontentloaded")
        page.bring_to_front()
        attach_images(page, image_paths)
        if debug_screenshot_path:
            page.screenshot(path=str(debug_screenshot_path), full_page=True)
            safe_print(f"Screenshot upload salvato: {debug_screenshot_path}")
        initial_count = send_prompt(page, prompt)
        return wait_for_response(page, initial_count)
    finally:
        try:
            page.close()
        except PlaywrightError:
            pass


def main():
    configure_stdout()
    load_env_file()
    parser = argparse.ArgumentParser(description="Crea grafici tecnici e li invia a ChatGPT per analisi.")
    parser.add_argument("--stocks", default="", help='Ticker separati da virgola, es. "VOD.L,A2A.MI,AVIO.MI"')
    parser.add_argument("--period", default="1y", help='Periodo yfinance, es. "6mo", "1y", "2y"')
    parser.add_argument("--days", type=int, default=70, help="Numero barre da mostrare nei grafici")
    parser.add_argument("--output-dir", default="output/stock_ai", help="Cartella output grafici e risposte")
    parser.add_argument("--cdp", default=DEFAULT_CDP_URL, help="Chrome remote debugging URL")
    parser.add_argument("--charts-only", action="store_true", help="Genera solo i grafici, senza ChatGPT")
    parser.add_argument("--no-telegram", action="store_true", help="Non inviare la risposta Telegram")
    args = parser.parse_args()

    stocks = parse_stock_list(args.stocks)
    output_root = Path(args.output_dir)

    bundles = []
    for ticker in stocks:
        safe_print(f"Genero grafici per {ticker}...")
        bundle = create_chart_bundle(ticker, output_root / ticker.replace("/", "_"), args.period, args.days)
        bundles.append(bundle)
        for path in bundle["files"]:
            safe_print(f"Creato: {path}")

    if args.charts_only:
        return

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        for bundle in bundles:
            ticker = bundle["ticker"]
            prompt = build_prompt(ticker, bundle["snapshot"])
            safe_print(f"Invio grafici a ChatGPT per {ticker}...")
            ticker_dir = output_root / ticker.replace("/", "_")
            debug_screenshot_path = ticker_dir / f"{ticker.replace('/', '_')}_chatgpt_upload.png"
            response = analyze_with_chatgpt(context, ticker, bundle["files"], prompt, debug_screenshot_path)
            response_path = ticker_dir / f"{ticker.replace('/', '_')}_analysis.txt"
            response_path.write_text(response or "", encoding="utf-8")
            safe_print(f"Analisi salvata: {response_path}")
            if response and not args.no_telegram:
                send_telegram_photo(bundle["files"][0], caption=f"{ticker} - grafico prezzo")
                send_telegram_message(response)


if __name__ == "__main__":
    main()
