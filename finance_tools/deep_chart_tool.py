import json
from pathlib import Path

from finance_tools.common import PROJECT_ROOT, run_python_script
from finance_tools.playwright_queue import run_serialized_playwright


def confirm_candidate_with_chart_ai(ticker, no_telegram=True):
    clean = ticker.strip().upper()
    safe_ticker = clean.replace("/", "_")
    output_dir = PROJECT_ROOT / "output" / "stock_ai" / safe_ticker
    analysis_path = output_dir / f"{safe_ticker}_analysis.txt"

    print(f"[deep-chart-tool] {clean} - preparo conferma visuale grafici con Playwright", flush=True)

    args = ["stock_chart_ai_analysis.py", "--stocks", clean]
    if no_telegram:
        args.append("--no-telegram")

    def runner():
        print(f"[deep-chart-tool] {clean} - richiamo stock_chart_ai_analysis.py", flush=True)
        return run_python_script(args, timeout_seconds=420)

    result = run_serialized_playwright(f"chart {clean}", runner)
    report = ""
    if analysis_path.exists():
        report = analysis_path.read_text(encoding="utf-8", errors="replace")
        print(f"[deep-chart-tool] {clean} - analisi visuale salvata: {analysis_path}", flush=True)
    else:
        print(f"[deep-chart-tool] {clean} - attenzione: file analisi non trovato", flush=True)
        if result["stderr"]:
            print(f"[deep-chart-tool] {clean} - errore: {result['stderr'][-800:]}", flush=True)

    return {
        "ticker": clean,
        "status": "ok" if result["returncode"] == 0 and report else "error",
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
