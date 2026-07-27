import json
from datetime import datetime

from finance_tools.chart_tool import generate_snapshot_context
from finance_tools.common import PROJECT_ROOT
from finance_tools.liquidity import apply_liquidity_to_score
from finance_tools.market_universe_store import load_market_universe
from finance_tools.mib30_scanner import score_snapshot


ETF_UNIVERSE = [
    {
        "ticker": "ROBO.MI",
        "name": "Robotics and Automation",
        "description": "Robotics and Automation",
        "market": "ETF",
        "asset_class": "etf",
    }
]


def load_etf_tickers():
    return load_market_universe("etfs", fallback_rows=[dict(item) for item in ETF_UNIVERSE])


def scan_etf_candidates(limit=8, days=70, period="1y", universe_limit=None, verbose=True):
    rows = []
    errors = []
    universe = load_etf_tickers()
    if universe_limit:
        universe = universe[: int(universe_limit)]
    if verbose:
        print(f"[etf-scanner] Universo: {len(universe)} ETF da analizzare", flush=True)

    for index, item in enumerate(universe, start=1):
        ticker = item["ticker"]
        try:
            if verbose:
                print(f"[etf-scanner] {index}/{len(universe)} {ticker} - scarico dati e calcolo indicatori...", flush=True)
            context = generate_snapshot_context(ticker, period=period)
            read_at = datetime.now().isoformat(timespec="seconds")
            snapshot = context["snapshot"]
            score, reasons, risks = score_snapshot(snapshot)
            score, liquidity = apply_liquidity_to_score(score, risks, snapshot, asset_class="etf")
            if verbose:
                reason_preview = "; ".join(reasons[:2]) if reasons else "nessun segnale positivo forte"
                risk_preview = "; ".join(risks[:2]) if risks else "nessun rischio tecnico principale"
                print(
                    f"[etf-scanner] {ticker} - score {score} | {reason_preview} | rischi: {risk_preview}",
                    flush=True,
                )
            rows.append(
                {
                    **item,
                    "score": score,
                    "last_yfinance_read_at": read_at,
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
                    "volume": snapshot["volume"],
                    "volume_ma5": snapshot["volume_ma5"],
                    "volume_ma10": snapshot["volume_ma10"],
                    **liquidity,
                    "reasons": reasons,
                    "risks": risks,
                }
            )
        except Exception as exc:
            if verbose:
                print(f"[etf-scanner] {ticker} - errore: {exc}", flush=True)
            errors.append({"ticker": ticker, "name": item.get("name", ticker), "error": str(exc)})

    rows.sort(key=lambda item: item["score"], reverse=True)
    liquid_rows = [item for item in rows if item.get("liquidity_ok") is not False]
    low_liquidity_rows = [item for item in rows if item.get("liquidity_ok") is False]
    candidates = liquid_rows[: int(limit)]
    if verbose:
        print(f"[etf-scanner] Scan completato: {len(rows)} ok, {len(errors)} errori", flush=True)
        print(
            "[etf-scanner] Selezione candidati ETF: ordino per score tecnico e applico filtro hard liquidita. "
            "Gli strumenti con liquidita bassa restano nello scan ma sono esclusi dai candidati operativi.",
            flush=True,
        )
        print("[etf-scanner] Migliori candidati ETF e motivo:", flush=True)
        for rank, item in enumerate(candidates, start=1):
            reason_preview = "; ".join(item.get("reasons", [])[:4]) or "nessun segnale positivo forte"
            risk_preview = "; ".join(item.get("risks", [])[:3]) or "nessun rischio tecnico principale"
            liquidity_status = "liquidita ok" if item.get("liquidity_ok") else "liquidita bassa/da evitare"
            print(
                f"[etf-scanner] #{rank} {item['ticker']} scelto per short-list | "
                f"score={item['score']} close={item['close']} oggi={item.get('change_1d_pct')}% | "
                f"motivi={reason_preview} | rischi={risk_preview} | {liquidity_status}",
                flush=True,
            )

    output = {
        "status": "ok",
        "universe": "ETF",
        "count": len(rows),
        "limit": int(limit),
        "scanned_rows": rows,
        "candidates": candidates,
        "excluded_low_liquidity": low_liquidity_rows,
        "errors": errors,
    }
    out_path = PROJECT_ROOT / "output" / "stock_ai" / "etf_scan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    output["file"] = str(out_path)
    return output


def load_etf_tickers_json():
    return json.dumps(
        {"status": "ok", "etfs": load_etf_tickers()},
        ensure_ascii=False,
        indent=2,
    )


def scan_etf_candidates_json(limit=8, days=70, period="1y", universe_limit=None):
    return json.dumps(
        scan_etf_candidates(limit=limit, days=days, period=period, universe_limit=universe_limit),
        ensure_ascii=False,
        indent=2,
    )
