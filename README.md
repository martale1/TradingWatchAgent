# TradingWatchAgent

Agente Python per creare e monitorare un portafoglio virtuale, cercare candidati dal MIB30, generare grafici tecnici e produrre proposte di modifica sempre soggette a conferma utente.

## Principi

- I tool locali non richiedono OpenAI API key.
- L'agente OpenAI SDK richiede `OPENAI_API_KEY`.
- In modalita standard le modifiche al portafoglio non vengono mai applicate automaticamente: l'agente crea proposte pending e l'utente deve confermare un `proposal_id`.
- In modalita autonoma virtuale l'agente puo applicare da solo operazioni simulate sul `portfolio.json`; l'utente viene notificato via Telegram.
- Le condizioni non ancora verificate vengono salvate in `portfolio.json` come `monitored_conditions`, cosi possono essere rivalutate nei controlli successivi.
- Le analisi news live possono usare Playwright con Chrome gia loggato, senza API key OpenAI.
- I candidati MIB30 vengono prima filtrati con score tecnico locale; l'agente decide poi se confermare i migliori con analisi visuale dei grafici via Playwright/ChatGPT prima di proporre operazioni.
- In modalita interattiva l'agente mantiene il contesto recente della sessione, quindi capisce riferimenti come "questi 5 titoli" o "i candidati precedenti".

## Struttura

```text
agent_portfolio_manager.py      # CLI agente OpenAI SDK
chatgpt_playwright_demo.py      # news/report via ChatGPT nel browser con Playwright
stock_chart_ai_analysis.py      # grafici + analisi ChatGPT via Playwright
backend/main.py                 # API FastAPI per dashboard React
frontend/                       # frontend React/Vite
finance_charts/                 # indicatori e grafici tecnici
finance_tools/                  # tool portfolio, scanner, news, chart
validTickers/                   # universo titoli MIB30
portfolio.example.json          # esempio watchlist
```

Universi ticker:

```text
validTickers/validtickers_IT_MIB30_with_sector.xlsx  # azioni monitorate dallo scanner MIB
validTickers/validtickers_CRYPTO.xlsx                # crypto separate: BTC/ETH/SOL/ADA
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
OPENAI_AGENT_MAX_TURNS=60
MONITOR_INTERVAL_MINUTES=30
MAX_AUTO_TRADE_PCT=25
```

`OPENAI_AGENT_MAX_TURNS` controlla quanti passaggi tool/LLM puo fare una run. Screening MIB30 con news, grafici, condizioni e proposte richiede piu passaggi rispetto a una semplice analisi.
`MONITOR_INTERVAL_MINUTES` e l'intervallo default del monitor periodico.
`MAX_AUTO_TRADE_PCT` limita quanto cash puo usare una nuova operazione autonoma virtuale.

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

## Performance portafoglio

Il sistema calcola rendimento corrente delle posizioni virtuali usando prezzi Yahoo Finance:

```text
- valore attuale portafoglio
- P/L totale EUR e %
- P/L per posizione EUR e %
- cash, investito, esposizione
- best/worst position
- alert su soglie di rendimento
```

Nel ciclo periodico l'agente usa `get_portfolio_performance`; se trova alert rilevanti puo inviare un Telegram performance. Anche il riepilogo monitoraggio Telegram include ora valore portafoglio e P/L totale.

Soglie alert iniziali:

```text
- posizione >= +5%: alert positivo
- posizione <= -3%: alert rischio
- portafoglio >= +2%: alert positivo
- portafoglio <= -2%: alert rischio
```

## Web app React + FastAPI

La dashboard React e pensata come frontend principale quando il prodotto diventa piu stabile. Usa un backend FastAPI separato:

```text
backend/main.py      # API portfolio, performance, monitoraggio, chat agente, Telegram
frontend/            # UI React/Vite
```

Avvia backend:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Avvia frontend:

```bash
cd frontend
npm install
npm run dev
```

Apri:

```text
http://127.0.0.1:5174
```

API docs:

```text
http://127.0.0.1:8000/docs
```

La web app mostra:

```text
- stato agente: ultima analisi avviata/completata e prossimo giro atteso
- capitale, valore portafoglio, cash e P/L con colori positivi/negativi
- posizioni aperte con P/L per titolo
- watchlist manuale per titoli da analizzare anche se non filtrati dallo scanner
- condizioni monitorate con prezzo attuale, trigger, supporto e distanza dal trigger
- grafici apribili con viste prezzo, volumi, RSI/Stocastico/Williams, MACD e ADX
- chat stile ChatGPT per parlare con l'agente
- azioni recenti e controlli per run autonoma singola e notifiche Telegram
```

Lo stato delle run agente viene salvato in `agent_run_state.json`, escluso da Git. Viene aggiornato quando parte `--daemon-monitor`, `--autonomous-monitor` o una run singola dal backend React.

### Watchlist manuale

La watchlist e una lista di ticker scelti dall'utente, separata dai candidati trovati dallo scanner MIB30. Serve per seguire titoli che vuoi analizzare piu a fondo anche se l'algoritmo non li seleziona.

Dalla dashboard React apri il tab `Watchlist`, inserisci ticker, priorita, motivo e, se vuoi, una `condizione ingresso` esplicita da monitorare. Se la condizione e presente, l'agente la usa come trigger principale nei monitor periodici; se manca, durante l'analisi puo proporre o salvare una condizione concreta con livello prezzo, conferma volumi e supporto di invalidazione.

Puoi gestirla anche dalla chat:

```text
aggiungi VOD.L alla watchlist con priorita high perche voglio seguirla
aggiungi VOD.L alla watchlist con condizione ingresso chiusura sopra 121 con volumi in recupero
mostra watchlist
rimuovi VOD.L dalla watchlist
```

## Scheduler Windows ogni 30 minuti

Per far girare l'agente autonomo ogni 30 minuti su Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_windows_monitor_task.ps1
```

La task Windows `TradingWatchAgentMonitor` esegue:

```text
scripts\run_autonomous_monitor_once.bat
```

Ogni giro lancia un ciclo singolo:

```text
agent_portfolio_manager.py --autonomous-monitor --once --monitor-interval-minutes 30 --deep-confirm-limit 2
```

Il job schedulato gira in modalita autonoma virtuale: puo comprare, vendere, ridurre o modificare posizioni nel solo portafoglio virtuale, registrando le azioni nello storico e notificando via Telegram secondo la policy configurata. L'agente puo usare anche conferme visuali Playwright/ChatGPT fino al limite indicato da `--deep-confirm-limit`, se Chrome con debug remoto e disponibile; se non lo e, continua con dati tecnici e cache disponibili.

Log:

```text
logs/scheduled-monitor.log
logs/scheduled-monitor.err.log
```

Lo script usa anche un lock locale (`logs/monitor.lock`) per evitare run sovrapposte: se un ciclo dura piu di 30 minuti, il giro successivo viene saltato e scritto nel log.

La dashboard React mostra `Ultima analisi titoli`, `Ultima run agente` e `Prossimo scheduled expected` leggendo `agent_run_state.json`.

Le notifiche performance automatiche sono deduplicate: lo stesso alert non viene reinviato a ogni ciclo. Per default un alert identico puo essere rimandato solo dopo 180 minuti; l'invio manuale dalla dashboard resta sempre disponibile.

## Chat Telegram con agente

Oltre alle notifiche Telegram, puoi usare lo stesso bot come chat remota per interrogare l'agente.

Avvio da terminale:

```powershell
C:\Users\theoi\anaconda3\envs\openaiAgent\python.exe telegram_agent_bot.py
```

Oppure con launcher Windows:

```powershell
scripts\run_telegram_agent_bot.bat
```

Il bridge:

```text
- ascolta solo TELEGRAM_RECEIVER_ID configurato in .env
- usa TELEGRAM_BOT_TOKEN o TELEGRAM_BOT_TOKEN_CH1
- salva offset e contesto breve in telegram_agent_state.json
- passa le richieste all'agente OpenAI SDK
- risponde su Telegram spezzando i messaggi lunghi e rendendo grassetti/liste in formato leggibile
- sopprime i riepiloghi Telegram automatici generati dal runner, cosi una domanda Telegram produce una sola risposta mirata
```

Esempi da scrivere in Telegram:

```text
aiuto
quali segnali attendi per uscire da CPR.MI?
mostra performance
mostra stato operativo
quali titoli stai monitorando?
aggiungi VOD.L alla watchlist con priorita high
mandami il grafico di CPR.MI
analizza AMP.MI
```

Se chiedi un grafico, il bridge invia direttamente le immagini PNG generate dal tool tecnico: prezzo/trend, momentum e ADX.

Log:

```text
logs/telegram-agent.log
logs/telegram-agent.err.log
```

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

L'agente chiude le risposte operative con una sezione `Opzioni successive`, scegliendo comandi coerenti con lo stato corrente. Esempio:

```text
Opzioni successive:
1. rivaluta le condizioni monitorate
2. mostra stato operativo del portafoglio
3. scannerizza il MIB30 e cerca nuovi candidati
4. analizza HER.MI con grafico e news live
```

Anche al primo avvio di `--interactive` viene mostrata una lista di opzioni operative costruita dal contenuto di `portfolio.json`.
Puoi scrivere il comando completo oppure solo il numero dell'opzione, per esempio `1`. Dopo ogni risposta, i numeri si aggiornano usando le ultime `Opzioni successive` mostrate dall'agente.

Per una verifica veloce senza chiamare il modello:

```text
Tu> titoli monitorati
```

La memoria e limitata alla sessione aperta: se chiudi il processo, riparti da una nuova conversazione. Il portafoglio e le proposte pending restano invece salvati in `portfolio.json`.

Quando un titolo e interessante ma non ancora acquistabile, l'agente deve salvarlo come condizione monitorata. Esempio: `HER.MI buy solo sopra 3,966 con volumi`. Nei turni successivi puoi chiedere:

```text
Tu> mostra stato operativo del portafoglio
Tu> mostra condizioni da monitorare
Tu> rivaluta le condizioni monitorate
```

La vista operativa include:

```text
- titoli in portafoglio
- proposte pending di acquisto o allocazione
- condizioni monitorate con stato e trigger
- watchlist
```

Durante ogni monitoraggio l'agente deve valutare anche i titoli gia in portafoglio. Se emergono segnali di uscita, riduzione, protezione o presa profitto, crea solo una proposta pending e aspetta conferma utente.

Dopo uno screening completo del MIB30 con analisi dettagliata grafico/news e salvataggio o aggiornamento dei titoli monitorati, il runner invia automaticamente un riepilogo Telegram con condizioni waiting/met/invalidated, proposte pending e stato del portafoglio. L'invio e deterministico: parte quando cambiano condizioni monitorate, proposte o stato operativo durante screening/rivalutazione/proposta.

## Monitor periodico

Il monitor periodico esegue cicli ricorrenti con questa priorita:

```text
1. controlla titoli gia in portafoglio e propone eventuali azioni pending
2. rivaluta condizioni monitorate e le aggiorna come waiting/met/invalidated/archived
3. scannerizza il MIB30 per trovare nuovi candidati interessanti
4. salva nuove condizioni o crea nuove proposte pending se serve
5. invia riepilogo Telegram quando lo stato operativo cambia
```

Per provarlo una sola volta da PyCharm o CLI:

```bash
python agent_portfolio_manager.py --daemon-monitor --once --scan-limit 5
```

Per lasciarlo girare ogni 30 minuti:

```bash
python agent_portfolio_manager.py --daemon-monitor --monitor-interval-minutes 30 --scan-limit 5
```

Per test veloci puoi limitare l'universo:

```bash
python agent_portfolio_manager.py --daemon-monitor --once --scan-limit 3 --universe-limit 10
```

Le news live via Playwright nel monitor periodico sono disattivate per default. Puoi abilitarle solo se Chrome e aperto con debug remoto:

```bash
python agent_portfolio_manager.py --daemon-monitor --monitor-interval-minutes 30 --periodic-live-news
```

In modalita periodica standard non viene mai applicata una modifica al portafoglio senza conferma esplicita del `proposal_id`.

### Modalita autonoma virtuale

Se vuoi che l'agente decida e applichi autonomamente operazioni sul solo portafoglio virtuale, senza conferma utente e con sola notifica Telegram, usa il flag esplicito:

```bash
python agent_portfolio_manager.py --autonomous-monitor --scan-limit 5 --max-auto-trade-pct 25
```

`--autonomous-monitor` equivale a `--daemon-monitor --auto-apply-virtual` e usa l'intervallo default `MONITOR_INTERVAL_MINUTES=30`.

Puoi comunque sovrascrivere l'intervallo:

```bash
python agent_portfolio_manager.py --autonomous-monitor --monitor-interval-minutes 15 --scan-limit 5 --max-auto-trade-pct 25
```

In questa modalita l'agente puo:

```text
- analizzare posizioni aperte e proporre/attuare azioni simulate
- creare una proposta pending motivata
- applicare autonomamente quella proposta sul portfolio.json virtuale
- aggiornare condizioni monitorate
- inviare riepilogo Telegram quando cambia lo stato
```

Limiti:

```text
- nessun ordine reale su broker
- nessuna operazione fuori dal portfolio.json virtuale
- ogni nuova operazione autonoma deve rispettare --max-auto-trade-pct
- se il segnale e debole o contraddittorio deve monitorare, non comprare
- l'utente non conferma prima: viene notificato via Telegram dopo le decisioni/applicazioni virtuali
```

Puoi inviare manualmente il riepilogo:

```text
Tu> invia riepilogo telegram
```

Se l'utente chiede esplicitamente di procedere con un acquisto anche quando il segnale non e confermato, l'agente deve assecondarlo creando una proposta pending, evidenziando i rischi e indicando che si tratta di una forzatura consapevole. La proposta richiede comunque conferma tramite `proposal_id`.
In modalita interattiva i comandi espliciti di acquisto vengono intercettati localmente per essere affidabili:

```text
Tu> compriamo 10000 euro di HER.MI
Tu> acquista 2500 euro su AMP.MI
```

Questi comandi creano una proposta pending, non aprono direttamente la posizione.

Puoi aggiornare il capitale virtuale con una richiesta esplicita:

```text
Tu> aggiorna il capitale a 20000 euro
```

L'aggiornamento modifica `initial_capital` e adegua la liquidita del delta, senza cancellare posizioni, proposte o condizioni monitorate.

Durante la rivalutazione l'agente deve aggiornare ogni condizione:

```text
waiting      # condizione ancora valida ma non scattata
met          # condizione scattata; puo generare proposta pending
invalidated  # contesto tecnico/news peggiorato, condizione non piu utile
archived     # condizione chiusa e rimossa dal monitoraggio operativo
```

Se una condizione diventa `met` e grafico/news confermano, l'agente crea una proposta pending con `create_buy_proposal`. In modalita interattiva aspetta conferma; in modalita `--autonomous-monitor` puo applicare automaticamente l'operazione virtuale e notificare via Telegram.

Le news sono parte del filtro decisionale: prima di comprare, vendere, ridurre o modificare una posizione virtuale l'agente deve usare le news disponibili, oppure dichiarare che non sono disponibili e abbassare la confidenza della decisione. News negative, downgrade, guidance peggiorativa o eventi societari rilevanti possono invalidare un trigger tecnico anche se il prezzo lo ha raggiunto.

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

L'agente e configurato con `parallel_tool_calls=False`: analizza i candidati in sequenza e aspetta il risultato di un tool prima di lanciare il successivo. La regola operativa e "un ticker alla volta": completa grafico, eventuali news, sintesi e giudizio provvisorio di un candidato prima di passare al candidato successivo. In piu, i tool che usano Playwright vengono messi in coda: una sola sessione Chrome/ChatGPT alla volta. Questo evita blocchi quando l'agente decide di approfondire piu candidati.

## Note

Questo progetto e per simulazione, studio e monitoraggio. Non e consulenza finanziaria.
