# TradingWatchAgent

Agente Python per creare e monitorare un portafoglio virtuale, cercare candidati dal MIB30, generare grafici tecnici e produrre proposte di modifica sempre soggette a conferma utente.

## Principi

- I tool locali non richiedono OpenAI API key.
- L'agente OpenAI SDK richiede `OPENAI_API_KEY`.
- Le modifiche al portafoglio non vengono mai applicate automaticamente: l'agente crea proposte pending e l'utente deve confermare un `proposal_id`.
- Le analisi news live possono usare Playwright con Chrome gia loggato, senza API key OpenAI.

## Struttura

```text
agent_portfolio_manager.py      # CLI agente OpenAI SDK
chatgpt_playwright_demo.py      # news/report via ChatGPT nel browser con Playwright
stock_chart_ai_analysis.py      # grafici + analisi ChatGPT via Playwright
finance_charts/                 # indicatori e grafici tecnici
finance_tools/                  # tool portfolio, scanner, news, chart
validTickers/                   # universo titoli MIB30
portfolio.example.json          # esempio watchlist
```

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

Compila `.env` con i valori reali. `OPENAI_API_KEY` serve solo per usare l'agente SDK, non per i tool locali.

## Test tool senza API key

Genera grafici e snapshot tecnico:

```bash
python stock_chart_ai_analysis.py --charts-only --stocks "VOD.L" --days 70
```

Scanner MIB30 tramite agente/tool CLI richiede API key se passa dall'agente:

```bash
python agent_portfolio_manager.py --scan-mib30 --scan-limit 5
```

## Portafoglio virtuale

Inizializza portafoglio:

```bash
python agent_portfolio_manager.py --init-portfolio
```

Oppure capitale diretto:

```bash
python agent_portfolio_manager.py --init-portfolio --capital 10000
```

Se il portafoglio e vuoto, chiedi all'agente di creare una proposta:

```bash
python agent_portfolio_manager.py --build-empty-portfolio --scan-limit 5 --cash-pct 15
```

L'agente chiede il capitale se non passi `--capital`, scannerizza il MIB30 e crea una proposta pending.

## Conferme

Le proposte vengono salvate in `portfolio.json`.

Per ora puoi chiedere all'agente:

```bash
python agent_portfolio_manager.py "Mostra le proposte pending"
python agent_portfolio_manager.py "Conferma la proposta 20260723-203433"
python agent_portfolio_manager.py "Rifiuta la proposta 20260723-203433"
```

## News live via Playwright

Apri Chrome con debug remoto:

```cmd
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%TEMP%\chatgpt-cdp-profile"
```

Poi:

```bash
python agent_portfolio_manager.py --stocks "VOD.L" --live-news
```

In questa modalita il tool news richiama `chatgpt_playwright_demo.py`, quindi usa Playwright e il tuo login ChatGPT nel browser. Non usa `OPENAI_API_KEY`.

## Note

Questo progetto e per simulazione, studio e monitoraggio. Non e consulenza finanziaria.
