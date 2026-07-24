import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from finance_tools.commodity_scanner import scan_commodity_candidates
from finance_tools.common import PROJECT_ROOT, load_env_file
from finance_tools.deep_chart_tool import confirm_candidate_with_chart_ai
from finance_tools.mib30_scanner import scan_mib30_candidates
from finance_tools.performance_tool import calculate_portfolio_performance
from finance_tools.portfolio_store import list_monitored_conditions, list_watchlist
from finance_tools.telegram_tool import send_telegram_message


OUTPUT_FILE = PROJECT_ROOT / "output" / "stock_ai" / "playwright_monitor_report.json"
TEXT_REPORT_FILE = PROJECT_ROOT / "output" / "stock_ai" / "playwright_monitor_report.txt"


def configure_stdout():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


def log(message):
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [playwright-monitor] {message}", flush=True)


def compact_candidate(item, market):
    return {
        "ticker": item.get("ticker"),
        "name": item.get("name") or item.get("description") or item.get("ticker"),
        "market": market,
        "score": item.get("score"),
        "close": item.get("close"),
        "change_1d_pct": item.get("change_1d_pct"),
        "rsi": item.get("rsi"),
        "adx": item.get("adx"),
        "support_10": item.get("support_10"),
        "resistance_10": item.get("resistance_10"),
        "reasons": item.get("reasons") or [],
        "risks": item.get("risks") or [],
    }


def select_candidates(mib_scan, commodity_scan, limit):
    rows = []
    for item in mib_scan.get("candidates", []):
        rows.append(compact_candidate(item, "FTSE MIB"))
    for item in commodity_scan.get("candidates", []):
        rows.append(compact_candidate(item, "Materie prime"))
    rows.sort(key=lambda item: (item.get("score") or 0), reverse=True)
    return rows[:limit]


def build_text_report(performance, candidates, confirmations, watchlist, conditions):
    lines = [
        "TWA | Playwright monitor",
        datetime.now().strftime("%d/%m/%Y %H:%M"),
        "",
        "Modalita: scan locale + approfondimento ChatGPT via Playwright",
        "Uso API key OpenAI SDK: NO",
        "",
        "PORTAFOGLIO",
        f"Valore: EUR {performance.get('total_value', 0):.2f}",
        f"P/L: EUR {performance.get('total_pnl', 0):+.2f} ({performance.get('total_pnl_pct', 0):+.2f}%)",
        f"Cash: EUR {performance.get('cash', 0):.2f}",
        f"Posizioni: {len(performance.get('positions') or [])}",
        "",
        "SHORTLIST",
    ]
    if not candidates:
        lines.append("nessun candidato selezionato")
    for item in candidates:
        reasons = "; ".join(item.get("reasons")[:2]) or "segnale tecnico locale"
        risks = "; ".join(item.get("risks")[:2]) or "nessun rischio principale"
        lines.append(
            f"- {item['ticker']} ({item['market']}): score {item.get('score')} | close {item.get('close')} | "
            f"oggi {item.get('change_1d_pct'):+.2f}% | {reasons} | rischi: {risks}"
        )

    lines.extend(["", "APPROFONDIMENTI PLAYWRIGHT"])
    for item in confirmations:
        status = item.get("status")
        report = (item.get("report") or "").strip()
        first_lines = [line.strip() for line in report.splitlines() if line.strip()][:8]
        lines.append(f"- {item.get('ticker')}: {status}")
        lines.extend(f"  {line}" for line in first_lines[:6])
        if not first_lines and item.get("stderr"):
            lines.append(f"  errore: {item.get('stderr')[-180:]}")

    lines.extend(["", "WATCHLIST / CONDIZIONI"])
    lines.append(f"Watchlist manuale: {len(watchlist)} titoli")
    lines.append(f"Condizioni monitorate: {len(conditions)}")
    for item in conditions[:6]:
        lines.append(f"- {item.get('ticker')}: {item.get('condition')}")

    return "\n".join(lines)


def run(limit=5, deep_limit=2, universe_limit=0, send_telegram=False):
    load_env_file()
    log("Avvio monitor Playwright-first: nessuna chiamata OpenAI SDK")
    performance = calculate_portfolio_performance()
    log("Performance portafoglio calcolata")

    mib_scan = scan_mib30_candidates(limit=limit, universe_limit=universe_limit or None, verbose=True)
    commodity_scan = scan_commodity_candidates(limit=limit, universe_limit=universe_limit or None, verbose=True)
    candidates = select_candidates(mib_scan, commodity_scan, limit=limit)
    log(f"Shortlist unica pronta: {len(candidates)} candidati")

    confirmations = []
    for item in candidates[:deep_limit]:
        ticker = item["ticker"]
        log(f"Approfondisco via Playwright/ChatGPT: {ticker}")
        confirmations.append(confirm_candidate_with_chart_ai(ticker=ticker, no_telegram=True))

    watchlist = list_watchlist()
    conditions = list_monitored_conditions()
    report = build_text_report(performance, candidates, confirmations, watchlist, conditions)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(
            {
                "status": "ok",
                "created_at": datetime.now().replace(microsecond=0).isoformat(),
                "performance": performance,
                "candidates": candidates,
                "confirmations": confirmations,
                "watchlist_count": len(watchlist),
                "conditions_count": len(conditions),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    TEXT_REPORT_FILE.write_text(report, encoding="utf-8")
    log(f"Report salvato: {TEXT_REPORT_FILE}")

    if send_telegram:
        result = send_telegram_message(report[:3900])
        log(f"Telegram: {result.get('status')} {result.get('message', '')}")

    print("\n" + report + "\n", flush=True)
    return report


def main():
    configure_stdout()
    parser = argparse.ArgumentParser(description="Monitor Playwright-first senza OpenAI SDK/API key.")
    parser.add_argument("--limit", type=int, default=5, help="Numero candidati in shortlist.")
    parser.add_argument("--deep-limit", type=int, default=2, help="Numero candidati da approfondire via Playwright.")
    parser.add_argument("--universe-limit", type=int, default=0, help="Solo test: limita universo FTSE MIB e materie prime.")
    parser.add_argument("--telegram", action="store_true", help="Invia report via Telegram.")
    args = parser.parse_args()
    run(limit=args.limit, deep_limit=args.deep_limit, universe_limit=args.universe_limit, send_telegram=args.telegram)


if __name__ == "__main__":
    main()
