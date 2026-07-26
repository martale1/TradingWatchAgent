import re
import unicodedata
from functools import lru_cache

from finance_tools.commodity_scanner import load_commodity_tickers
from finance_tools.etf_scanner import load_etf_tickers
from finance_tools.mib30_scanner import load_mib30_tickers
from finance_tools.portfolio_store import load_portfolio


MANUAL_ALIASES = {
    "A2A": "A2A.MI",
    "AMPLIFON": "AMP.MI",
    "AMP": "AMP.MI",
    "CAMPARI": "CPR.MI",
    "CPR": "CPR.MI",
    "HERA": "HER.MI",
    "HER": "HER.MI",
    "SNAM": "SRG.MI",
    "SRG": "SRG.MI",
    "VODAFONE": "VOD.L",
    "VOD": "VOD.L",
    "NEXI": "NEXI.MI",
    "STELLANTIS": "STLAM.MI",
    "STLAM": "STLAM.MI",
    "RAME": "COPA.MI",
    "COPPER": "COPA.MI",
    "ORO": "GBS.MI",
    "GOLD": "GBS.MI",
    "CAFFE": "COFF.MI",
    "CAFFÈ": "COFF.MI",
    "COFFEE": "COFF.MI",
    "PETROLIO": "CRUD.MI",
    "CRUDE": "CRUD.MI",
    "OIL": "CRUD.MI",
    "GRANO": "WEAT.MI",
    "WHEAT": "WEAT.MI",
}

IGNORED_TOKENS = {
    "AI",
    "ADX",
    "AND",
    "BUY",
    "BOT",
    "COSA",
    "DA",
    "DEI",
    "DEL",
    "DI",
    "EUR",
    "EURO",
    "FAI",
    "FARA",
    "FARAI",
    "GRAFICO",
    "GRAFICI",
    "IL",
    "IN",
    "LA",
    "LE",
    "LO",
    "MACD",
    "MI",
    "NO",
    "OK",
    "PER",
    "PREZZO",
    "RSI",
    "SE",
    "SU",
    "TICKER",
    "TITOLO",
    "TRIGGER",
    "TU",
    "VENDI",
    "VENDITA",
    "VOLUME",
    "VOLUMI",
}


def normalize_text(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.upper().replace("€", " EUR ")
    return re.sub(r"[^A-Z0-9.]+", " ", text).strip()


def _plain_alias(value):
    return re.sub(r"[^A-Z0-9]+", " ", normalize_text(value)).strip()


def _add_alias(index, alias, ticker, name="", market="", source=""):
    alias = _plain_alias(alias)
    ticker = str(ticker or "").strip().upper()
    if not alias or not ticker or alias in IGNORED_TOKENS:
        return
    item = {"ticker": ticker, "name": name or ticker, "market": market, "source": source}
    index.setdefault(alias, {})
    existing = index[alias].get(ticker)
    if existing and existing.get("source") == "manual":
        return
    index[alias][ticker] = item


def _add_universe_item(index, item, market):
    ticker = str(item.get("ticker", "")).strip().upper()
    if not ticker:
        return
    name = str(item.get("name") or ticker).strip()
    _add_alias(index, ticker, ticker, name=name, market=market, source="ticker")
    _add_alias(index, ticker.split(".")[0], ticker, name=name, market=market, source="ticker_root")
    _add_alias(index, name, ticker, name=name, market=market, source="name")

    words = [word for word in _plain_alias(name).split() if len(word) >= 3 and word not in IGNORED_TOKENS]
    if words:
        _add_alias(index, words[0], ticker, name=name, market=market, source="name_word")


@lru_cache(maxsize=1)
def build_static_alias_index():
    index = {}
    for alias, ticker in MANUAL_ALIASES.items():
        _add_alias(index, alias, ticker, source="manual")
    for item in load_mib30_tickers():
        _add_universe_item(index, item, market="FTSE MIB")
    for item in load_commodity_tickers():
        _add_universe_item(index, item, market="Materie prime")
    for item in load_etf_tickers():
        _add_universe_item(index, item, market="ETF")
    return index


def build_runtime_alias_index():
    index = {alias: dict(matches) for alias, matches in build_static_alias_index().items()}
    portfolio = load_portfolio() or {}
    runtime_groups = [
        ("positions", "portfolio"),
        ("watchlist", "watchlist"),
        ("monitored_conditions", "monitoring"),
        ("pending_proposals", "proposal"),
    ]
    for group_name, source in runtime_groups:
        for item in portfolio.get(group_name, []) or []:
            ticker = str(item.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            name = str(item.get("name") or ticker).strip()
            _add_alias(index, ticker, ticker, name=name, source=source)
            _add_alias(index, ticker.split(".")[0], ticker, name=name, source=source)
            _add_alias(index, name, ticker, name=name, source=source)
    return index


def _history_text(history):
    parts = []
    for item in history or []:
        if isinstance(item, dict):
            parts.extend(str(item.get(key, "")) for key in ("content", "user", "assistant"))
        else:
            parts.append(str(item))
    return "\n".join(part for part in parts if part)


def resolve_ticker_reference(text, history=None):
    text = str(text or "")
    explicit = re.search(r"\b([A-Z0-9]{1,8}\.[A-Z]{1,4})\b", text, flags=re.IGNORECASE)
    if explicit:
        ticker = explicit.group(1).upper()
        return {
            "ticker": ticker,
            "matched_text": explicit.group(1),
            "name": ticker,
            "market": "",
            "source": "explicit_ticker",
            "ambiguous": [],
        }

    normalized = f" {_plain_alias(text)} "
    matches = {}
    index = build_runtime_alias_index()
    for alias, alias_matches in index.items():
        if f" {alias} " in normalized:
            for ticker, item in alias_matches.items():
                matches[ticker] = {**item, "matched_text": alias}

    if len(matches) == 1:
        item = next(iter(matches.values()))
        return {**item, "ambiguous": []}
    if len(matches) > 1:
        ordered = sorted(matches.values(), key=lambda item: (item.get("source") != "manual", item["ticker"]))
        return {
            "ticker": "",
            "matched_text": "",
            "name": "",
            "market": "",
            "source": "ambiguous",
            "ambiguous": ordered,
        }

    history_blob = _history_text(history)
    if history_blob:
        return resolve_ticker_reference(history_blob, history=None)

    return {"ticker": "", "matched_text": "", "name": "", "market": "", "source": "", "ambiguous": []}


def resolve_ticker(text, history=None):
    resolved = resolve_ticker_reference(text, history=history)
    return resolved.get("ticker", "")


def resolve_ticker_context(text, history=None):
    resolved = resolve_ticker_reference(text, history=history)
    if resolved.get("ticker"):
        label = resolved.get("matched_text") or resolved.get("name") or resolved["ticker"]
        market = f" ({resolved['market']})" if resolved.get("market") else ""
        return f"Ticker risolto dalla richiesta: {label} -> {resolved['ticker']}{market}."
    ambiguous = resolved.get("ambiguous") or []
    if ambiguous:
        options = ", ".join(f"{item['ticker']} ({item.get('name') or item['ticker']})" for item in ambiguous[:6])
        return f"Riferimento ticker ambiguo. Chiedi conferma all'utente prima di operare. Possibili ticker: {options}."
    return ""
