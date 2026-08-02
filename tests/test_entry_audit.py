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
    assert audit["audit_type"] == "monitored_condition"


def test_entry_audit_recovers_legacy_condition_by_evaluation_time():
    position = {"ticker": "CRUD.MI", "entry_price": 12.464, "opened_at": "2026-07-30T16:34:34"}
    portfolio = {
        "closed_proposals": [{
            "id": "legacy-proposal",
            "ticker": "CRUD.MI",
            "action": "buy_virtual_position",
            "status": "confirmed",
            "confirmed_at": "2026-07-30T16:34:34",
            "reason": "BUY_CANDIDATE confermato",
            "metadata": {"entry_price": 12.464, "risk_validation": {"allowed": True, "amount": 689.06}},
        }],
        "monitored_conditions": [{
            "id": "legacy-condition",
            "ticker": "CRUD.MI",
            "condition": "Pullback 12.178-12.48245",
            "metadata": {
                "last_entry_scenario_eval_at": "2026-07-30T16:34:20",
                "last_price": 12.464,
                "volume_ratio": 1.073,
                "intraday_volume_pace_ratio": 1.209,
                "daily_bar_complete": False,
                "entry_scenarios": [{
                    "type": "PULLBACK_SUPPORTO",
                    "state": "BUY_CANDIDATE",
                    "entry_area_min": 12.178,
                    "entry_area_max": 12.48245,
                    "support": 12.178,
                    "required_volume_ratio": 0.8,
                    "playwright_confirmed": True,
                    "news_negative": False,
                }],
            },
        }],
    }

    audit = build_entry_audit(portfolio, "CRUD.MI", position)

    assert audit["condition_id"] == "legacy-condition"
    assert audit["checks"][0]["status"] == "passed"
    assert audit["checks"][1]["status"] == "passed"
    assert audit["checks"][2]["status"] == "missing"
    assert audit["legacy_warning"]
    assert audit["audit_type"] == "monitored_condition"


def test_entry_audit_uses_standardized_snapshot_without_reconstruction():
    snapshot = {
        "schema_version": 1,
        "captured_at": "2026-08-02T10:00:00",
        "decision_kind": "langgraph_automatic",
        "score": 8.2,
        "reasons": ["trend positivo", "liquidita sufficiente"],
        "risks": ["volatilita moderata"],
        "liquidity_ok": True,
        "chart_entry_confirmed": True,
        "risk_validation": {"allowed": True, "amount": 500},
        "audit_complete": True,
    }
    position = {
        "ticker": "ENI.MI",
        "entry_price": 23.9,
        "opened_at": "2026-08-02T10:00:01",
        "entry_audit_snapshot": snapshot,
    }

    audit = build_entry_audit({"positions": [position]}, "ENI.MI", position)

    assert audit["audit_type"] == "standardized_snapshot"
    assert audit["decision_kind"] == "langgraph_automatic"
    assert audit["score"] == 8.2
    assert audit["reasons"] == snapshot["reasons"]
    assert [item["status"] for item in audit["checks"]] == ["passed", "passed", "passed", "passed"]
