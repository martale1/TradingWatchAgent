import json
import os

from finance_tools.common import PROJECT_ROOT
from finance_tools.portfolio_registry import (
    DEFAULT_PORTFOLIO_ID,
    load_portfolio_config,
    update_portfolio_config,
)


AUTONOMY_SETTINGS_FILE = PROJECT_ROOT / "autonomy_settings.json"
VALID_MODES = {"confirmation", "protective", "full_auto"}
LEGACY_MODE_ALIASES = {"advisory": "confirmation"}
DEFAULT_SETTINGS = {
    "portfolio_action_mode": "full_auto",
    "notify_telegram": True,
}


def active_portfolio_id(portfolio_id=None):
    return str(
        portfolio_id
        or os.getenv("ACTIVE_PORTFOLIO_ID")
        or DEFAULT_PORTFOLIO_ID
    ).strip().lower()


def load_autonomy_settings(portfolio_id=None):
    settings = dict(DEFAULT_SETTINGS)
    resolved_id = active_portfolio_id(portfolio_id)
    config = load_portfolio_config(resolved_id)
    portfolio_settings = (config or {}).get("autonomy")
    if isinstance(portfolio_settings, dict):
        settings.update(portfolio_settings)
    elif AUTONOMY_SETTINGS_FILE.exists():
        try:
            payload = json.loads(AUTONOMY_SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                settings.update(payload)
        except (OSError, json.JSONDecodeError):
            pass
    mode = LEGACY_MODE_ALIASES.get(
        settings.get("portfolio_action_mode"),
        settings.get("portfolio_action_mode"),
    )
    if mode not in VALID_MODES:
        settings["portfolio_action_mode"] = DEFAULT_SETTINGS["portfolio_action_mode"]
    else:
        settings["portfolio_action_mode"] = mode
    settings["notify_telegram"] = bool(settings.get("notify_telegram", True))
    return settings


def save_autonomy_settings(values, portfolio_id=None):
    resolved_id = active_portfolio_id(portfolio_id)
    current = load_autonomy_settings(resolved_id)
    mode = values.get("portfolio_action_mode", current["portfolio_action_mode"])
    mode = LEGACY_MODE_ALIASES.get(mode, mode)
    if mode not in VALID_MODES:
        raise ValueError(f"Modalita autonomia non valida: {mode}")
    current.update(
        {
            "portfolio_action_mode": mode,
            "notify_telegram": bool(values.get("notify_telegram", current["notify_telegram"])),
        }
    )
    config = load_portfolio_config(resolved_id)
    if config:
        update_portfolio_config(resolved_id, {"autonomy": current})
    else:
        AUTONOMY_SETTINGS_FILE.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return current


def autonomous_action_allowed(action, portfolio_id=None):
    mode = load_autonomy_settings(portfolio_id)["portfolio_action_mode"]
    if mode == "full_auto":
        return True, mode
    if mode == "protective" and action in {"sell_virtual_position", "reduce_virtual_position"}:
        return True, mode
    return False, mode
