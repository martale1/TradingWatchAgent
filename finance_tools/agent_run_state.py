import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from finance_tools.common import PROJECT_ROOT


STATE_FILE = PROJECT_ROOT / "agent_run_state.json"


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
    return state


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
            "last_run_was_once": bool(once),
        }
    )
    return save_agent_run_state(state)
