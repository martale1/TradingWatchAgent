from typing import Any, TypedDict


class TradingGraphState(TypedDict, total=False):
    """Shared state passed across the LangGraph workflow."""

    request: str
    mode: str
    scan_limit: int
    universe_limit: int | None
    portfolio: dict[str, Any]
    performance: dict[str, Any]
    ftse_mib_scan: dict[str, Any]
    commodity_scan: dict[str, Any]
    shortlist: list[dict[str, Any]]
    deep_analysis_plan: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    logs: list[str]
    errors: list[str]
    final_summary: str

