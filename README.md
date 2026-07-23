# TradingWatchAgent

Agente Python per creare e monitorare un portafoglio virtuale, cercare candidati dal MIB30, generare grafici tecnici e produrre proposte di modifica sempre soggette a conferma utente.

## Principi

- I tool locali non richiedono OpenAI API key.
- L'agente OpenAI SDK richiede `OPENAI_API_KEY`.
- Le modifiche al portafoglio non vengono mai applicate automaticamente: l'agente crea proposte pending e l'utente deve confermare un `proposal_id`.
- Le analisi news live possono usare Playwright con Chrome gia loggato, senza API key OpenAI.
- I candidati MIB30 vengono prima filtrati con score tecnico locale; l'agente decide poi se confermare i migliori con analisi visuale dei grafici via Playwright/ChatGPT prima di proporre operazioni.
- In modalita interattiva l'agente mantiene il contesto recente della sessione, quindi capisce riferimenti come "questi 5 titoli" o "i candidati precedenti".

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

Il modello dell'agente si imposta con `OPENAI_AGENT_MODEL` nel file `.env`. Il default consigliato e:

```env
OPENAI_AGENT_MODEL=gpt-5.6-luna
```

Da PyCharm o CLI puoi comunque sovrascriverlo con `--model`, ad esempio:

```bash
python agent_portfolio_manager.py --interactive --model gpt-5.6-terra
```

## Test tool senza API key

Genera grafici e snapshot tecnico:

```bash
python stock_chart_ai_analysis.py --charts-only --stocks "VOD.L" --days 70
```

Scanner MIB30 tramite agente/tool CLI richiede API key se passa dall'agente:

```bash
python agent_portfolio_manager.py --scan-mib30 --scan-limit 5
```

Scanner MIB30. Per default l'agente puo decidere autonomamente se approfondire i migliori candidati con Playwright/ChatGPT:

```bash
python agent_portfolio_manager.py --scan-mib30 --scan-limit 5
```

Puoi forzare la conferma approfondita dei migliori candidati tramite Playwright/ChatGPT:

```bash
python agent_portfolio_manager.py --scan-mib30 --scan-limit 5 --deep-chart-confirmation --deep-confirm-limit 3
```

In questo flusso lo scanner locale scarica i dati da Yahoo Finance, calcola indicatori e seleziona i candidati senza generare PNG. Se l'agente decide di approfondire, o se lo forzi con `--deep-chart-confirmation`, chiama `confirm_candidate_chart_with_playwright`: solo in quel momento vengono creati i grafici e caricati in ChatGPT via Playwright per ottenere una conferma visuale.

Per disattivare la scelta autonoma:

```bash
python agent_portfolio_manager.py --scan-mib30 --scan-limit 5 --no-auto-deep-confirmation
```

## Portafoglio virtuale

## Modalita interattiva

Da PyCharm puoi lanciare:

```bash
python agent_portfolio_manager.py --interactive
```

In questa modalita puoi continuare la conversazione usando riferimenti al turno precedente. Esempio:

```text
Tu> scannerizza il MIB30 e proponi 5 candidati per 20000 euro
Tu> cerca le news per questi 5 titoli
Tu> conferma i migliori 3 con analisi grafica Playwright
```

La memoria e limitata alla sessione aperta: se chiudi il processo, riparti da una nuova conversazione. Il portafoglio e le proposte pending restano invece salvati in `portfolio.json`.

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

Quando chiedi una proposta di portafoglio, l'agente puo decidere autonomamente di approfondire i migliori candidati prima di proporre l'allocazione. Puoi anche forzarlo:

```bash
python agent_portfolio_manager.py --build-empty-portfolio --capital 20000 --scan-limit 5 --cash-pct 15 --deep-chart-confirmation --deep-confirm-limit 3
```

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

L'agente e configurato con `parallel_tool_calls=False`: analizza i candidati in sequenza e aspetta il risultato di un tool prima di lanciare il successivo. In piu, i tool che usano Playwright vengono messi in coda: una sola sessione Chrome/ChatGPT alla volta. Questo evita blocchi quando l'agente decide di approfondire piu candidati.

## Note

Questo progetto e per simulazione, studio e monitoraggio. Non e consulenza finanziaria.
