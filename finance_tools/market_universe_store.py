import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from finance_tools.common import PROJECT_ROOT


UNIVERSE_DIR = PROJECT_ROOT / "data" / "market_universes"

MARKET_ALIASES = {
    "ftse-mib": "ftse_mib",
    "ftse_mib": "ftse_mib",
    "ftsemib": "ftse_mib",
    "mib30": "ftse_mib",
    "commodities": "commodities",
    "commodity": "commodities",
    "materie_prime": "commodities",
    "materie-prime": "commodities",
    "etf": "etfs",
    "etfs": "etfs",
}

MARKET_LABELS = {
    "ftse_mib": "FTSE MIB",
    "commodities": "Materie prime",
    "etfs": "ETF",
}

TICKER_COLUMNS = ["Ticker", "ticker", "Symbol", "symbol", "Codice", "codice", "Code", "code"]
NAME_COLUMNS = ["Name", "name", "Nome", "nome", "Descrizione", "description", "Description", "Titolo", "title"]
SECTOR_COLUMNS = ["Sector", "sector", "Settore", "settore"]
INDUSTRY_COLUMNS = ["Industry", "industry", "Industria", "industria"]
LATEST_COLUMNS = ["Latest_Quotation", "latest_quotation", "Ultima quotazione", "Ultima_Quotazione"]


def normalize_market(market: str) -> str:
    key = MARKET_ALIASES.get(str(market or "").strip().lower().replace(" ", "_"))
    if not key:
        raise ValueError(f"Mercato non supportato: {market}")
    return key


def market_universe_path(market: str) -> Path:
    return UNIVERSE_DIR / f"{normalize_market(market)}.json"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _first_value(row: dict, columns: list[str], default=""):
    for column in columns:
        value = row.get(column)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _normalize_row(row: dict, market: str, active=True) -> dict | None:
    ticker = _first_value(row, TICKER_COLUMNS)
    if not ticker:
        values = [str(value).strip() for value in row.values() if str(value).strip()]
        ticker = values[0] if values else ""
    ticker = ticker.upper()
    if not ticker:
        return None

    name = _first_value(row, NAME_COLUMNS, ticker)
    item = {
        "ticker": ticker,
        "name": name or ticker,
        "description": _first_value(row, ["description", "Description", "Descrizione"], ""),
        "sector": _first_value(row, SECTOR_COLUMNS, ""),
        "industry": _first_value(row, INDUSTRY_COLUMNS, ""),
        "latest_quotation": _first_value(row, LATEST_COLUMNS, ""),
        "market": MARKET_LABELS.get(normalize_market(market), market),
        "asset_class": "commodity" if normalize_market(market) == "commodities" else ("etf" if normalize_market(market) == "etfs" else "equity"),
        "active": bool(active),
        "updated_at": _now(),
    }
    for key, value in row.items():
        if key not in item and value is not None and str(value).strip():
            item[str(key)] = str(value).strip()
    return item


def _read_payload(market: str) -> dict | None:
    path = market_universe_path(market)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_payload(market: str, rows: list[dict]) -> dict:
    key = normalize_market(market)
    UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "market": key,
        "label": MARKET_LABELS[key],
        "updated_at": _now(),
        "items": sorted(rows, key=lambda item: str(item.get("ticker", ""))),
    }
    market_universe_path(key).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def load_market_universe(market: str, fallback_rows: list[dict] | None = None, include_inactive=False) -> list[dict]:
    payload = _read_payload(market)
    if payload:
        rows = [dict(item) for item in payload.get("items", []) if item.get("ticker")]
    else:
        rows = []
        for row in fallback_rows or []:
            normalized = _normalize_row(dict(row), market, active=True)
            if normalized:
                rows.append(normalized)
    if include_inactive:
        return rows
    return [item for item in rows if item.get("active", True) is not False]


def list_market_universe(market: str, fallback_rows: list[dict] | None = None) -> dict:
    key = normalize_market(market)
    rows = load_market_universe(key, fallback_rows=fallback_rows, include_inactive=True)
    active_count = sum(1 for item in rows if item.get("active", True) is not False)
    return {
        "status": "ok",
        "market": key,
        "label": MARKET_LABELS[key],
        "count": len(rows),
        "active_count": active_count,
        "items": rows,
        "configured": _read_payload(key) is not None,
    }


def save_market_universe(market: str, rows: list[dict]) -> dict:
    key = normalize_market(market)
    normalized_rows = []
    seen = set()
    for row in rows:
        normalized = _normalize_row(dict(row), key, active=row.get("active", True))
        if normalized and normalized["ticker"] not in seen:
            seen.add(normalized["ticker"])
            normalized_rows.append(normalized)
    return _write_payload(key, normalized_rows)


def add_market_instrument(market: str, item: dict) -> dict:
    key = normalize_market(market)
    rows = load_market_universe(key, include_inactive=True)
    normalized = _normalize_row(item, key, active=item.get("active", True))
    if not normalized:
        raise ValueError("Ticker non valido")
    updated = False
    for index, row in enumerate(rows):
        if str(row.get("ticker", "")).upper() == normalized["ticker"]:
            rows[index] = {**row, **normalized, "updated_at": _now()}
            updated = True
            break
    if not updated:
        rows.append(normalized)
    payload = _write_payload(key, rows)
    return {"status": "ok", "item": normalized, "market": key, "count": len(payload["items"])}


def update_market_instrument(market: str, ticker: str, changes: dict) -> dict:
    key = normalize_market(market)
    rows = load_market_universe(key, include_inactive=True)
    target = str(ticker or "").strip().upper()
    for index, row in enumerate(rows):
        if str(row.get("ticker", "")).upper() == target:
            clean_changes = {key_: value for key_, value in changes.items() if value is not None}
            rows[index] = {**row, **clean_changes, "ticker": target, "updated_at": _now()}
            _write_payload(key, rows)
            return {"status": "ok", "item": rows[index]}
    raise ValueError(f"Ticker non trovato: {ticker}")


def remove_market_instrument(market: str, ticker: str) -> dict:
    key = normalize_market(market)
    target = str(ticker or "").strip().upper()
    rows = load_market_universe(key, include_inactive=True)
    next_rows = [row for row in rows if str(row.get("ticker", "")).upper() != target]
    if len(next_rows) == len(rows):
        raise ValueError(f"Ticker non trovato: {ticker}")
    _write_payload(key, next_rows)
    return {"status": "ok", "removed": target, "count": len(next_rows)}


def read_excel_universe(path: str | Path, market: str, active=False) -> list[dict]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File Excel non trovato: {file_path}")
    df = pd.read_excel(file_path)
    rows = []
    for raw in df.fillna("").to_dict(orient="records"):
        normalized = _normalize_row(raw, market, active=active)
        if normalized:
            normalized["source_file"] = str(file_path)
            rows.append(normalized)
    return rows


def import_market_universe_from_excel(market: str, path: str | Path, replace=False, activate=False) -> dict:
    key = normalize_market(market)
    imported = read_excel_universe(path, key, active=activate)
    current = [] if replace else load_market_universe(key, include_inactive=True)
    by_ticker = {str(item.get("ticker", "")).upper(): dict(item) for item in current if item.get("ticker")}
    for item in imported:
        ticker = item["ticker"]
        by_ticker[ticker] = {**by_ticker.get(ticker, {}), **item, "updated_at": _now()}
    payload = _write_payload(key, list(by_ticker.values()))
    return {
        "status": "ok",
        "market": key,
        "imported": len(imported),
        "count": len(payload["items"]),
        "active_count": sum(1 for item in payload["items"] if item.get("active", True) is not False),
        "items": payload["items"],
    }
