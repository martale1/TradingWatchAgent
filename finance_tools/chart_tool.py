import json
from pathlib import Path

from finance_charts.technical_charts import create_chart_bundle, create_snapshot_bundle
from finance_tools.common import PROJECT_ROOT


def _round_floats(value):
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _round_floats(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_floats(item) for item in value]
    return value


def generate_chart_context(ticker, days=70, period="1y"):
    print(f"[chart-tool] {ticker} - preparo cartella output e scarico dati Yahoo Finance", flush=True)
    output_dir = PROJECT_ROOT / "output" / "stock_ai" / ticker.replace("/", "_")
    print(f"[chart-tool] {ticker} - genero grafici tecnici | days={days} period={period}", flush=True)
    bundle = create_chart_bundle(ticker, output_dir, period=period, days=days)
    print(f"[chart-tool] {ticker} - grafici creati: {len(bundle['files'])}", flush=True)
    result = {
        "ticker": ticker,
        "status": "ok",
        "days": days,
        "period": period,
        "snapshot": _round_floats(bundle["snapshot"]),
        "files": [str(Path(path)) for path in bundle["files"]],
    }
    print(f"[chart-tool] {ticker} - snapshot tecnico pronto", flush=True)
    return result


def generate_snapshot_context(ticker, period="1y"):
    print(f"[chart-tool] {ticker} - scarico dati Yahoo Finance e calcolo indicatori", flush=True)
    bundle = create_snapshot_bundle(ticker, period=period)
    result = {
        "ticker": ticker,
        "status": "ok",
        "period": period,
        "snapshot": _round_floats(bundle["snapshot"]),
        "files": [],
    }
    print(f"[chart-tool] {ticker} - snapshot tecnico pronto senza grafici", flush=True)
    return result


def generate_chart_context_json(ticker, days=70, period="1y"):
    return json.dumps(generate_chart_context(ticker, days, period), ensure_ascii=False, indent=2)
