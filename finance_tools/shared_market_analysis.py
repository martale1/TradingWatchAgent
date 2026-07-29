import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_registry import (
    atomic_write_json,
    list_portfolios,
    load_portfolio_config,
    load_portfolio_state,
    portfolio_runtime_path,
    portfolio_state_path,
)
from finance_tools.monitoring_rules import ensure_candidate_conditions


SHARED_ROOT = PROJECT_ROOT / "data" / "shared"
MARKET_ANALYSIS_ROOT = SHARED_ROOT / "market-analysis"
OPPORTUNITIES_ROOT = SHARED_ROOT / "opportunities"
LATEST_ANALYSIS_FILE = MARKET_ANALYSIS_ROOT / "latest.json"
LATEST_OPPORTUNITIES_FILE = OPPORTUNITIES_ROOT / "latest.json"
SCAN_FILES = {
    "ftse_mib": PROJECT_ROOT / "output" / "stock_ai" / "mib30_scan.json",
    "commodities": PROJECT_ROOT / "output" / "stock_ai" / "commodity_scan.json",
    "etf": PROJECT_ROOT / "output" / "stock_ai" / "etf_scan.json",
}
LEVERAGED_RE = re.compile(r"(?:^|[\s_-])(?:2x|3x|leveraged|short|ultra)(?:$|[\s_-])", re.IGNORECASE)


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def read_scan(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return {
        "source_file": str(path),
        "source_updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
            timespec="seconds"
        ),
        "payload": payload,
    }


def normalize_asset_class(row, market):
    value = str(row.get("asset_class") or "").strip().lower()
    if market == "commodities" or value in {"commodity", "etc", "commodity_etc"}:
        return "commodity_etc"
    if value == "etf" or market == "etf":
        return "etf"
    return "equity"


def is_leveraged(row):
    text = " ".join(
        str(row.get(key) or "") for key in ("ticker", "name", "description")
    )
    return bool(LEVERAGED_RE.search(text))


def build_shared_snapshot():
    run_id = f"shared-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    rows = []
    sources = {}
    for market, path in SCAN_FILES.items():
        scan = read_scan(path)
        if not scan:
            sources[market] = {"status": "missing", "source_file": str(path)}
            continue
        payload = scan["payload"]
        scan_rows = payload.get("scanned_rows") or payload.get("candidates") or []
        sources[market] = {
            "status": payload.get("status", "ok"),
            "source_file": scan["source_file"],
            "source_updated_at": scan["source_updated_at"],
            "count": len(scan_rows),
        }
        for item in scan_rows:
            ticker = str(item.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            rows.append(
                {
                    **item,
                    "ticker": ticker,
                    "market_key": market,
                    "asset_class": normalize_asset_class(item, market),
                    "leveraged": is_leveraged(item),
                    "shared_analysis_run_id": run_id,
                    "shared_analysis_as_of": scan["source_updated_at"],
                }
            )
    snapshot = {
        "version": 1,
        "algorithm_version": "multi-portfolio-v1",
        "run_id": run_id,
        "created_at": now_iso(),
        "sources": sources,
        "items": rows,
        "count": len(rows),
    }
    atomic_write_json(LATEST_ANALYSIS_FILE, snapshot)
    return snapshot


def open_positions_by_ticker(portfolio):
    return {
        str(item.get("ticker") or "").strip().upper(): item
        for item in portfolio.get("positions", [])
        if item.get("status") == "open" and item.get("ticker")
    }


def evaluate_item(row, config, portfolio):
    ticker = row["ticker"]
    market = row["market_key"]
    asset_class = row["asset_class"]
    score = float(row.get("score") or 0)
    turnover = float(row.get("turnover_eur") or 0)
    limits = config.get("risk_limits") or {}
    reasons = []
    blocking = []

    if market not in set(config.get("allowed_markets") or []):
        blocking.append(f"mercato {market} non ammesso")
    if asset_class not in set(config.get("allowed_asset_classes") or []):
        blocking.append(f"asset class {asset_class} non ammessa")
    if ticker in {
        str(value).strip().upper() for value in config.get("excluded_tickers") or []
    }:
        blocking.append("ticker escluso")
    sector = str(row.get("sector") or "").strip()
    excluded_sectors = {
        str(value).strip().lower() for value in config.get("excluded_sectors") or []
    }
    if sector and sector.lower() in excluded_sectors:
        blocking.append(f"settore {sector} escluso")
    if row.get("leveraged") and not config.get("allow_leveraged", False):
        blocking.append("strumento leveraged non ammesso")
    min_score = float(limits.get("min_score") or 0)
    if score < min_score:
        blocking.append(f"score {score:g} sotto soglia {min_score:g}")
    if row.get("liquidity_ok") is False:
        blocking.append("liquidita scanner insufficiente")
    min_turnover = float(limits.get("min_average_turnover") or 0)
    if turnover < min_turnover:
        blocking.append(
            f"controvalore {turnover:.0f} sotto soglia {min_turnover:.0f}"
        )

    positions = open_positions_by_ticker(portfolio)
    existing = positions.get(ticker)
    max_positions = int(limits.get("max_positions") or 0)
    if not existing and max_positions and len(positions) >= max_positions:
        blocking.append(f"numero massimo posizioni raggiunto ({max_positions})")

    action = "INCREMENT" if existing else "BUY"
    if existing:
        reasons.append("titolo gia presente: valutabile solo come incremento")
    else:
        reasons.append("nuova posizione potenziale")
    if score:
        reasons.append(f"score {score:g}")
    if turnover:
        reasons.append(f"controvalore medio {turnover:.0f}")

    return {
        "ticker": ticker,
        "market": market,
        "asset_class": asset_class,
        "score": score,
        "liquidity_ok": row.get("liquidity_ok"),
        "turnover_eur": turnover,
        "eligible": not blocking,
        "action": action if not blocking else "SKIP",
        "blocking_reasons": blocking,
        "reasons": reasons,
        "shared_analysis_run_id": row.get("shared_analysis_run_id"),
        "shared_analysis_as_of": row.get("shared_analysis_as_of"),
    }


def evaluate_snapshot_for_portfolios(snapshot=None):
    snapshot = snapshot or build_shared_snapshot()
    results = []
    for entry in list_portfolios(include_archived=False).get("items", []):
        portfolio_id = entry["id"]
        config = load_portfolio_config(portfolio_id)
        portfolio = load_portfolio_state(portfolio_id)
        if not config or not portfolio:
            results.append(
                {
                    "portfolio_id": portfolio_id,
                    "status": "error",
                    "error": "configurazione o stato portafoglio mancante",
                    "items": [],
                }
            )
            continue
        if config.get("status") != "active":
            results.append(
                {
                    "portfolio_id": portfolio_id,
                    "portfolio_name": config.get("name"),
                    "status": "skipped",
                    "reason": f"portafoglio {config.get('status')}",
                    "items": [],
                }
            )
            continue
        items = [evaluate_item(row, config, portfolio) for row in snapshot.get("items", [])]
        result = {
            "portfolio_id": portfolio_id,
            "portfolio_name": config.get("name"),
            "risk_profile": config.get("risk_profile"),
            "status": "ok",
            "eligible_count": sum(1 for item in items if item["eligible"]),
            "rejected_count": sum(1 for item in items if not item["eligible"]),
            "items": items,
        }
        results.append(result)
        runtime_path = portfolio_runtime_path(portfolio_id)
        runtime = {}
        if runtime_path.exists():
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                runtime = {}
        runtime.update(
            {
                "portfolio_id": portfolio_id,
                "updated_at": now_iso(),
                "last_shared_analysis_run_id": snapshot.get("run_id"),
                "last_shared_analysis_at": snapshot.get("created_at"),
                "last_opportunity_summary": {
                    "eligible_count": result["eligible_count"],
                    "rejected_count": result["rejected_count"],
                },
            }
        )
        atomic_write_json(runtime_path, runtime)

    payload = {
        "version": 1,
        "run_id": snapshot.get("run_id"),
        "created_at": now_iso(),
        "shared_item_count": snapshot.get("count", 0),
        "portfolios": results,
    }
    atomic_write_json(LATEST_OPPORTUNITIES_FILE, payload)
    return payload


def apply_shared_snapshot_to_portfolios(snapshot, evaluation, max_candidates_per_market=5):
    rows_by_ticker = {
        item["ticker"]: item
        for item in snapshot.get("items", [])
        if item.get("ticker")
    }
    application_results = []
    for portfolio_result in evaluation.get("portfolios", []):
        portfolio_id = portfolio_result.get("portfolio_id")
        if portfolio_result.get("status") != "ok":
            application_results.append(
                {
                    "portfolio_id": portfolio_id,
                    "status": "skipped",
                    "reason": portfolio_result.get("reason") or portfolio_result.get("error"),
                    "created_conditions": [],
                }
            )
            continue
        config = load_portfolio_config(portfolio_id) or {}
        path = portfolio_state_path(portfolio_id)
        eligible = [
            rows_by_ticker[item["ticker"]]
            for item in portfolio_result.get("items", [])
            if item.get("eligible") and item.get("ticker") in rows_by_ticker
        ]
        eligible.sort(
            key=lambda item: (
                float(item.get("score") or 0),
                float(item.get("turnover_eur") or 0),
            ),
            reverse=True,
        )
        created = []
        for market in config.get("allowed_markets") or []:
            market_rows = [
                item for item in eligible if item.get("market_key") == market
            ][: max(0, int(max_candidates_per_market))]
            if not market_rows:
                continue
            created.extend(
                ensure_candidate_conditions(
                    market_rows,
                    market=market,
                    min_score=float(
                        (config.get("risk_limits") or {}).get("min_score") or 0
                    ),
                    max_items=max_candidates_per_market,
                    path=path,
                )
            )
        application_results.append(
            {
                "portfolio_id": portfolio_id,
                "status": "ok",
                "eligible_count": len(eligible),
                "created_conditions_count": len(created),
                "created_conditions": [
                    {
                        "id": item.get("id"),
                        "ticker": item.get("ticker"),
                        "status": item.get("status"),
                    }
                    for item in created
                ],
            }
        )
    return application_results


def run_shared_portfolio_evaluation(apply_conditions=True):
    snapshot = build_shared_snapshot()
    evaluation = evaluate_snapshot_for_portfolios(snapshot)
    if apply_conditions:
        evaluation["applications"] = apply_shared_snapshot_to_portfolios(
            snapshot,
            evaluation,
        )
        atomic_write_json(LATEST_OPPORTUNITIES_FILE, evaluation)
    return evaluation


def load_latest_shared_results():
    if not LATEST_OPPORTUNITIES_FILE.exists():
        return None
    try:
        return json.loads(LATEST_OPPORTUNITIES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
