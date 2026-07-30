from unittest.mock import patch

from finance_tools import playwright_health


def test_failure_is_notified_once_and_recovery_is_notified(tmp_path):
    state_file = tmp_path / "playwright_health.json"

    with (
        patch.object(playwright_health, "STATE_FILE", state_file),
        patch.object(
            playwright_health,
            "_send_alert",
            return_value={"status": "success"},
        ) as send_alert,
    ):
        first = playwright_health.record_playwright_failure(
            "chart", "CDP timeout", ticker="VOD.L", portfolio_id="dinamico-10k"
        )
        second = playwright_health.record_playwright_failure(
            "chart", "CDP timeout", ticker="VOD.L", portfolio_id="dinamico-10k"
        )
        recovered = playwright_health.record_playwright_success(
            "chart", ticker="VOD.L", portfolio_id="dinamico-10k"
        )

    assert first["status"] == "error"
    assert second["status"] == "error"
    assert recovered["status"] == "ok"
    assert send_alert.call_count == 2
    assert "dinamico-10k" in send_alert.call_args_list[0].args[0]
    assert "ripristinato" in send_alert.call_args_list[1].args[0]


def test_default_portfolio_comes_from_environment(tmp_path, monkeypatch):
    state_file = tmp_path / "playwright_health.json"
    monkeypatch.setenv("ACTIVE_PORTFOLIO_ID", "prudente")

    with (
        patch.object(playwright_health, "STATE_FILE", state_file),
        patch.object(
            playwright_health,
            "_send_alert",
            return_value={"status": "success"},
        ),
    ):
        state = playwright_health.record_playwright_failure("news", "timeout")

    assert state["portfolio_id"] == "prudente"
