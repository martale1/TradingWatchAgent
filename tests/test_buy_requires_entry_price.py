import json

from finance_tools.portfolio_store import confirm_proposal


def test_confirm_buy_blocks_missing_entry_price(tmp_path):
    path = tmp_path / "portfolio.json"
    path.write_text(
        json.dumps(
            {
                "portfolio_id": "test",
                "initial_capital": 10000,
                "cash": 10000,
                "positions": [],
                "pending_proposals": [
                    {
                        "id": "buy-1",
                        "action": "buy_virtual_position",
                        "ticker": "SBUL.MI",
                        "status": "pending",
                        "metadata": {"amount": 1200, "entry_price": None},
                    }
                ],
                "closed_proposals": [],
            }
        ),
        encoding="utf-8",
    )

    result = confirm_proposal("buy-1", path=path)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert result["status"] == "blocked"
    assert saved["cash"] == 10000
    assert saved["positions"] == []
    assert saved["closed_proposals"][0]["failure_reason"] == "prezzo di ingresso mancante o non valido"
