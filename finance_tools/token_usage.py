import json
from datetime import datetime

from finance_tools.common import PROJECT_ROOT


TOKEN_USAGE_FILE = PROJECT_ROOT / "output" / "openai_token_usage.json"


def _empty_store():
    return {"events": []}


def load_token_usage_store():
    if not TOKEN_USAGE_FILE.exists():
        return _empty_store()
    try:
        data = json.loads(TOKEN_USAGE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _empty_store()
    except (OSError, json.JSONDecodeError):
        return _empty_store()


def record_token_usage(usage, model="", mode="", label=""):
    if usage is None:
        return None
    event = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "date": datetime.now().date().isoformat(),
        "model": str(model or ""),
        "mode": str(mode or ""),
        "label": str(label or "")[:180],
        "requests": int(getattr(usage, "requests", 0) or 0),
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "cached_input_tokens": int(
            getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        ),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "reasoning_tokens": int(
            getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0
        ),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
    if not any(event[key] for key in ("requests", "input_tokens", "output_tokens", "total_tokens")):
        return None
    store = load_token_usage_store()
    store.setdefault("events", []).append(event)
    store["events"] = store["events"][-2000:]
    TOKEN_USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_USAGE_FILE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    return event


def token_usage_summary(days=14):
    events = load_token_usage_store().get("events") or []
    grouped = {}
    for event in events:
        day = str(event.get("date") or "")
        if not day:
            continue
        row = grouped.setdefault(
            day,
            {
                "date": day,
                "runs": 0,
                "requests": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                "models": {},
            },
        )
        row["runs"] += 1
        for key in (
            "requests",
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            row[key] += int(event.get(key) or 0)
        model = str(event.get("model") or "n/d")
        row["models"][model] = row["models"].get(model, 0) + int(event.get("total_tokens") or 0)

    daily = sorted(grouped.values(), key=lambda item: item["date"], reverse=True)[: max(1, int(days))]
    today_key = datetime.now().date().isoformat()
    today = grouped.get(
        today_key,
        {
            "date": today_key,
            "runs": 0,
            "requests": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
            "models": {},
        },
    )
    return {
        "today": today,
        "daily": daily,
        "last_event": events[-1] if events else None,
        "tracking_started_at": events[0].get("timestamp") if events else None,
        "file": str(TOKEN_USAGE_FILE),
    }
