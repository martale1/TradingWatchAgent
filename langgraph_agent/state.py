from typing import Any, TypedDict


class TradingGraphState(TypedDict, total=False):
    """Shared state passed across the LangGraph workflow."""

    run_id: str
    request: str
    mode: str
    scan_limit: int
    universe_limit: int | None
    apply_virtual: bool
    use_playwright: bool
    max_auto_trade_pct: float
    portfolio: dict[str, Any]
    performance: dict[str, Any]
    ftse_mib_scan: dict[str, Any]
    commodity_scan: dict[str, Any]
    etf_scan: dict[str, Any]
    shortlist: list[dict[str, Any]]
    deep_analysis_plan: list[dict[str, Any]]
    deep_analysis_results: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    applied_actions: list[dict[str, Any]]
    created_proposals: list[dict[str, Any]]
    logs: list[str]
    errors: list[str]
    final_summary: str
