import json
from datetime import datetime, timedelta
from pathlib import Path

from finance_tools.common import PROJECT_ROOT, run_python_script
from finance_tools.playwright_queue import run_serialized_playwright
from finance_tools.playwright_health import (
    record_playwright_failure,
    record_playwright_success,
)


def _is_recent(path, minutes):
    if not path.exists() or not minutes:
        return False
    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - modified_at <= timedelta(minutes=minutes)


def confirm_candidate_with_chart_ai(ticker, no_telegram=True, cache_minutes=30, force=False):
    clean = ticker.strip().upper()
    safe_ticker = clean.replace("/", "_")
    output_dir = PROJECT_ROOT / "output" / "stock_ai" / safe_ticker
    analysis_path = output_dir / f"{safe_ticker}_analysis.txt"

    if not force and _is_recent(analysis_path, cache_minutes):
        report = analysis_path.read_text(encoding="utf-8", errors="replace")
        print(
            f"[deep-chart-tool] {clean} - riuso analisi grafica Playwright recente "
            f"(<={cache_minutes} min): {analysis_path}",
            flush=True,
        )
        return {
            "ticker": clean,
            "status": "ok",
            "source": "cached_playwright_chart_ai",
            "report": report,
            "analysis_file": str(analysis_path),
            "stdout_tail": "",
            "stderr": "",
            "cache_minutes": cache_minutes,
        }

    print(f"[deep-chart-tool] {clean} - preparo conferma visuale grafici con Playwright", flush=True)

    args = ["stock_chart_ai_analysis.py", "--stocks", clean]
    if no_telegram:
        args.append("--no-telegram")

    def runner():
        print(
            f"[deep-chart-tool] {clean} - richiamo stock_chart_ai_analysis.py "
            "(grafici + analisi visuale)",
            flush=True,
        )
        return run_python_script(
            args,
            timeout_seconds=150,
            progress_label=f"chart-ai {clean}",
            heartbeat_seconds=15,
        )

    result = run_serialized_playwright(f"chart {clean}", runner)
    report = ""
    if analysis_path.exists():
        report = analysis_path.read_text(encoding="utf-8", errors="replace")
        print(f"[deep-chart-tool] {clean} - analisi visuale salvata: {analysis_path}", flush=True)
    else:
        print(f"[deep-chart-tool] {clean} - attenzione: file analisi non trovato", flush=True)
        if result["stderr"]:
            print(f"[deep-chart-tool] {clean} - errore: {result['stderr'][-800:]}", flush=True)

    status = "ok" if result["returncode"] == 0 and report else "error"
    if status == "ok":
        record_playwright_success("analisi grafica", ticker=clean)
    else:
        record_playwright_failure(
            "analisi grafica",
            detail=result.get("stderr") or result.get("stdout"),
            ticker=clean,
        )
    return {
        "ticker": clean,
        "status": status,
        "source": "playwright_chart_ai",
        "report": report,
        "analysis_file": str(analysis_path),
        "stdout_tail": result["stdout"][-2000:],
        "stderr": result["stderr"],
    }


def confirm_candidate_with_chart_ai_json(ticker, no_telegram=True):
    return json.dumps(
        confirm_candidate_with_chart_ai(ticker=ticker, no_telegram=no_telegram),
        ensure_ascii=False,
        indent=2,
    )
