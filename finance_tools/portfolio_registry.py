import copy
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from finance_tools.common import PROJECT_ROOT


PORTFOLIOS_ROOT = PROJECT_ROOT / "data" / "portfolios"
REGISTRY_FILE = PORTFOLIOS_ROOT / "registry.json"
LEGACY_PORTFOLIO_FILE = PROJECT_ROOT / "portfolio.json"
DEFAULT_PORTFOLIO_ID = "main"
VALID_STATUSES = {"active", "paused", "archived"}
VALID_ASSET_CLASSES = {"equity", "etf", "commodity_etc"}
VALID_MARKETS = {"ftse_mib", "commodities", "etf", "watchlist"}
VALID_AUTONOMY_MODES = {"confirmation", "protective", "full_auto"}
PORTFOLIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


RISK_PROFILES = {
    "conservative": {
        "min_cash_pct": 25.0,
        "max_position_pct": 7.0,
        "max_sector_pct": 18.0,
        "max_new_position_pct": 5.0,
        "max_increment_pct": 2.0,
        "min_trade_pct": 1.0,
        "min_score": 7.0,
        "min_average_turnover": 250000.0,
        "max_positions": 25,
    },
    "balanced": {
        "min_cash_pct": 15.0,
        "max_position_pct": 12.0,
        "max_sector_pct": 25.0,
        "max_new_position_pct": 8.0,
        "max_increment_pct": 3.0,
        "min_trade_pct": 1.0,
        "min_score": 6.0,
        "min_average_turnover": 100000.0,
        "max_positions": 18,
    },
    "dynamic": {
        "min_cash_pct": 8.0,
        "max_position_pct": 18.0,
        "max_sector_pct": 35.0,
        "max_new_position_pct": 12.0,
        "max_increment_pct": 5.0,
        "min_trade_pct": 1.0,
        "min_score": 5.0,
        "min_average_turnover": 50000.0,
        "max_positions": 12,
    },
}


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(default)


def validate_portfolio_id(portfolio_id):
    value = str(portfolio_id or "").strip().lower()
    if not PORTFOLIO_ID_RE.match(value):
        raise ValueError(
            "ID portafoglio non valido: usa 3-50 caratteri minuscoli, numeri e trattini."
        )
    return value


def portfolio_dir(portfolio_id):
    return PORTFOLIOS_ROOT / validate_portfolio_id(portfolio_id)


def portfolio_state_path(portfolio_id=DEFAULT_PORTFOLIO_ID):
    return portfolio_dir(portfolio_id) / "portfolio.json"


def portfolio_config_path(portfolio_id=DEFAULT_PORTFOLIO_ID):
    return portfolio_dir(portfolio_id) / "config.json"


def portfolio_runtime_path(portfolio_id=DEFAULT_PORTFOLIO_ID):
    return portfolio_dir(portfolio_id) / "runtime.json"


def risk_profile(profile_name="balanced", overrides=None):
    profile_name = str(profile_name or "balanced").strip().lower()
    if profile_name not in RISK_PROFILES:
        raise ValueError(f"Profilo di rischio non valido: {profile_name}")
    values = copy.deepcopy(RISK_PROFILES[profile_name])
    overrides = overrides or {}
    for key in values:
        if key in overrides and overrides[key] is not None:
            expected_type = int if key == "max_positions" else float
            values[key] = expected_type(overrides[key])
    if values["min_cash_pct"] < 0 or values["min_cash_pct"] >= 100:
        raise ValueError("min_cash_pct deve essere compreso tra 0 e 100.")
    for key in (
        "max_position_pct",
        "max_sector_pct",
        "max_new_position_pct",
        "max_increment_pct",
        "min_trade_pct",
    ):
        if values[key] <= 0 or values[key] > 100:
            raise ValueError(f"{key} deve essere maggiore di 0 e non superiore a 100.")
    if values["max_positions"] < 1:
        raise ValueError("max_positions deve essere almeno 1.")
    return values


def default_config(
    portfolio_id,
    name,
    initial_capital,
    profile_name="balanced",
    description="",
    allowed_markets=None,
    allowed_asset_classes=None,
    autonomy_mode="full_auto",
    risk_overrides=None,
):
    portfolio_id = validate_portfolio_id(portfolio_id)
    autonomy_mode = str(autonomy_mode or "full_auto")
    if autonomy_mode not in VALID_AUTONOMY_MODES:
        raise ValueError(f"Modalita autonomia non valida: {autonomy_mode}")
    markets = list(dict.fromkeys(allowed_markets or sorted(VALID_MARKETS)))
    assets = list(dict.fromkeys(allowed_asset_classes or sorted(VALID_ASSET_CLASSES)))
    invalid_markets = set(markets) - VALID_MARKETS
    invalid_assets = set(assets) - VALID_ASSET_CLASSES
    if not markets:
        raise ValueError("Seleziona almeno un mercato.")
    if not assets:
        raise ValueError("Seleziona almeno una asset class.")
    if invalid_markets:
        raise ValueError(f"Mercati non validi: {', '.join(sorted(invalid_markets))}")
    if invalid_assets:
        raise ValueError(f"Asset class non valide: {', '.join(sorted(invalid_assets))}")
    timestamp = now_iso()
    return {
        "version": 1,
        "id": portfolio_id,
        "name": str(name or portfolio_id).strip(),
        "description": str(description or "").strip(),
        "status": "active",
        "created_at": timestamp,
        "updated_at": timestamp,
        "initial_capital": float(initial_capital),
        "base_currency": "EUR",
        "risk_profile": str(profile_name or "balanced").lower(),
        "risk_limits": risk_profile(profile_name, risk_overrides),
        "allowed_markets": markets,
        "allowed_asset_classes": assets,
        "allow_leveraged": False,
        "excluded_sectors": [],
        "preferred_sectors": [],
        "excluded_tickers": [],
        "asset_class_limits_pct": {},
        "autonomy": {
            "portfolio_action_mode": autonomy_mode,
            "notify_telegram": True,
        },
        "telegram": {
            "inherit_global": True,
        },
    }


def default_portfolio_state(portfolio_id, initial_capital):
    timestamp = now_iso()
    return {
        "version": 2,
        "portfolio_id": portfolio_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "base_currency": "EUR",
        "initial_capital": float(initial_capital),
        "cash": float(initial_capital),
        "positions": [],
        "watchlist": [],
        "monitored_conditions": [],
        "pending_proposals": [],
        "closed_proposals": [],
    }


def empty_registry():
    return {
        "version": 1,
        "default_portfolio_id": DEFAULT_PORTFOLIO_ID,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "migration": {},
        "portfolios": [],
    }


def load_registry(ensure=True):
    if ensure:
        ensure_registry()
    return read_json(REGISTRY_FILE, empty_registry())


def registry_entry(config):
    return {
        "id": config["id"],
        "name": config["name"],
        "description": config.get("description", ""),
        "status": config.get("status", "active"),
        "risk_profile": config.get("risk_profile", "balanced"),
        "initial_capital": config.get("initial_capital", 0),
        "base_currency": config.get("base_currency", "EUR"),
        "created_at": config.get("created_at"),
        "updated_at": config.get("updated_at"),
    }


def save_registry(registry):
    registry["updated_at"] = now_iso()
    atomic_write_json(REGISTRY_FILE, registry)
    return registry


def ensure_registry():
    if REGISTRY_FILE.exists():
        return read_json(REGISTRY_FILE, empty_registry())

    registry = empty_registry()
    legacy = read_json(LEGACY_PORTFOLIO_FILE)
    if isinstance(legacy, dict):
        capital = float(legacy.get("initial_capital") or legacy.get("cash") or 0)
        state = copy.deepcopy(legacy)
        state["version"] = max(int(state.get("version") or 1), 2)
        state["portfolio_id"] = DEFAULT_PORTFOLIO_ID
        config = default_config(
            DEFAULT_PORTFOLIO_ID,
            "Portafoglio principale",
            capital,
            profile_name="balanced",
        )
        atomic_write_json(portfolio_state_path(DEFAULT_PORTFOLIO_ID), state)
        atomic_write_json(portfolio_config_path(DEFAULT_PORTFOLIO_ID), config)
        atomic_write_json(
            portfolio_runtime_path(DEFAULT_PORTFOLIO_ID),
            {"portfolio_id": DEFAULT_PORTFOLIO_ID, "updated_at": now_iso()},
        )
        registry["migration"] = {
            "legacy_portfolio_imported": True,
            "source": str(LEGACY_PORTFOLIO_FILE),
            "portfolio_id": DEFAULT_PORTFOLIO_ID,
            "migrated_at": now_iso(),
        }
        registry["portfolios"].append(registry_entry(config))
    save_registry(registry)
    return registry


def list_portfolios(include_archived=False):
    registry = load_registry()
    entries = registry.get("portfolios", [])
    if not include_archived:
        entries = [item for item in entries if item.get("status") != "archived"]
    return {
        "default_portfolio_id": registry.get("default_portfolio_id", DEFAULT_PORTFOLIO_ID),
        "items": entries,
        "count": len(entries),
        "risk_profiles": copy.deepcopy(RISK_PROFILES),
    }


def load_portfolio_config(portfolio_id=DEFAULT_PORTFOLIO_ID):
    ensure_registry()
    return read_json(portfolio_config_path(portfolio_id))


def load_portfolio_state(portfolio_id=DEFAULT_PORTFOLIO_ID):
    ensure_registry()
    return read_json(portfolio_state_path(portfolio_id))


def create_portfolio(
    portfolio_id,
    name,
    initial_capital,
    profile_name="balanced",
    description="",
    allowed_markets=None,
    allowed_asset_classes=None,
    autonomy_mode="full_auto",
    risk_overrides=None,
    allow_leveraged=False,
):
    portfolio_id = validate_portfolio_id(portfolio_id)
    capital = float(initial_capital)
    if capital <= 0:
        raise ValueError("Il capitale iniziale deve essere maggiore di zero.")
    registry = load_registry()
    if any(item.get("id") == portfolio_id for item in registry.get("portfolios", [])):
        raise FileExistsError(f"Il portafoglio {portfolio_id} esiste gia.")
    config = default_config(
        portfolio_id,
        name,
        capital,
        profile_name=profile_name,
        description=description,
        allowed_markets=allowed_markets,
        allowed_asset_classes=allowed_asset_classes,
        autonomy_mode=autonomy_mode,
        risk_overrides=risk_overrides,
    )
    config["allow_leveraged"] = bool(allow_leveraged)
    state = default_portfolio_state(portfolio_id, capital)
    atomic_write_json(portfolio_config_path(portfolio_id), config)
    atomic_write_json(portfolio_state_path(portfolio_id), state)
    atomic_write_json(
        portfolio_runtime_path(portfolio_id),
        {"portfolio_id": portfolio_id, "updated_at": now_iso()},
    )
    registry.setdefault("portfolios", []).append(registry_entry(config))
    save_registry(registry)
    return {"config": config, "portfolio": state}


def update_portfolio_config(portfolio_id, changes):
    portfolio_id = validate_portfolio_id(portfolio_id)
    config = load_portfolio_config(portfolio_id)
    if not config:
        raise FileNotFoundError(f"Portafoglio {portfolio_id} non trovato.")
    changes = dict(changes or {})
    if "id" in changes and changes["id"] != portfolio_id:
        raise ValueError("L'ID del portafoglio non puo essere modificato.")
    for key in ("name", "description", "allow_leveraged"):
        if key in changes:
            config[key] = changes[key]
    if "status" in changes:
        if changes["status"] not in VALID_STATUSES:
            raise ValueError(f"Stato non valido: {changes['status']}")
        config["status"] = changes["status"]
    if "allowed_markets" in changes:
        if not changes["allowed_markets"]:
            raise ValueError("Seleziona almeno un mercato.")
        invalid = set(changes["allowed_markets"]) - VALID_MARKETS
        if invalid:
            raise ValueError(f"Mercati non validi: {', '.join(sorted(invalid))}")
        config["allowed_markets"] = list(dict.fromkeys(changes["allowed_markets"]))
    if "allowed_asset_classes" in changes:
        if not changes["allowed_asset_classes"]:
            raise ValueError("Seleziona almeno una asset class.")
        invalid = set(changes["allowed_asset_classes"]) - VALID_ASSET_CLASSES
        if invalid:
            raise ValueError(f"Asset class non valide: {', '.join(sorted(invalid))}")
        config["allowed_asset_classes"] = list(dict.fromkeys(changes["allowed_asset_classes"]))
    if "risk_profile" in changes or "risk_limits" in changes:
        profile_name = changes.get("risk_profile", config.get("risk_profile", "balanced"))
        config["risk_profile"] = profile_name
        config["risk_limits"] = risk_profile(profile_name, changes.get("risk_limits"))
    if "autonomy" in changes:
        autonomy = {**config.get("autonomy", {}), **(changes["autonomy"] or {})}
        mode = autonomy.get("portfolio_action_mode", "full_auto")
        if mode not in VALID_AUTONOMY_MODES:
            raise ValueError(f"Modalita autonomia non valida: {mode}")
        autonomy["notify_telegram"] = bool(autonomy.get("notify_telegram", True))
        config["autonomy"] = autonomy
    for key in (
        "excluded_sectors",
        "preferred_sectors",
        "excluded_tickers",
        "asset_class_limits_pct",
        "telegram",
    ):
        if key in changes:
            config[key] = changes[key]
    config["updated_at"] = now_iso()
    atomic_write_json(portfolio_config_path(portfolio_id), config)

    registry = load_registry()
    entries = registry.get("portfolios", [])
    registry["portfolios"] = [
        registry_entry(config) if item.get("id") == portfolio_id else item
        for item in entries
    ]
    save_registry(registry)
    return config
