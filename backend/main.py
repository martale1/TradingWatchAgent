import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finance_tools.common import load_env_file  # noqa: E402
from finance_tools.agent_run_state import agent_schedule_status  # noqa: E402
from finance_tools.commodity_scanner import load_commodity_tickers, scan_commodity_candidates  # noqa: E402
from finance_tools.exit_view import build_exit_conditions  # noqa: E402
from finance_tools.mib30_scanner import load_mib30_tickers, scan_mib30_candidates  # noqa: E402
from finance_tools.monitoring_view import enrich_monitored_conditions  # noqa: E402
from finance_tools.performance_tool import build_performance_history_view, calculate_portfolio_performance  # noqa: E402
from finance_tools.portfolio_store import (  # noqa: E402
    add_watchlist_item,
    list_watchlist,
    load_portfolio,
    portfolio_status_summary,
    remove_watchlist_item,
)
from finance_tools.telegram_tool import (  # noqa: E402
    load_telegram_settings,
    save_telegram_settings,
    send_monitoring_summary,
    send_performance_summary,
)
from finance_charts.technical_charts import add_indicators  # noqa: E402
import yfinance as yf  # noqa: E402


load_env_file()

app = FastAPI(title="TradingWatchAgent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:5174",
        "http://localhost:5174",
        "http://127.0.0.1:4174",
        "http://localhost:4174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = []


class RunMonitorRequest(BaseModel):
    scan_limit: int = 5
    max_auto_trade_pct: float = 25.0


class PlaywrightMonitorRequest(BaseModel):
    limit: int = 5
    deep_limit: int = 2
    universe_limit: int = 0
    telegram: bool = True


class WatchlistRequest(BaseModel):
    ticker: str
    name: str = ""
    market: str = ""
    reason: str = ""
    entry_condition: str = ""
    priority: str = "normal"
    tags: list[str] = []


class TelegramSettingsRequest(BaseModel):
    monitoring_mode: str = "always"
    send_performance_alerts: bool = True
    max_monitoring_items: int = 5


class CommodityScanRequest(BaseModel):
    limit: int = 8
    universe_limit: int = 0


class FtseMibScanRequest(BaseModel):
    limit: int = 8
    universe_limit: int = 0


def tail_text(path: Path, max_lines: int = 300):
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-max_lines:])


def timestamped(line: str):
    return f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {line}"


def append_web_agent_log(line: str):
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    with (log_dir / "web-agent.log").open("a", encoding="utf-8") as handle:
        handle.write(timestamped(line.rstrip()) + "\n")


def run_agent_command(args, timeout=900, script="agent_portfolio_manager.py"):
    cmd = [sys.executable, str(ROOT / script), *args]
    append_web_agent_log(f"===== START {' '.join(cmd)} =====")
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output_lines = []
    try:
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.rstrip()
            output_lines.append(clean)
            append_web_agent_log(clean)
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        append_web_agent_log(f"===== TIMEOUT dopo {timeout}s =====")
        raise HTTPException(status_code=504, detail=f"Timeout agente dopo {timeout}s") from exc
    output = "\n".join(output_lines).strip()
    append_web_agent_log(f"===== END exit={return_code} =====")
    if return_code != 0:
        raise HTTPException(status_code=500, detail={"exit_code": return_code, "output": output})
    return output


def extract_agent_answer(output):
    marker = "[agent] Risposta finale agente ricevuta"
    if marker in output:
        return output.split(marker, 1)[1].strip()
    interrupted = "Run interrotta prima della risposta finale"
    if interrupted in output:
        return output[output.find(interrupted) :].strip()
    return output


def build_context(history, message):
    lines = [
        "Questa richiesta arriva dalla web app React di TradingWatchAgent.",
        "Usa il contesto recente per capire riferimenti a portafoglio, condizioni, proposte o titoli.",
        "",
        "Contesto recente:",
    ]
    for item in history[-8:]:
        role = "Utente" if item.get("role") == "user" else "Agente"
        lines.append(f"{role}: {item.get('content', '')}")
    lines.extend(["", "Nuova richiesta utente:", message])
    return "\n".join(lines)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard")
def dashboard():
    portfolio = load_portfolio()
    status = portfolio_status_summary()
    performance = calculate_portfolio_performance()
    performance_history = build_performance_history_view()
    monitored = enrich_monitored_conditions(status.get("monitored_conditions", []))
    exits = build_exit_conditions(performance, portfolio)
    closed = list(reversed((portfolio or {}).get("closed_proposals", [])))[:20]
    return {
        "portfolio": status,
        "performance": performance,
        "performance_history": performance_history,
        "monitored": monitored,
        "exit_conditions": exits,
        "agent_run_state": agent_schedule_status(),
        "recent_actions": closed,
        "ftse_mib": load_mib30_tickers(),
        "commodities": load_commodity_tickers(),
    }


@app.get("/api/ftse-mib")
def ftse_mib():
    return {"status": "ok", "tickers": load_mib30_tickers()}


@app.post("/api/ftse-mib/scan")
def ftse_mib_scan(request: FtseMibScanRequest):
    try:
        return scan_mib30_candidates(
            limit=max(1, min(int(request.limit), 30)),
            universe_limit=int(request.universe_limit) or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore scanner FTSE MIB: {exc}") from exc


@app.get("/api/commodities")
def commodities():
    return {"status": "ok", "commodities": load_commodity_tickers()}


@app.post("/api/commodities/scan")
def commodities_scan(request: CommodityScanRequest):
    try:
        return scan_commodity_candidates(
            limit=max(1, min(int(request.limit), 30)),
            universe_limit=int(request.universe_limit) or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore scanner materie prime: {exc}") from exc


@app.get("/api/run-logs")
def run_logs(lines: int = 300):
    max_lines = max(20, min(int(lines or 300), 2000))
    log_dir = ROOT / "logs"
    scheduled_log = log_dir / "scheduled-monitor.log"
    scheduled_err = log_dir / "scheduled-monitor.err.log"
    web_agent_log = log_dir / "web-agent.log"
    agent_state = agent_schedule_status()
    return {
        "status": "ok",
        "lines": max_lines,
        "agent_run_state": agent_state,
        "scheduled_log": tail_text(scheduled_log, max_lines),
        "scheduled_err": tail_text(scheduled_err, max_lines),
        "web_agent_log": tail_text(web_agent_log, max_lines),
        "scheduled_log_updated_at": scheduled_log.stat().st_mtime if scheduled_log.exists() else None,
        "scheduled_err_updated_at": scheduled_err.stat().st_mtime if scheduled_err.exists() else None,
        "web_agent_log_updated_at": web_agent_log.stat().st_mtime if web_agent_log.exists() else None,
    }


@app.get("/api/chart/{ticker}")
def chart_data(ticker: str, period: str = "6mo", interval: str = "1d"):
    symbol = ticker.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    warmup_periods = {
        "1mo": ("1y", 23),
        "3mo": ("1y", 66),
        "6mo": ("1y", 132),
        "1y": ("2y", 252),
    }
    download_period, visible_rows = warmup_periods.get(period, (period, None))
    try:
        history = yf.Ticker(symbol).history(period=download_period, interval=interval, auto_adjust=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore download dati {symbol}: {exc}") from exc
    if history.empty:
        raise HTTPException(status_code=404, detail=f"Nessun dato prezzo disponibile per {symbol}")

    try:
        history = add_indicators(history)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore calcolo indicatori {symbol}: {exc}") from exc

    if visible_rows:
        history = history.tail(visible_rows)

    def clean_number(value, digits=4):
        if value is None or value != value:
            return None
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return None

    history = history.reset_index()
    rows = []
    for _, row in history.iterrows():
        close = row.get("Close")
        if close is None or close != close:
            continue
        date_value = row.get("Date") if "Date" in row else row.get("Datetime")
        rows.append(
            {
                "date": date_value.strftime("%Y-%m-%d") if hasattr(date_value, "strftime") else str(date_value),
                "open": round(float(row.get("Open", close)), 4),
                "high": round(float(row.get("High", close)), 4),
                "low": round(float(row.get("Low", close)), 4),
                "close": round(float(close), 4),
                "volume": int(row.get("Volume", 0) or 0),
                "vol_ma5": clean_number(row.get("Vol_MA5"), 0),
                "vol_ma10": clean_number(row.get("Vol_MA10"), 0),
                "rsi": clean_number(row.get("RSI")),
                "stoch_k": clean_number(row.get("Stoch_K")),
                "stoch_d": clean_number(row.get("Stoch_D")),
                "williams_r": clean_number(row.get("Williams_R")),
                "macd": clean_number(row.get("MACD")),
                "macd_signal": clean_number(row.get("MACD_Signal")),
                "macd_hist": clean_number(row.get("MACD_Hist")),
                "adx": clean_number(row.get("ADX")),
                "plus_di": clean_number(row.get("PLUS_DI")),
                "minus_di": clean_number(row.get("MINUS_DI")),
            }
        )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato close disponibile per {symbol}")

    return {"ticker": symbol, "period": period, "data_period": download_period, "interval": interval, "prices": rows}


@app.get("/api/watchlist")
def get_watchlist():
    return {"status": "ok", "watchlist": list_watchlist()}


@app.post("/api/watchlist")
def add_watchlist(request: WatchlistRequest):
    if not request.ticker.strip():
        raise HTTPException(status_code=400, detail="Ticker mancante")
    try:
        item = add_watchlist_item(
            ticker=request.ticker,
            name=request.name,
            market=request.market,
            reason=request.reason,
            entry_condition=request.entry_condition,
            priority=request.priority,
            tags=request.tags,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "item": item}


@app.delete("/api/watchlist/{ticker}")
def delete_watchlist(ticker: str):
    try:
        return remove_watchlist_item(ticker)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/agent/chat")
def chat(request: ChatRequest):
    output = run_agent_command([build_context(request.history, request.message)])
    return {"answer": extract_agent_answer(output), "raw": output}


@app.post("/api/agent/run-once")
def run_once(request: RunMonitorRequest):
    output = run_agent_command(
        [
            "--autonomous-monitor",
            "--once",
            "--scan-limit",
            str(int(request.scan_limit)),
            "--max-auto-trade-pct",
            str(float(request.max_auto_trade_pct)),
        ]
    )
    return {"output": output}


@app.post("/api/playwright-monitor/run")
def run_playwright_monitor(request: PlaywrightMonitorRequest):
    args = [
        "--limit",
        str(max(1, min(int(request.limit), 30))),
        "--deep-limit",
        str(max(0, min(int(request.deep_limit), 10))),
        "--universe-limit",
        str(max(0, int(request.universe_limit))),
    ]
    if request.telegram:
        args.append("--telegram")
    output = run_agent_command(args, timeout=1800, script="playwright_monitor.py")
    return {"output": output}


@app.post("/api/agent/analyze-watchlist-entry-conditions")
def analyze_watchlist_entry_conditions():
    prompt = (
        "Analizza tutti i titoli della watchlist manuale usando list_manual_watchlist. "
        "Per ogni titolo lavora in sequenza, uno alla volta: "
        "1) usa analyze_stock_chart; "
        "2) usa confirm_candidate_chart_with_playwright(no_telegram=True) per analisi visuale AI via Playwright; "
        "3) usa news disponibili in cache senza live se non richiesto esplicitamente; "
        "4) definisci una entry_condition concreta scegliendo uno di due scenari: "
        "SCENARIO BREAKOUT = chiusura sopra resistenza/trigger con volumi in recupero o sopra media, stop sotto supporto/livello rotto; "
        "SCENARIO PULLBACK_SUPPORTO = ingresso vicino al supporto solo se il supporto tiene e compare rimbalzo/reazione positiva, "
        "con stop stretto sotto supporto e target verso resistenza/trigger. "
        "Non considerare il semplice arrivo vicino al supporto come buy automatico: serve evidenza di tenuta/rimbalzo e news non negative. "
        "5) aggiorna la watchlist con add_ticker_to_watchlist mantenendo motivo, priorita e tag esistenti quando disponibili. "
        "Non creare proposte di acquisto in questa azione: imposta solo condizioni ingresso per la watchlist. "
        "Concludi con una tabella compatta ticker, prezzo, condizione ingresso impostata, supporto/stop e motivazione."
    )
    output = run_agent_command([prompt], timeout=1800)
    return {"output": output, "answer": extract_agent_answer(output)}


@app.post("/api/telegram/monitoring")
def telegram_monitoring():
    return send_monitoring_summary(extra_note="Invio richiesto da web app React.")


@app.post("/api/telegram/performance")
def telegram_performance():
    return send_performance_summary(extra_note="Invio richiesto da web app React.", force=True)


@app.get("/api/telegram/settings")
def telegram_settings():
    return {"status": "ok", "settings": load_telegram_settings()}


@app.post("/api/telegram/settings")
def update_telegram_settings(request: TelegramSettingsRequest):
    try:
        settings = save_telegram_settings(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "settings": settings}
