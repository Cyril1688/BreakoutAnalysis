"""
Configuration settings for the Screenshot API.
Cookies and auth are loaded from config/config.json — do NOT hardcode credentials here.
"""

import os
import json
from pathlib import Path

# Base directory for screenshots
SCREENSHOT_BASE_DIR = os.path.join(os.getcwd(), "assets", "screenshots")

# Default screenshot settings
DEFAULT_IMAGE_TYPE = "png"
DEFAULT_VIEWPORT_WIDTH = 1920
DEFAULT_VIEWPORT_HEIGHT = 1080
DEFAULT_DEVICE_SCALE_FACTOR = 1  # Increase for higher resolution

# Browser settings
BROWSER_TYPE = "chromium"  # Options: chromium, firefox, webkit
HEADLESS = True

# Timeout settings (in milliseconds)
NAVIGATION_TIMEOUT = 60000  # 60 seconds
WAIT_FOR_TIMEOUT = 30000    # 30 seconds

# TradingView specific settings
TRADINGVIEW_WAIT_SELECTOR = ".chart-markup-table"
TRADINGVIEW_LOAD_STATE = "domcontentloaded"

# TradingView headers (no credentials here — safe to share)
TRADINGVIEW_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}


def _load_tradingview_cookies():
    """
    Loads TradingView session cookies from config/config.json.
    Returns an empty list if cookies are not configured (screenshots will work
    but may show the login page for authenticated charts).
    """
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'config', 'config.json'
    )
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        tv_cookies = config.get('tradingview', {}).get('cookies', {})
        sessionid = tv_cookies.get('sessionid', '')
        sessionid_sign = tv_cookies.get('sessionid_sign', '')
        device_t = tv_cookies.get('device_t', '')

        if not sessionid:
            return []  # No cookies configured — unauthenticated screenshots

        return [
            {"name": "sessionid",      "value": sessionid,      "domain": ".tradingview.com", "path": "/"},
            {"name": "sessionid_sign", "value": sessionid_sign, "domain": ".tradingview.com", "path": "/"},
            {"name": "device_t",       "value": device_t,       "domain": ".tradingview.com", "path": "/"},
        ]
    except Exception:
        return []  # Fail gracefully — screenshots will still be attempted without auth


# Loaded at import time; returns [] if not configured
TRADINGVIEW_COOKIES = _load_tradingview_cookies()


def get_screenshot_dir(date_str=None):
    """
    Get the screenshot directory for a specific date.
    If date_str is None, the base directory is returned.

    Args:
        date_str (str, optional): Date string in format YYYY-MM-DD. Defaults to None.

    Returns:
        Path: Path object for the screenshot directory
    """
    if date_str:
        return Path(SCREENSHOT_BASE_DIR) / date_str
    return Path(SCREENSHOT_BASE_DIR)
