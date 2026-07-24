import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from finance_tools.common import PROJECT_ROOT


STATE_FILE = PROJECT_ROOT / "agent_run_state.json"
ANALYSIS_ROOT = PROJECT_ROOT / "output" / "stock_ai"


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def default_interval_minutes():
    try:
        return int(os.getenv("MONITOR_INTERVAL_MINUTES", "30"))
    except ValueError:
        return 30


def load_agent_run_state(path=STATE_FILE):
    file_path = Path(path)
    if not file_path.exists():
        return {
            "status": "never_run",
            "message": "Nessuna analisi agente registrata.",
            "interval_minutes": default_interval_minutes(),
            "last_started_at": None,
            "last_completed_at": None,
            "next_expected_at": None,
            "last_mode": None,
            "last_scan_limit": None,
            "last_universe_limit": None,
            "last_error": "",
        }
    state = json.loads(file_path.read_text(encoding="utf-8"))
    interval = int(state.get("interval_minutes") or default_interval_minutes())
    if not state.get("next_expected_at") and state.get("last_completed_at"):
        completed = parse_iso(state.get("last_completed_at"))
        if completed:
            state["next_expected_at"] = (completed + timedelta(minutes=interval)).isoformat()
    if not state.get("next_expected_at") and state.get("last_started_at"):
        started = parse_iso(state.get("last_started_at"))
        if started:
            state["next_expected_at"] = (started + timedelta(minutes=interval)).isoformat()
    return state


def latest_stock_analysis_state():
    files = []
    if ANALYSIS_ROOT.exists():
        files = list(ANALYSIS_ROOT.glob("*/*_analysis.txt"))
    if not files:
        state = load_agent_run_state()
        return {
            "last_stock_analysis_at": state.get("last_completed_at"),
            "last_stock_analysis_source": "agent_run_state" if state.get("last_completed_at") else "none",
            "last_stock_analysis_ticker": None,
            "analyzed_tickers_count": 0,
        }

    latest = max(files, key=lambda item: item.stat().st_mtime)
    tickers = sorted({path.parent.name.upper() for path in files})
    return {
        "last_stock_analysis_at": datetime.fromtimestamp(latest.stat().st_mtime).replace(microsecond=0).isoformat(),
        "last_stock_analysis_source": "Playwright/ChatGPT chart analysis",
        "last_stock_analysis_ticker": latest.parent.name.upper(),
        "analyzed_tickers_count": len(tickers),
        "analyzed_tickers": tickers,
    }


def windows_scheduler_state(task_name=None):
    if os.name != "nt":
        return {}
    task = task_name or os.getenv("WINDOWS_MONITOR_TASK_NAME", "TradingWatchAgentMonitor")
    script = (
        f"$task=Get-ScheduledTask -TaskName '{task}' -ErrorAction SilentlyContinue; "
        "if (-not $task) { return }; "
        f"$info=Get-ScheduledTaskInfo -TaskName '{task}' -ErrorAction SilentlyContinue; "
        "[pscustomobject]@{"
        "TaskName=$task.TaskName;"
        "State=$task.State.ToString();"
        "LastRunTime=if($info.LastRunTime){$info.LastRunTime.ToString('s')}else{$null};"
        "NextRunTime=if($info.NextRunTime){$info.NextRunTime.ToString('s')}else{$null};"
        "LastTaskResult=$info.LastTaskResult;"
        "NumberOfMissedRuns=$info.NumberOfMissedRuns"
        "} | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=8,
        )
    except Exception as exc:
        return {"scheduler_error": str(exc)}
    if result.returncode != 0 or not result.stdout.strip():
        return {"scheduler_error": result.stderr.strip() or "Task scheduler non disponibile."}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"scheduler_error": f"Risposta scheduler non valida: {exc}"}
    return {
        "scheduler_task_name": data.get("TaskName"),
        "scheduler_state": data.get("State"),
        "scheduler_last_run_at": data.get("LastRunTime"),
        "scheduler_next_run_at": data.get("NextRunTime"),
        "scheduler_last_task_result": data.get("LastTaskResult"),
        "scheduler_missed_runs": data.get("NumberOfMissedRuns"),
        "scheduler_enabled": data.get("State") not in ("Disabled", None),
    }


def agent_schedule_status():
    state = load_agent_run_state()
    stock = latest_stock_analysis_state()
    scheduler = windows_scheduler_state()
    next_expected = parse_iso(state.get("next_expected_at"))
    now = datetime.now()
    is_overdue = bool(next_expected and next_expected < now)
    is_stale_running = bool(
        state.get("status") == "running"
        and state.get("last_started_at")
        and parse_iso(state.get("last_started_at"))
        and (now - parse_iso(state.get("last_started_at"))) > timedelta(minutes=int(state.get("interval_minutes") or default_interval_minutes()) * 2)
    )
    return {
        **state,
        **stock,
        **scheduler,
        "next_scheduled_expected_at": state.get("next_expected_at"),
        "next_scheduled_is_overdue": is_overdue,
        "running_state_is_stale": is_stale_running,
    }


def save_agent_run_state(state, path=STATE_FILE):
    file_path = Path(path)
    file_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def mark_agent_run_started(
    mode,
    interval_minutes=None,
    scan_limit=None,
    universe_limit=None,
    live_news=False,
    auto_apply_virtual=False,
    cycle=None,
):
    interval = int(interval_minutes or default_interval_minutes())
    state = load_agent_run_state()
    state.update(
        {
            "status": "running",
            "last_started_at": now_iso(),
            "last_mode": mode,
            "interval_minutes": interval,
            "last_scan_limit": scan_limit,
            "last_universe_limit": universe_limit,
            "last_live_news": bool(live_news),
            "last_auto_apply_virtual": bool(auto_apply_virtual),
            "last_cycle": cycle,
            "last_error": "",
        }
    )
    return save_agent_run_state(state)


def mark_agent_run_completed(interval_minutes=None, once=False, error=""):
    interval = int(interval_minutes or default_interval_minutes())
    completed = datetime.now().replace(microsecond=0)
    state = load_agent_run_state()
    state.update(
        {
            "status": "error" if error else "ok",
            "last_completed_at": completed.isoformat(),
            "interval_minutes": interval,
            "next_expected_at": (completed + timedelta(minutes=interval)).isoformat(),
            "last_error": str(error or ""),
            "last_warning": "" if not error else state.get("last_warning", ""),
            "last_run_was_once": bool(once),
        }
    )
    return save_agent_run_state(state)
