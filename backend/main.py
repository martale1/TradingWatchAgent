import json
import math
import os
import subprocess
import sys
import threading
import time
import uuid
from queue import Empty, Queue
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from finance_tools.common import load_env_file  # noqa: E402
from finance_tools.autonomy_settings import load_autonomy_settings, save_autonomy_settings  # noqa: E402
from finance_tools.agent_run_state import agent_schedule_status  # noqa: E402
from finance_tools.commodity_scanner import load_commodity_tickers, scan_commodity_candidates  # noqa: E402
from finance_tools.etf_scanner import load_etf_tickers, scan_etf_candidates  # noqa: E402
from finance_tools.exit_view import build_exit_conditions  # noqa: E402
from finance_tools.market_universe_store import (  # noqa: E402
    add_market_instrument,
    import_market_universe_from_excel,
    list_market_universe,
    remove_market_instrument,
    update_market_instrument,
)
from finance_tools.mib30_scanner import load_mib30_tickers, scan_mib30_candidates  # noqa: E402
from finance_tools.monitoring_view import enrich_monitored_conditions  # noqa: E402
from finance_tools.performance_tool import build_performance_history_view, calculate_portfolio_performance  # noqa: E402
from finance_tools.portfolio_deep_analysis import run_deep_portfolio_analysis  # noqa: E402
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
SDK_MODEL = "gpt-5-mini"

app = FastAPI(title="Autonomous Trading Agent API")
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


SCENARIO_RANK = {
    "BUY_CANDIDATE": 50,
    "TRIGGER_MET": 45,
    "CONFIRMED": 40,
    "CONFIRMING": 35,
    "NEAR_TRIGGER": 25,
    "WAIT": 10,
}

STATUS_RANK = {
    "met": 30,
    "waiting": 20,
    "invalidated": 5,
}

DEEP_ANALYSIS_JOBS = {}
DEEP_ANALYSIS_JOBS_LOCK = threading.Lock()
LAST_DEEP_ANALYSIS_PATH = ROOT / "output" / "stock_ai" / "last_deep_portfolio_analysis.json"


def safe_number(value):
    try:
        if value is None:
            return None
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def compact_deep_analysis_item(item):
    decision = item.get("decision") or {}
    performance = item.get("performance") or {}
    position = item.get("position") or {}
    proposal = item.get("proposal") or {}
    technical = item.get("technical") or {}

    return {
        "ticker": item.get("ticker"),
        "decision": {
            "action": decision.get("action"),
            "percent": safe_number(decision.get("percent")),
            "priority": decision.get("priority"),
            "reason": decision.get("reason"),
            "levels": decision.get("levels") or {},
        },
        "position": {
            "invested_amount": safe_number(
                performance.get("invested_amount")
                or position.get("allocated_amount")
                or position.get("invested_amount")
            ),
            "entry_price": safe_number(performance.get("entry_price") or position.get("entry_price")),
            "quantity": safe_number(performance.get("virtual_quantity") or position.get("virtual_quantity")),
            "opened_at": position.get("opened_at") or position.get("created_at"),
        },
        "performance": {
            "current_price": safe_number(performance.get("current_price")),
            "market_value": safe_number(performance.get("market_value")),
            "pnl": safe_number(performance.get("pnl")),
            "pnl_pct": safe_number(performance.get("pnl_pct")),
            "daily_change_pct": safe_number(performance.get("daily_change_pct")),
            "price_change_pct": safe_number(performance.get("price_change_pct")),
        },
        "technical": {
            "close": safe_number(technical.get("close")),
            "rsi": safe_number(technical.get("rsi")),
            "adx": safe_number(technical.get("adx")),
            "support": safe_number(technical.get("support")),
            "resistance": safe_number(technical.get("resistance")),
            "volume_ratio_ma10": safe_number(technical.get("volume_ratio_ma10")),
        },
        "proposal": {
            "id": proposal.get("id"),
            "action": proposal.get("action"),
            "status": proposal.get("status"),
        } if proposal else None,
        "applied": item.get("applied") or None,
        "chart_analysis_file": item.get("chart_analysis_file"),
        "news_file": item.get("news_file"),
        "chart_preview": item.get("chart_preview"),
        "news_preview": item.get("news_preview"),
    }


def build_deep_analysis_report(result):
    performance = calculate_portfolio_performance(record_history=False)
    items = [compact_deep_analysis_item(item) for item in result.get("items", [])]
    actions = {}
    for item in items:
        action = str((item.get("decision") or {}).get("action") or "n/d")
        actions[action] = actions.get(action, 0) + 1

    return {
        "status": result.get("status"),
        "summary": result.get("summary", "Analisi completata."),
        "portfolio": {
            "total_value": safe_number(performance.get("total_value")),
            "cash": safe_number(performance.get("cash")),
            "invested": safe_number(performance.get("invested")),
            "pnl": safe_number(performance.get("total_pnl")),
            "pnl_pct": safe_number(performance.get("total_pnl_pct")),
            "positions": len(performance.get("positions") or []),
        },
        "actions": actions,
        "items": items,
    }


def update_deep_analysis_job(job_id, **changes):
    with DEEP_ANALYSIS_JOBS_LOCK:
        job = DEEP_ANALYSIS_JOBS.get(job_id)
        if not job:
            return
        event = changes.pop("event", None)
        job.update(changes)
        if event:
            event = {
                **event,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            job.setdefault("events", []).append(event)
            job["events"] = job["events"][-80:]


def run_deep_analysis_job(job_id, payload):
    def on_progress(event):
        ticker_part = f" ticker={event.get('ticker')}" if event.get("ticker") else ""
        count_part = ""
        if event.get("current") is not None and event.get("total") is not None:
            count_part = f" {event.get('current')}/{event.get('total')}"
        percent_part = f" {event.get('percent')}%" if event.get("percent") is not None else ""
        append_agent_logs(
            "[deep-analysis] "
            f"{event.get('stage', 'step')}{ticker_part}{count_part}{percent_part} | "
            f"{event.get('message', '')}"
        )
        update_deep_analysis_job(
            job_id,
            stage=event.get("stage"),
            message=event.get("message"),
            ticker=event.get("ticker"),
            current=event.get("current"),
            total=event.get("total"),
            percent=event.get("percent"),
            event=event,
        )

    update_deep_analysis_job(
        job_id,
        state="running",
        started_at=datetime.now().isoformat(timespec="seconds"),
        stage="starting",
        message="Avvio analisi approfondita del portafoglio.",
        percent=1,
        event={"stage": "starting", "message": "Job avviato dal backend."},
    )
    try:
        result = run_deep_portfolio_analysis(
            max_positions=max(1, min(int(payload["max_positions"]), 30)),
            create_proposals=bool(payload["create_proposals"]),
            auto_apply=bool(payload["auto_apply"]),
            send_telegram=bool(payload["telegram"]),
            use_playwright=True,
            live_news=True,
            progress_callback=on_progress,
        )
        summary = result.get("summary", "Analisi completata.")
        report = build_deep_analysis_report(result)
        report = save_last_deep_analysis_report(report)
        update_deep_analysis_job(
            job_id,
            state="completed",
            stage="completed",
            message=summary,
            percent=100,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            result=report,
        )
        append_agent_logs(f"Analisi approfondita portafoglio completata: {summary}")
    except Exception as exc:
        message = f"{exc.__class__.__name__}: {exc}"
        append_agent_logs(f"Analisi approfondita portafoglio fallita: {message}")
        update_deep_analysis_job(
            job_id,
            state="error",
            stage="error",
            message=message,
            error=message,
            finished_at=datetime.now().isoformat(timespec="seconds"),
            event={"stage": "error", "message": message},
        )


def dedupe_dashboard_conditions(conditions):
    """Keep one operational trigger card per ticker for dashboard display."""
    best_by_ticker = {}
    for item in conditions:
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        metadata = item.get("metadata") or {}
        scenario_state = str(metadata.get("scenario_state") or "").upper()
        status = str(item.get("status") or "").lower()
        rank = (
            SCENARIO_RANK.get(scenario_state, 0),
            STATUS_RANK.get(status, 0),
            str(item.get("updated_at") or item.get("created_at") or ""),
        )
        current = best_by_ticker.get(ticker)
        if current is None or rank > current[0]:
            best_by_ticker[ticker] = (rank, item)
    return [entry[1] for entry in best_by_ticker.values()]


def enrich_universe_with_scan(rows, scan_filename):
    scan_path = ROOT / "output" / "stock_ai" / scan_filename
    if not scan_path.exists():
        return rows
    try:
        payload = json.loads(scan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return rows
    candidates = payload.get("scanned_rows") or payload.get("candidates") or []
    by_ticker = {
        str(item.get("ticker", "")).strip().upper(): item
        for item in candidates
        if item.get("ticker")
    }
    if not by_ticker:
        return rows
    updated_at = datetime.fromtimestamp(scan_path.stat().st_mtime).isoformat()
    enriched = []
    for row in rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        scan_item = by_ticker.get(ticker)
        if scan_item:
            enriched.append({
                **scan_item,
                **row,
                "scan_updated_at": updated_at,
                "score_source": scan_filename,
            })
        else:
            enriched.append(row)
    return enriched


def json_safe(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def save_last_deep_analysis_report(report):
    payload = {
        **report,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    LAST_DEEP_ANALYSIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_DEEP_ANALYSIS_PATH.write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def load_last_deep_analysis_report():
    if not LAST_DEEP_ANALYSIS_PATH.exists():
        return None
    try:
        return json.loads(LAST_DEEP_ANALYSIS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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


class EtfScanRequest(BaseModel):
    limit: int = 8
    universe_limit: int = 0


class FtseMibScanRequest(BaseModel):
    limit: int = 8
    universe_limit: int = 0


class MarketInstrumentRequest(BaseModel):
    ticker: str
    name: str = ""
    description: str = ""
    sector: str = ""
    industry: str = ""
    latest_quotation: str = ""
    active: bool = True


class MarketInstrumentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    sector: str | None = None
    industry: str | None = None
    latest_quotation: str | None = None
    active: bool | None = None


class MarketImportRequest(BaseModel):
    path: str
    replace: bool = False
    activate: bool = False


class PortfolioDeepAnalysisRequest(BaseModel):
    max_positions: int = 10
    create_proposals: bool = False
    auto_apply: bool = False
    telegram: bool = False


class AutonomySettingsRequest(BaseModel):
    portfolio_action_mode: str = "full_auto"
    notify_telegram: bool = True


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


def append_run_journal_log(line: str):
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    with (log_dir / "run-journal.log").open("a", encoding="utf-8") as handle:
        handle.write(timestamped(line.rstrip()) + "\n")


def append_agent_logs(line: str):
    append_web_agent_log(line)
    append_run_journal_log(line)


def kill_process_tree(pid: int):
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        subprocess.run(
            ["pkill", "-TERM", "-P", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


def run_agent_command(args, timeout=900, script="agent_portfolio_manager.py"):
    cmd = [sys.executable, str(ROOT / script), *args]
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    append_agent_logs(f"===== RUN {run_id} START script={script} =====")
    append_agent_logs(f"[runner] cwd={ROOT}")
    append_agent_logs(f"[runner] command={' '.join(cmd)}")
    env = {
        **dict(os.environ),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "TRADINGWATCH_TIMESTAMP_LOGS": "0",
    }
    process = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output_lines = []
    output_queue = Queue()

    def reader():
        try:
            for line in process.stdout:
                output_queue.put(line.rstrip("\n"))
        finally:
            output_queue.put(None)

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    reader_done = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                kill_process_tree(process.pid)
                append_agent_logs(f"===== RUN {run_id} TIMEOUT dopo {timeout}s: processo agente terminato =====")
                raise HTTPException(status_code=504, detail=f"Timeout agente dopo {timeout}s")

            try:
                line = output_queue.get(timeout=min(0.5, max(0.05, remaining)))
            except Empty:
                if process.poll() is not None and reader_done:
                    break
                continue

            if line is None:
                reader_done = True
                if process.poll() is not None:
                    break
                continue

            output_lines.append(line)
            append_agent_logs(f"[run {run_id}] {line}")

            if process.poll() is not None and reader_done:
                break
    finally:
        try:
            if process.stdout:
                process.stdout.close()
        except OSError:
            pass

    thread.join(timeout=2)
    return_code = process.wait(timeout=5)
    output = "\n".join(output_lines).strip()
    append_agent_logs(f"===== RUN {run_id} END exit={return_code} righe={len(output_lines)} =====")
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
        "Questa richiesta arriva dalla web app React di Autonomous Trading Agent.",
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
    active_conditions = [
        item
        for item in status.get("monitored_conditions", [])
        if item.get("status") in {"waiting", "met"}
    ]
    active_conditions = dedupe_dashboard_conditions(active_conditions)
    monitored = enrich_monitored_conditions(active_conditions)
    exits = build_exit_conditions(performance, portfolio)
    closed = list(reversed((portfolio or {}).get("closed_proposals", [])))[:20]
    return json_safe({
        "portfolio": status,
        "performance": performance,
        "performance_history": performance_history,
        "monitored": monitored,
        "exit_conditions": exits,
        "agent_run_state": agent_schedule_status(),
        "recent_actions": closed,
        "ftse_mib": enrich_universe_with_scan(load_mib30_tickers(), "mib30_scan.json"),
        "commodities": enrich_universe_with_scan(load_commodity_tickers(), "commodity_scan.json"),
        "etfs": enrich_universe_with_scan(load_etf_tickers(), "etf_scan.json"),
    })


def fallback_market_rows(market: str):
    key = str(market or "").lower().replace("-", "_")
    if key in {"ftse_mib", "ftsemib", "mib30"}:
        return load_mib30_tickers()
    if key in {"commodities", "commodity", "materie_prime"}:
        return load_commodity_tickers()
    if key in {"etfs", "etf"}:
        return load_etf_tickers()
    return []


@app.get("/api/markets/{market}/universe")
def market_universe(market: str):
    try:
        return json_safe(list_market_universe(market, fallback_rows=fallback_market_rows(market)))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/markets/{market}/instrument")
def market_add_instrument(market: str, request: MarketInstrumentRequest):
    try:
        return json_safe(add_market_instrument(market, request.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/markets/{market}/instrument/{ticker}")
def market_update_instrument(market: str, ticker: str, request: MarketInstrumentUpdateRequest):
    try:
        return json_safe(update_market_instrument(market, ticker, request.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/markets/{market}/instrument/{ticker}")
def market_remove_instrument(market: str, ticker: str):
    try:
        return json_safe(remove_market_instrument(market, ticker))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/markets/{market}/import-excel")
def market_import_excel(market: str, request: MarketImportRequest):
    try:
        return json_safe(
            import_market_universe_from_excel(
                market,
                request.path,
                replace=bool(request.replace),
                activate=bool(request.activate),
            )
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@app.get("/api/etfs")
def etfs():
    items = load_etf_tickers()
    return {
        "status": "ok",
        "etfs": items,
        "items": items,
        "count": len(items),
        "active_count": len([item for item in items if item.get("active", True)]),
    }


@app.post("/api/etfs/scan")
def etfs_scan(request: EtfScanRequest):
    try:
        return scan_etf_candidates(
            limit=max(1, min(int(request.limit), 30)),
            universe_limit=int(request.universe_limit) or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore scanner ETF: {exc}") from exc


@app.get("/api/run-logs")
def run_logs(lines: int = 300):
    max_lines = max(20, min(int(lines or 300), 2000))
    log_dir = ROOT / "logs"
    scheduled_log = log_dir / "scheduled-monitor.log"
    scheduled_err = log_dir / "scheduled-monitor.err.log"
    web_agent_log = log_dir / "web-agent.log"
    run_journal_log = log_dir / "run-journal.log"
    manual_optimized_log = log_dir / "manual-optimized-run.log"
    telegram_agent_log = log_dir / "telegram-agent.log"
    agent_state = agent_schedule_status()

    def log_meta(path: Path):
        if not path.exists():
            return {"name": path.name, "exists": False, "size": 0, "updated_at": None}
        stat = path.stat()
        return {
            "name": path.name,
            "exists": True,
            "size": stat.st_size,
            "updated_at": stat.st_mtime,
        }

    def titled_tail(path: Path, title: str):
        text = tail_text(path, max_lines)
        if not text.strip():
            return f"===== {title} =====\nNessun output disponibile in {path.name}."
        return f"===== {title} ({path.name}) =====\n{text}"

    combined_parts = [
        titled_tail(run_journal_log, "JOURNAL RUN UNIFICATO"),
        titled_tail(manual_optimized_log, "RUN MANUALE OTTIMIZZATO"),
        titled_tail(scheduled_log, "RUN SCHEDULATO"),
        titled_tail(web_agent_log, "RICHIESTE DA GUI/CHAT"),
        titled_tail(telegram_agent_log, "BRIDGE TELEGRAM"),
    ]
    return {
        "status": "ok",
        "lines": max_lines,
        "agent_run_state": agent_state,
        "combined_run_log": "\n\n".join(combined_parts),
        "run_journal_log": tail_text(run_journal_log, max_lines),
        "manual_optimized_log": tail_text(manual_optimized_log, max_lines),
        "scheduled_log": tail_text(scheduled_log, max_lines),
        "scheduled_err": tail_text(scheduled_err, max_lines),
        "web_agent_log": tail_text(web_agent_log, max_lines),
        "telegram_agent_log": tail_text(telegram_agent_log, max_lines),
        "log_files": [
            log_meta(run_journal_log),
            log_meta(manual_optimized_log),
            log_meta(scheduled_log),
            log_meta(scheduled_err),
            log_meta(web_agent_log),
            log_meta(telegram_agent_log),
        ],
        "run_journal_log_updated_at": run_journal_log.stat().st_mtime if run_journal_log.exists() else None,
        "manual_optimized_log_updated_at": manual_optimized_log.stat().st_mtime if manual_optimized_log.exists() else None,
        "scheduled_log_updated_at": scheduled_log.stat().st_mtime if scheduled_log.exists() else None,
        "scheduled_err_updated_at": scheduled_err.stat().st_mtime if scheduled_err.exists() else None,
        "web_agent_log_updated_at": web_agent_log.stat().st_mtime if web_agent_log.exists() else None,
        "telegram_agent_log_updated_at": telegram_agent_log.stat().st_mtime if telegram_agent_log.exists() else None,
    }


@app.post("/api/run-logs/clear")
def clear_run_logs():
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    cleared = []
    for filename in (
        "run-journal.log",
        "manual-optimized-run.log",
        "web-agent.log",
        "scheduled-monitor.log",
        "scheduled-monitor.err.log",
        "telegram-agent.log",
    ):
        path = log_dir / filename
        path.write_text("", encoding="utf-8")
        cleared.append(filename)
    append_agent_logs("===== LOG RIPULITI DA GUI =====")
    return {"status": "ok", "cleared": cleared}


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
    output = run_agent_command(["--model", SDK_MODEL, build_context(request.history, request.message)])
    return {"answer": extract_agent_answer(output), "raw": output}


@app.post("/api/agent/run-once")
def run_once(request: RunMonitorRequest):
    append_agent_logs(
        "===== RUN MANUALE DA GUI: avvio monitor autonomo "
        f"universo=FTSE MIB completo + MateriePrime.xlsx completo + watchlist + trigger; "
        f"top_candidati={int(request.scan_limit)} max_auto_trade_pct={float(request.max_auto_trade_pct)} ====="
    )
    output = run_agent_command(
        [
            "--model",
            SDK_MODEL,
            "--autonomous-monitor",
            "--once",
            "--scan-limit",
            str(int(request.scan_limit)),
            "--universe-limit",
            "0",
            "--periodic-live-news",
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
        "2) usa confirm_candidate_chart_with_playwright(no_telegram=True, reason='watchlist: serve definire trigger ingresso con grafico AI') "
        "per analisi visuale AI via Playwright; "
        "3) usa analyze_stock_news(live=True) per cercare news aggiornate via Playwright/ChatGPT; "
        "4) definisci una entry_condition concreta scegliendo uno di due scenari: "
        "SCENARIO BREAKOUT = chiusura sopra resistenza/trigger con volumi in recupero o sopra media, stop sotto supporto/livello rotto; "
        "SCENARIO PULLBACK_SUPPORTO = ingresso vicino al supporto solo se il supporto tiene e compare rimbalzo/reazione positiva, "
        "con stop stretto sotto supporto e target verso resistenza/trigger. "
        "Non considerare il semplice arrivo vicino al supporto come buy automatico: serve evidenza di tenuta/rimbalzo e news non negative. "
        "5) aggiorna la watchlist con add_ticker_to_watchlist mantenendo motivo, priorita e tag esistenti quando disponibili. "
        "Non creare proposte di acquisto in questa azione: imposta solo condizioni ingresso per la watchlist. "
        "Concludi con una tabella compatta ticker, prezzo, condizione ingresso impostata, supporto/stop e motivazione."
    )
    output = run_agent_command(["--model", SDK_MODEL, prompt], timeout=1800)
    return {"output": output, "answer": extract_agent_answer(output)}


@app.post("/api/portfolio/deep-analysis")
def portfolio_deep_analysis(request: PortfolioDeepAnalysisRequest):
    payload = request.model_dump()
    with DEEP_ANALYSIS_JOBS_LOCK:
        active_job = next(
            (
                job
                for job in DEEP_ANALYSIS_JOBS.values()
                if job.get("state") in {"queued", "running"}
            ),
            None,
        )
        if active_job:
            append_agent_logs(
                "Richiesta analisi approfondita ignorata: "
                f"job {active_job['job_id']} gia in corso."
            )
            return {
                "status": "started",
                "job_id": active_job["job_id"],
                "reused": True,
                "message": "Analisi gia in corso: collegamento al job esistente.",
            }
        job_id = uuid.uuid4().hex
        DEEP_ANALYSIS_JOBS[job_id] = {
            "job_id": job_id,
            "state": "queued",
            "stage": "queued",
            "message": "Analisi accodata.",
            "ticker": None,
            "current": 0,
            "total": None,
            "percent": 0,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "started_at": None,
            "finished_at": None,
            "events": [],
        }
    append_agent_logs(
        "===== ANALISI APPROFONDITA PORTAFOGLIO ON DEMAND: "
        "scope=solo posizioni aperte | "
        f"max_positions={int(request.max_positions)} "
        f"create_proposals={bool(request.create_proposals)} "
        f"auto_apply={bool(request.auto_apply)} telegram={bool(request.telegram)} ====="
    )
    threading.Thread(
        target=run_deep_analysis_job,
        args=(job_id, payload),
        daemon=True,
        name=f"portfolio-deep-{job_id[:8]}",
    ).start()
    return {"status": "started", "job_id": job_id}


@app.get("/api/portfolio/deep-analysis/latest")
def latest_portfolio_deep_analysis():
    return {"status": "ok", "report": load_last_deep_analysis_report()}


@app.get("/api/portfolio/deep-analysis/{job_id}")
def portfolio_deep_analysis_status(job_id: str):
    with DEEP_ANALYSIS_JOBS_LOCK:
        job = DEEP_ANALYSIS_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job analisi non trovato.")
        return json.loads(json.dumps(job))


@app.get("/api/autonomy/settings")
def autonomy_settings():
    return {"status": "ok", "settings": load_autonomy_settings()}


@app.post("/api/autonomy/settings")
def update_autonomy_settings(request: AutonomySettingsRequest):
    try:
        settings = save_autonomy_settings(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    append_agent_logs(
        "Configurazione autonomia aggiornata dalla GUI | "
        f"portfolio_action_mode={settings['portfolio_action_mode']} "
        f"notify_telegram={settings['notify_telegram']}"
    )
    return {"status": "ok", "settings": settings}


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
