import json
from pathlib import Path

import pandas as pd

from finance_tools.chart_tool import generate_snapshot_context
from finance_tools.common import PROJECT_ROOT
from finance_tools.mib30_scanner import score_snapshot


COMMODITIES_XLSX = PROJECT_ROOT / "validTickers" / "MateriePrime.xlsx"


def load_commodity_tickers(path=COMMODITIES_XLSX):
    file_path = Path(path)
    if not file_path.exists():
        return []

    df = pd.read_excel(file_path)
    records = []
    for row in df.fillna("").to_dict(orient="records"):
        ticker = str(row.get("Ticker", "")).strip().upper()
        if not ticker:
            continue
        records.append(
            {
                "ticker": ticker,
                "name": str(row.get("Name", ticker)).strip() or ticker,
                "latest_quotation": str(row.get("Latest_Quotation", "")).strip(),
                "market": "Materie prime / ETC",
                "asset_class": "commodity",
            }
        )
    return records


def scan_commodity_candidates(limit=8, days=70, period="1y", universe_limit=None, verbose=True):
    rows = []
    errors = []
    universe = load_commodity_tickers()
    if universe_limit:
        universe = universe[: int(universe_limit)]
    if verbose:
        print(f"[commodity-scanner] Universo: {len(universe)} strumenti da analizzare", flush=True)

    for index, item in enumerate(universe, start=1):
        ticker = item["ticker"]
        try:
            if verbose:
                print(f"[commodity-scanner] {index}/{len(universe)} {ticker} - scarico dati e calcolo indicatori...", flush=True)
            context = generate_snapshot_context(ticker, period=period)
            snapshot = context["snapshot"]
            score, reasons, risks = score_snapshot(snapshot)
            if verbose:
                reason_preview = "; ".join(reasons[:2]) if reasons else "nessun segnale positivo forte"
                risk_preview = "; ".join(risks[:2]) if risks else "nessun rischio tecnico principale"
                print(
                    f"[commodity-scanner] {ticker} - score {score} | {reason_preview} | rischi: {risk_preview}",
                    flush=True,
                )
            rows.append(
                {
                    **item,
                    "score": score,
                    "close": snapshot["close"],
                    "change_1d_pct": snapshot["change_1d_pct"],
                    "rsi": snapshot["rsi"],
                    "macd": snapshot["macd"],
                    "macd_signal": snapshot["macd_signal"],
                    "adx": snapshot["adx"],
                    "plus_di": snapshot["plus_di"],
                    "minus_di": snapshot["minus_di"],
                    "support_10": snapshot["support_10"],
                    "resistance_10": snapshot["resistance_10"],
                    "reasons": reasons,
                    "risks": risks,
                }
            )
        except Exception as exc:
            if verbose:
                print(f"[commodity-scanner] {ticker} - errore: {exc}", flush=True)
            errors.append({"ticker": ticker, "name": item.get("name", ticker), "error": str(exc)})

    rows.sort(key=lambda item: item["score"], reverse=True)
    candidates = rows[: int(limit)]
    if verbose:
        print(f"[commodity-scanner] Scan completato: {len(rows)} ok, {len(errors)} errori", flush=True)
        for item in candidates:
            print(f"[commodity-scanner] - {item['ticker']} score {item['score']} close {item['close']}", flush=True)

    output = {
        "status": "ok",
        "universe": "COMMODITIES_ETC",
        "source_file": str(COMMODITIES_XLSX),
        "count": len(rows),
        "limit": int(limit),
        "candidates": candidates,
        "errors": errors,
    }
    out_path = PROJECT_ROOT / "output" / "stock_ai" / "commodity_scan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    output["file"] = str(out_path)
    return output


def load_commodity_tickers_json():
    return json.dumps(
        {"status": "ok", "source_file": str(COMMODITIES_XLSX), "commodities": load_commodity_tickers()},
        ensure_ascii=False,
        indent=2,
    )


def scan_commodity_candidates_json(limit=8, days=70, period="1y", universe_limit=None):
    return json.dumps(
        scan_commodity_candidates(limit=limit, days=days, period=period, universe_limit=universe_limit),
        ensure_ascii=False,
        indent=2,
    )
