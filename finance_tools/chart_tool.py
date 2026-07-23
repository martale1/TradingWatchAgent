import json
from pathlib import Path

from finance_charts.technical_charts import create_chart_bundle
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
    output_dir = PROJECT_ROOT / "output" / "stock_ai" / ticker.replace("/", "_")
    bundle = create_chart_bundle(ticker, output_dir, period=period, days=days)
    result = {
        "ticker": ticker,
        "status": "ok",
        "days": days,
        "period": period,
        "snapshot": _round_floats(bundle["snapshot"]),
        "files": [str(Path(path)) for path in bundle["files"]],
    }
    return result


def generate_chart_context_json(ticker, days=70, period="1y"):
    return json.dumps(generate_chart_context(ticker, days, period), ensure_ascii=False, indent=2)

