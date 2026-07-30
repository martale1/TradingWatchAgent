import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from finance_tools.common import PROJECT_ROOT, run_python_script
from finance_tools.playwright_queue import run_serialized_playwright
from finance_tools.playwright_health import (
    record_playwright_failure,
    record_playwright_success,
)


STOCK_CATALOG = {
    "VOD.L": {"company": "Vodafone", "market": "London Stock Exchange"},
    "A2A.MI": {"company": "A2A", "market": "Borsa Italiana"},
    "AVIO.MI": {"company": "Avio", "market": "Borsa Italiana"},
}


def load_valid_ticker_info(ticker):
    path = PROJECT_ROOT / "validTickers" / "validtickers_IT_MIB30_with_sector.xlsx"
    if not path.exists():
        return {}
    try:
        df = pd.read_excel(path).fillna("")
    except Exception:
        return {}
    clean = ticker.strip().upper()
    matches = df[df["Ticker"].astype(str).str.upper().str.strip() == clean]
    if matches.empty:
        return {}
    row = matches.iloc[0]
    return {
        "company": str(row.get("Name", clean)).strip() or clean,
        "market": "Borsa Italiana" if clean.endswith(".MI") else "",
    }


def ticker_info(ticker):
    clean = ticker.strip().upper()
    info = STOCK_CATALOG.get(clean) or load_valid_ticker_info(clean)
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


def _is_recent(path, minutes):
    if not path.exists() or not minutes:
        return False
    modified_at = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - modified_at <= timedelta(minutes=minutes)


def _attach_telegram_notification(result):
    if result.get("status") != "ok":
        return result
    try:
        from finance_tools.news_notifications import send_relevant_news_alerts

        result["telegram_notification"] = send_relevant_news_alerts([result.get("ticker")])
    except Exception as exc:
        result["telegram_notification"] = {
            "status": "error",
            "message": f"{exc.__class__.__name__}: {exc}",
        }
    return result


def get_news_report(ticker, live=False, cache_minutes=30, force=False):
    info = ticker_info(ticker)
    output_path = PROJECT_ROOT / "output" / "stock_ai" / info["ticker"].replace("/", "_") / f"{info['ticker']}_news.txt"
    print(f"[news-tool] {info['ticker']} - richiesta news | live={live}", flush=True)

    if output_path.exists() and (not live or (not force and _is_recent(output_path, cache_minutes))):
        source = "cached_file" if not live else "cached_live_file"
        detail = f"cache recente <={cache_minutes} min" if live else "cache locale"
        print(f"[news-tool] {info['ticker']} - leggo news da {detail}: {output_path}", flush=True)
        return _attach_telegram_notification({
            "ticker": info["ticker"],
            "status": "ok",
            "source": source,
            "report": output_path.read_text(encoding="utf-8", errors="replace"),
            "file": str(output_path),
        })

    if not live:
        print(f"[news-tool] {info['ticker']} - cache non presente, live disattivato", flush=True)
        return {
            "ticker": info["ticker"],
            "status": "missing",
            "source": "none",
            "report": "Nessun report news salvato. Esegui con --live-news per interrogare ChatGPT via Playwright.",
            "file": str(output_path),
        }

    print(f"[news-tool] {info['ticker']} - preparo Playwright/ChatGPT tramite chatgpt_playwright_demo.py", flush=True)
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
    def runner():
        print(
            f"[news-tool] {info['ticker']} - attendo risposta dallo script Playwright/ChatGPT "
            "(news live)",
            flush=True,
        )
        return run_python_script(
            args,
            timeout_seconds=150,
            progress_label=f"news-live {info['ticker']}",
            heartbeat_seconds=15,
        )

    result = run_serialized_playwright(f"news {info['ticker']}", runner)
    report = _extract_response(result["stdout"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"[news-tool] {info['ticker']} - report news salvato: {output_path}", flush=True)
    status = "ok" if result["returncode"] == 0 and report else "error"
    if status == "ok":
        record_playwright_success("news live", ticker=info["ticker"])
    else:
        record_playwright_failure(
            "news live",
            detail=result.get("stderr") or result.get("stdout"),
            ticker=info["ticker"],
        )
    return _attach_telegram_notification({
        "ticker": info["ticker"],
        "status": status,
        "source": "live_playwright",
        "report": report,
        "file": str(output_path),
        "stderr": result["stderr"],
    })


def get_news_report_json(ticker, live=False):
    return json.dumps(get_news_report(ticker, live=live), ensure_ascii=False, indent=2)
