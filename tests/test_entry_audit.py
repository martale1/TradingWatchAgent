from finance_tools.exit_view import build_entry_audit


def test_entry_audit_links_position_proposal_and_condition():
    position = {
        "ticker": "SBUL.MI",
        "entry_price": 7.353,
        "opened_at": "2026-07-30T14:37:19",
        "source": "confirmed_agent_buy_proposal",
    }
    portfolio = {
        "positions": [position],
        "closed_proposals": [
            {
                "id": "proposal-1",
                "ticker": "SBUL.MI",
                "action": "buy_virtual_position",
                "status": "confirmed",
                "confirmed_at": "2026-07-30T14:37:19",
                "reason": "BUY da condizione condition-1",
                "metadata": {
                    "entry_price": 7.353,
                    "risk_validation": {"allowed": True, "amount": 474.45},
                },
            }
        ],
        "monitored_conditions": [
            {
                "id": "condition-1",
                "condition": "Pullback sul supporto 7.219",
                "metadata": {
                    "auto_proposal_id": "proposal-1",
                    "last_price": 7.353,
                    "volume_ratio": 0.2869,
                    "entry_scenarios": [
                        {
                            "type": "PULLBACK_SUPPORTO",
                            "state": "BUY_CANDIDATE",
                            "support": 7.219,
                            "trigger": 7.399475,
                            "required_volume_ratio": 0.8,
                        }
                    ],
                },
            }
        ],
    }

    audit = build_entry_audit(portfolio, "SBUL.MI", position)

    assert audit["proposal_id"] == "proposal-1"
    assert audit["condition_id"] == "condition-1"
    assert audit["scenario_type"] == "PULLBACK_SUPPORTO"
    assert audit["support"] == 7.219
    assert audit["risk_allowed"] is True
