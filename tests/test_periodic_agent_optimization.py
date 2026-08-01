from agent_portfolio_manager import (
    build_agent,
    build_periodic_monitor_request,
)


def test_periodic_agent_uses_a_reduced_tool_set():
    agent = build_agent(
        model="gpt-5-mini",
        auto_apply_virtual=True,
        periodic=True,
    )
    tool_names = {tool.name for tool in agent.tools}

    assert len(tool_names) <= 14
    assert "load_virtual_portfolio" not in tool_names
    assert "analyze_portfolio_positions_deep" not in tool_names
    assert "send_monitoring_telegram_summary" not in tool_names
    assert "get_portfolio_operating_status" in tool_names
    assert "evaluate_entry_scenarios" in tool_names
    assert "auto_apply_virtual_proposal_tool" in tool_names


def test_periodic_prompt_bounds_position_analysis():
    request = build_periodic_monitor_request(
        live_news=True,
        auto_apply_virtual=True,
        run_market_scanners=False,
    )

    assert "massimo tre posizioni" in request
    assert "Non analizzare tutte le posizioni" in request
    assert "Non chiamare tool Telegram" in request
    assert len(request) < 2500
