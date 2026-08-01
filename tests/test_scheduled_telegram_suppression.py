from agent_portfolio_manager import scheduled_telegram_tools_suppressed


def test_scheduled_run_suppresses_intermediate_telegram_tools(monkeypatch):
    monkeypatch.setenv("SUPPRESS_AGENT_TELEGRAM_TOOLS", "1")

    assert scheduled_telegram_tools_suppressed() is True


def test_interactive_run_keeps_telegram_tools_enabled(monkeypatch):
    monkeypatch.delenv("SUPPRESS_AGENT_TELEGRAM_TOOLS", raising=False)

    assert scheduled_telegram_tools_suppressed() is False
