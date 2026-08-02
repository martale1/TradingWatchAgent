import json

from finance_tools.portfolio_store import add_position_action_proposal, confirm_proposal


def _portfolio(path):
    path.write_text(
        json.dumps(
            {
                "portfolio_id": "action-audit",
                "initial_capital": 1000,
                "cash": 500,
                "positions": [
                    {
                        "ticker": "ENI.MI",
                        "status": "open",
                        "entry_price": 20,
                        "virtual_quantity": 25,
                        "allocated_amount": 500,
                    }
                ],
                "pending_proposals": [],
                "closed_proposals": [],
            }
        ),
        encoding="utf-8",
    )


def test_automatic_exit_without_complete_evidence_is_blocked(tmp_path):
    path = tmp_path / "portfolio.json"
    _portfolio(path)
    proposal = add_position_action_proposal(
        "ENI.MI",
        "sell",
        "Stop dichiarato ma prove incomplete",
        reference_price=19,
        metadata={"source": "deterministic_exit_stop"},
        path=path,
    )

    result = confirm_proposal(proposal["id"], path=path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert saved["positions"][0]["status"] == "open"
    assert saved["closed_proposals"][0]["failure_reason"] == "snapshot audit azione automatica mancante o incompleto"


def test_new_automatic_source_cannot_bypass_audit_guard(tmp_path):
    path = tmp_path / "portfolio.json"
    _portfolio(path)
    proposal = add_position_action_proposal(
        "ENI.MI",
        "reduce",
        "Nuovo motore senza dossier",
        percent=30,
        reference_price=21,
        metadata={"source": "future_engine_not_yet_known"},
        path=path,
    )

    result = confirm_proposal(proposal["id"], path=path, confirmation_context="automatic")

    assert result["status"] == "blocked"
    assert result["reason"] == "snapshot audit azione automatica mancante o incompleto"


def test_complete_exit_evidence_is_preserved_on_execution(tmp_path):
    path = tmp_path / "portfolio.json"
    _portfolio(path)
    snapshot = {
        "schema_version": 1,
        "captured_at": "2026-08-02T10:00:00",
        "decision_kind": "deterministic_trigger",
        "source": "deterministic_exit_stop",
        "action": "sell_all",
        "percent": 100,
        "trigger_type": "hard_stop",
        "trigger_level": 19.5,
        "observed_price": 19,
        "comparison": "price_lte_trigger",
        "condition_met": True,
        "rule": "19 <= 19.5",
        "audit_complete": True,
    }
    proposal = add_position_action_proposal(
        "ENI.MI",
        "sell",
        "Stop verificato",
        reference_price=19,
        metadata={
            "source": "deterministic_exit_stop",
            "trigger_level": 19.5,
            "action_audit_snapshot": snapshot,
        },
        path=path,
    )

    result = confirm_proposal(proposal["id"], path=path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert result["status"] == "ok"
    assert saved["positions"][0]["status"] == "closed"
    assert saved["closed_proposals"][0]["metadata"]["action_audit_snapshot"] == snapshot
