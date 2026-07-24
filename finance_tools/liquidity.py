import os


MIN_EQUITY_AVG_VOLUME = float(os.getenv("MIN_EQUITY_AVG_VOLUME", "100000"))
MIN_COMMODITY_AVG_VOLUME = float(os.getenv("MIN_COMMODITY_AVG_VOLUME", "5000"))
MIN_LIQUIDITY_TURNOVER_EUR = float(os.getenv("MIN_LIQUIDITY_TURNOVER_EUR", "100000"))


def liquidity_metrics(snapshot, asset_class="equity"):
    volume = float(snapshot.get("volume") or 0)
    volume_ma5 = float(snapshot.get("volume_ma5") or 0)
    volume_ma10 = float(snapshot.get("volume_ma10") or 0)
    close = float(snapshot.get("close") or 0)
    avg_volume = volume_ma10 or volume_ma5 or volume
    turnover = avg_volume * close
    min_avg_volume = MIN_COMMODITY_AVG_VOLUME if asset_class == "commodity" else MIN_EQUITY_AVG_VOLUME

    warnings = []
    if avg_volume < min_avg_volume:
        warnings.append(f"liquidita bassa: volume medio 10 sedute {avg_volume:.0f} < soglia {min_avg_volume:.0f}")
    if turnover < MIN_LIQUIDITY_TURNOVER_EUR:
        warnings.append(f"controvalore medio basso: circa EUR {turnover:.0f} < soglia EUR {MIN_LIQUIDITY_TURNOVER_EUR:.0f}")

    return {
        "volume": volume,
        "volume_ma5": volume_ma5,
        "volume_ma10": volume_ma10,
        "avg_volume": avg_volume,
        "turnover_eur": turnover,
        "min_avg_volume": min_avg_volume,
        "min_turnover_eur": MIN_LIQUIDITY_TURNOVER_EUR,
        "liquidity_ok": not warnings,
        "liquidity_warnings": warnings,
    }


def apply_liquidity_to_score(score, risks, snapshot, asset_class="equity"):
    metrics = liquidity_metrics(snapshot, asset_class=asset_class)
    adjusted = int(score)
    if metrics["liquidity_warnings"]:
        adjusted -= 3
        risks.extend(metrics["liquidity_warnings"])
    return adjusted, metrics
