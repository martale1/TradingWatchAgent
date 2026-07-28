from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


MARKET_CLOSE_RULES = {
    ".L": ("Europe/London", time(16, 30)),
    ".MI": ("Europe/Rome", time(17, 30)),
}
DEFAULT_CLOSE_RULE = ("Europe/Rome", time(17, 30))
FINALIZATION_BUFFER_MINUTES = 10


def market_close_status(ticker, snapshot_date=None, now=None):
    symbol = str(ticker or "").strip().upper()
    timezone_name, close_time = next(
        (rule for suffix, rule in MARKET_CLOSE_RULES.items() if symbol.endswith(suffix)),
        DEFAULT_CLOSE_RULE,
    )
    market_tz = ZoneInfo(timezone_name)
    moment = now or datetime.now(market_tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=market_tz)
    else:
        moment = moment.astimezone(market_tz)

    try:
        bar_date = datetime.fromisoformat(str(snapshot_date)).date()
    except (TypeError, ValueError):
        bar_date = moment.date()

    close_at = datetime.combine(bar_date, close_time, tzinfo=market_tz)
    finalized_at = close_at + timedelta(minutes=FINALIZATION_BUFFER_MINUTES)
    if bar_date < moment.date():
        complete = True
        reason = "ultima barra riferita a una seduta gia conclusa"
    elif bar_date > moment.date():
        complete = False
        reason = "barra giornaliera con data futura/non consolidata"
    elif moment.weekday() >= 5:
        complete = True
        reason = "mercato chiuso nel fine settimana"
    elif moment >= finalized_at:
        complete = True
        reason = "seduta conclusa e barra giornaliera consolidata"
    else:
        complete = False
        reason = "seduta ancora in corso: volume e close giornalieri provvisori"

    return {
        "daily_bar_complete": complete,
        "reason": reason,
        "market_timezone": timezone_name,
        "market_close_at": close_at.isoformat(timespec="minutes"),
        "volume_finalized_at": finalized_at.isoformat(timespec="minutes"),
        "snapshot_date": bar_date.isoformat(),
    }
