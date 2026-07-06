"""
config_loader.py — Centralized configuration loader with environment variable overrides.

Environment variables take precedence over values in config/config.json, which allows
running the bot in Docker / CI / cloud environments without modifying any files.

Supported overrides:
    ALPACA_API_KEY              → alpaca.api_key
    ALPACA_API_SECRET           → alpaca.api_secret
    ALPACA_DATA_FEED            → alpaca.data_feed  (sip | iex)
    ALPACA_USE_PAPER            → alpaca.use_paper  (true | false)
    GEMINI_API_KEY              → all gemini-* models api_key
    OPENAI_API_KEY              → all gpt-* / o4-* models api_key
    DISCORD_WEBHOOK_URL         → discord.webhook_url
    DISCORD_REPORT_WEBHOOK_URL  → discord.webhook_url_market_report
    TV_CHART_ID                 → tradingview.chart_id
"""

import json
import logging
import os
from copy import deepcopy

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config', 'config.json'
)


def load_config(config_path: str = None) -> dict:
    """
    Load config from JSON file then apply environment variable overrides.

    Args:
        config_path: Path to config.json. Defaults to <project_root>/config/config.json.

    Returns:
        Merged configuration dictionary (file values + env var overrides).
    """
    config_path = config_path or _DEFAULT_CONFIG_PATH

    # --- Load from file ---
    config = {}
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.debug(f"Loaded config from {config_path}")
    except FileNotFoundError:
        logger.error(
            f"Config file not found at {config_path}. "
            "Copy config/config.example.json to config/config.json and fill in your values."
        )
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing config file {config_path}: {e}")

    # Deep copy so we never mutate the raw parsed dict
    cfg = deepcopy(config)

    # --- Apply environment variable overrides ---
    _apply_env_overrides(cfg)

    return cfg


def _apply_env_overrides(cfg: dict) -> None:
    """Apply supported environment variable overrides in-place."""

    # Alpaca
    alpaca = cfg.setdefault('alpaca', {})
    _override(alpaca, 'api_key',    os.environ.get('ALPACA_API_KEY'))
    _override(alpaca, 'api_secret', os.environ.get('ALPACA_API_SECRET'))
    _override(alpaca, 'data_feed',  os.environ.get('ALPACA_DATA_FEED'))
    use_paper_env = os.environ.get('ALPACA_USE_PAPER')
    if use_paper_env is not None:
        alpaca['use_paper'] = use_paper_env.lower() not in ('false', '0', 'no')

    # Discord
    discord = cfg.setdefault('discord', {})
    _override(discord, 'webhook_url',              os.environ.get('DISCORD_WEBHOOK_URL'))
    _override(discord, 'webhook_url_market_report', os.environ.get('DISCORD_REPORT_WEBHOOK_URL'))

    # TradingView
    tv = cfg.setdefault('tradingview', {})
    _override(tv, 'chart_id', os.environ.get('TV_CHART_ID'))

    # LLM API keys — apply to all matching models
    llms = cfg.setdefault('llms', {})
    models = llms.setdefault('models', [])
    gemini_key = os.environ.get('GEMINI_API_KEY')
    openai_key = os.environ.get('OPENAI_API_KEY')

    for model in models:
        name = model.get('name', '')
        if gemini_key and name.startswith('gemini'):
            model['api_key'] = gemini_key
            logger.debug(f"Applied GEMINI_API_KEY env var to model '{name}'")
        if openai_key and (name.startswith('gpt') or name.startswith('o4') or name.startswith('o3')):
            model['api_key'] = openai_key
            logger.debug(f"Applied OPENAI_API_KEY env var to model '{name}'")


def _override(section: dict, key: str, value) -> None:
    """Set key in section only if value is a non-empty string."""
    if value:
        section[key] = value
        logger.debug(f"Config override applied: {key} (from environment variable)")
