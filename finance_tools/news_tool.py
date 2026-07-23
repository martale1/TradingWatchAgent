import json
from pathlib import Path

from finance_tools.common import PROJECT_ROOT, run_python_script


STOCK_CATALOG = {
    "VOD.L": {"company": "Vodafone", "market": "London Stock Exchange"},
    "A2A.MI": {"company": "A2A", "market": "Borsa Italiana"},
    "AVIO.MI": {"company": "Avio", "market": "Borsa Italiana"},
}


def ticker_info(ticker):
    clean = ticker.strip().upper()
    info = STOCK_CATALOG.get(clean, {})
    return {
        "ticker": clean,
        "company": info.get("company", clean),
        "market": info.get("market", ""),
    }


def _extract_response(stdout):
    marker = "--- Risposta ChatGPT ---"
    if marker not in stdout:
        return stdout.strip()
    return stdout.split(marker, 1)[1].strip()


def get_news_report(ticker, live=False):
    info = ticker_info(ticker)
    output_path = PROJECT_ROOT / "output" / "stock_ai" / info["ticker"].replace("/", "_") / f"{info['ticker']}_news.txt"

    if not live and output_path.exists():
        return {
            "ticker": info["ticker"],
            "status": "ok",
            "source": "cached_file",
            "report": output_path.read_text(encoding="utf-8", errors="replace"),
            "file": str(output_path),
        }

    if not live:
        return {
            "ticker": info["ticker"],
            "status": "missing",
            "source": "none",
            "report": "Nessun report news salvato. Esegui con --live-news per interrogare ChatGPT via Playwright.",
            "file": str(output_path),
        }

    args = [
        "chatgpt_playwright_demo.py",
        "--no-telegram",
        "--ticker",
        info["ticker"],
        "--company",
        info["company"],
        "--market",
        info["market"],
    ]
    result = run_python_script(args, timeout_seconds=300)
    report = _extract_response(result["stdout"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return {
        "ticker": info["ticker"],
        "status": "ok" if result["returncode"] == 0 else "error",
        "source": "live_playwright",
        "report": report,
        "file": str(output_path),
        "stderr": result["stderr"],
    }


def get_news_report_json(ticker, live=False):
    return json.dumps(get_news_report(ticker, live=live), ensure_ascii=False, indent=2)

