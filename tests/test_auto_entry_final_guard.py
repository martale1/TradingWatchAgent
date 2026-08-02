from agent_portfolio_manager import _confirmed_entry_guard


def sbul_condition(chart_entry_confirmed=False):
    return {
        "ticker": "SBUL.MI",
        "metadata": {
            "scenario_state": "BUY_CANDIDATE",
            "last_price": 7.353,
            "volume_ratio": 0.2869234720082178,
            "intraday_volume_pace_ratio": 0.8066445656683097,
            "daily_bar_complete": False,
            "entry_scenarios": [
                {
                    "type": "PULLBACK_SUPPORTO",
                    "state": "BUY_CANDIDATE",
                    "support": 7.219,
                    "entry_area_max": 7.399475,
                    "trigger": 7.399475,
                    "required_volume_ratio": 0.8,
                    "chart_entry_confirmed": chart_entry_confirmed,
                }
            ],
        },
    }


def test_sbul_record_is_blocked_without_explicit_chart_confirmation():
    allowed, reason = _confirmed_entry_guard(sbul_condition(False))

    assert allowed is False
    assert "conferma operativa del grafico assente" in reason


def test_confirmed_pullback_passes_final_guard():
    allowed, reason = _confirmed_entry_guard(sbul_condition(True))

    assert allowed is True
    assert "confermato" in reason
