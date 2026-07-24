import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finance_tools.common import load_env_file  # noqa: E402
from finance_tools.agent_run_state import agent_schedule_status  # noqa: E402
from finance_tools.exit_view import build_exit_conditions  # noqa: E402
from finance_tools.monitoring_view import enrich_monitored_conditions  # noqa: E402
from finance_tools.performance_tool import calculate_portfolio_performance  # noqa: E402
from finance_tools.portfolio_store import load_portfolio, portfolio_status_summary  # noqa: E402
from finance_tools.telegram_tool import send_monitoring_summary, send_performance_summary  # noqa: E402
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


def run_agent_command(args, timeout=900):
    cmd = [sys.executable, str(ROOT / "agent_portfolio_manager.py"), *args]
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    output = result.stdout.strip() if result.stdout else result.stderr.strip()
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail={"exit_code": result.returncode, "output": output})
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
    monitored = enrich_monitored_conditions(status.get("monitored_conditions", []))
    exits = build_exit_conditions(performance, portfolio)
    closed = list(reversed((portfolio or {}).get("closed_proposals", [])))[:20]
    return {
        "portfolio": status,
        "performance": performance,
        "monitored": monitored,
        "exit_conditions": exits,
        "agent_run_state": agent_schedule_status(),
        "recent_actions": closed,
    }


@app.get("/api/chart/{ticker}")
def chart_data(ticker: str, period: str = "6mo", interval: str = "1d"):
    symbol = ticker.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Ticker mancante")
    try:
        history = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore download dati {symbol}: {exc}") from exc
    if history.empty:
        raise HTTPException(status_code=404, detail=f"Nessun dato prezzo disponibile per {symbol}")

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
            }
        )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Nessun dato close disponibile per {symbol}")

    return {"ticker": symbol, "period": period, "interval": interval, "prices": rows}


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


@app.post("/api/telegram/monitoring")
def telegram_monitoring():
    return send_monitoring_summary(extra_note="Invio richiesto da web app React.")


@app.post("/api/telegram/performance")
def telegram_performance():
    return send_performance_summary(extra_note="Invio richiesto da web app React.")
