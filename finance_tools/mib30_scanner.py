import json
from pathlib import Path

import pandas as pd

from finance_tools.chart_tool import generate_chart_context
from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_store import add_allocation_proposal, add_proposal


MIB30_XLSX = PROJECT_ROOT / "validTickers" / "validtickers_IT_MIB30_with_sector.xlsx"


def load_mib30_tickers(path=MIB30_XLSX):
    df = pd.read_excel(path)
    records = []
    for row in df.fillna("").to_dict(orient="records"):
        ticker = str(row.get("Ticker", "")).strip().upper()
        if ticker:
            records.append(
                {
                    "ticker": ticker,
                    "name": str(row.get("Name", ticker)).strip(),
                    "sector": str(row.get("Sector", "")).strip(),
                    "industry": str(row.get("Industry", "")).strip(),
                }
            )
    return records


def score_snapshot(snapshot):
    score = 0
    reasons = []
    risks = []

    if snapshot["macd"] > snapshot["macd_signal"]:
        score += 2
        reasons.append("MACD sopra signal")
    else:
        risks.append("MACD non conferma")

    if snapshot["plus_di"] > snapshot["minus_di"] and snapshot["adx"] >= 20:
        score += 2
        reasons.append("DI+ sopra DI- con ADX >= 20")
    elif snapshot["adx"] < 20:
        risks.append("trend debole ADX < 20")

    if 45 <= snapshot["rsi"] <= 68:
        score += 2
        reasons.append("RSI costruttivo non eccessivo")
    elif snapshot["rsi"] > 72:
        score -= 1
        risks.append("RSI in ipercomprato")
    elif snapshot["rsi"] < 40:
        score -= 1
        risks.append("RSI debole")

    if snapshot["stoch_k"] > snapshot["stoch_d"] and snapshot["stoch_k"] < 85:
        score += 1
        reasons.append("Stocastico positivo")

    if snapshot["volume"] > snapshot["volume_ma10"]:
        score += 1
        reasons.append("volume sopra MA10")
    else:
        risks.append("volume sotto MA10")

    if 0 <= snapshot["resistance_10_dist_pct"] <= 6:
        score += 1
        reasons.append("resistenza breve vicina")

    if -5 <= snapshot["support_10_dist_pct"] <= 0:
        score += 1
        reasons.append("supporto breve vicino")

    return score, reasons, risks


def scan_mib30_candidates(limit=5, days=70, period="1y", create_proposals=False):
    rows = []
    errors = []
    for item in load_mib30_tickers():
        ticker = item["ticker"]
        try:
            context = generate_chart_context(ticker, days=days, period=period)
            snapshot = context["snapshot"]
            score, reasons, risks = score_snapshot(snapshot)
            rows.append(
                {
                    **item,
                    "score": score,
                    "close": snapshot["close"],
                    "change_1d_pct": snapshot["change_1d_pct"],
                    "rsi": snapshot["rsi"],
                    "macd": snapshot["macd"],
                    "macd_signal": snapshot["macd_signal"],
                    "adx": snapshot["adx"],
                    "plus_di": snapshot["plus_di"],
                    "minus_di": snapshot["minus_di"],
                    "support_10": snapshot["support_10"],
                    "resistance_10": snapshot["resistance_10"],
                    "reasons": reasons,
                    "risks": risks,
                    "files": context["files"],
                }
            )
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})

    rows.sort(key=lambda item: item["score"], reverse=True)
    candidates = rows[: int(limit)]

    proposals = []
    if create_proposals:
        for item in candidates:
            if item["score"] <= 0:
                continue
            reason = "; ".join(item["reasons"]) or "Titolo emerso dallo scanner MIB30"
            proposals.append(
                add_proposal(
                    action="add_to_watchlist",
                    ticker=item["ticker"],
                    reason=reason,
                    metadata={
                        "name": item["name"],
                        "market": "Borsa Italiana",
                        "sector": item["sector"],
                        "score": item["score"],
                        "risks": item["risks"],
                    },
                )
            )

    output = {
        "status": "ok",
        "universe": "IT_MIB30",
        "count": len(rows),
        "limit": int(limit),
        "candidates": candidates,
        "errors": errors,
        "proposals_created": proposals,
    }
    out_path = PROJECT_ROOT / "output" / "stock_ai" / "mib30_scan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    output["file"] = str(out_path)
    return output


def scan_mib30_candidates_json(limit=5, days=70, period="1y", create_proposals=False):
    return json.dumps(
        scan_mib30_candidates(limit=limit, days=days, period=period, create_proposals=create_proposals),
        ensure_ascii=False,
        indent=2,
    )


def propose_virtual_allocation(capital, max_positions=5, cash_pct=15, days=70, period="1y"):
    scan = scan_mib30_candidates(limit=max_positions, days=days, period=period, create_proposals=False)
    candidates = [item for item in scan["candidates"] if item["score"] > 0]
    if not candidates:
        return {
            "status": "no_candidates",
            "message": "Nessun candidato con score positivo.",
            "scan": scan,
        }

    investable_pct = max(0, min(100, 100 - float(cash_pct)))
    investable_amount = float(capital) * investable_pct / 100.0
    total_score = sum(max(1, item["score"]) for item in candidates)
    allocations = []
    allocated_total = 0.0

    for item in candidates:
        weight = max(1, item["score"]) / total_score
        amount = round(investable_amount * weight, 2)
        allocated_total += amount
        close = float(item["close"])
        quantity = round(amount / close, 4) if close > 0 else 0
        allocation_pct = round(amount / float(capital) * 100, 2)
        allocations.append(
            {
                "ticker": item["ticker"],
                "name": item["name"],
                "market": "Borsa Italiana",
                "sector": item["sector"],
                "score": item["score"],
                "allocation_pct": allocation_pct,
                "allocated_amount": amount,
                "entry_price": close,
                "virtual_quantity": quantity,
                "reason": "; ".join(item["reasons"]),
                "risks": item["risks"],
            }
        )

    reason = (
        f"Allocazione virtuale proposta da scanner MIB30: {len(allocations)} titoli, "
        f"{investable_pct:.1f}% investito e {float(cash_pct):.1f}% cash."
    )
    proposal = add_allocation_proposal(
        capital=float(capital),
        allocations=allocations,
        reason=reason,
        metadata={
            "cash_pct": float(cash_pct),
            "cash_amount": round(float(capital) - allocated_total, 2),
            "scan_file": scan.get("file"),
            "errors": scan.get("errors", []),
        },
    )
    return {
        "status": "ok",
        "proposal": proposal,
        "allocations": allocations,
        "cash_amount": round(float(capital) - allocated_total, 2),
        "scan": scan,
    }


def propose_virtual_allocation_json(capital, max_positions=5, cash_pct=15, days=70, period="1y"):
    return json.dumps(
        propose_virtual_allocation(
            capital=capital,
            max_positions=max_positions,
            cash_pct=cash_pct,
            days=days,
            period=period,
        ),
        ensure_ascii=False,
        indent=2,
    )
