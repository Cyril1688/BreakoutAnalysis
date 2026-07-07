"""
US Stock (美股) Screener
Uses akshare (East Money) to fetch US real-time quotes and screen for unusual movers.

No API keys required (akshare hits East Money's public endpoint).
Mirrors the structure of china_screener.py so it slots into the same pipeline.

Market hours (US/Eastern, UTC-4 in summer):
- Regular session: 9:30 - 16:00
- We only screen during the regular session to avoid alerting on stale pre-open data.
"""

import json
import logging
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - US_SCREENER - %(levelname)s - %(message)s')

# US/Eastern timezone
US_EASTERN_TZ = pytz.timezone('US/Eastern')

# Config path relative to project root
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.json')

# Column mapping: akshare (East Money) US columns -> standard names
# (matches the schema expected by tradealerts.prepare_notification_content)
US_COLUMN_MAP = {
    'Ticker': '代码',            # e.g., 'AAPL.OQ' -> stripped to 'AAPL'
    'CompanyName': '名称',       # e.g., '苹果' (Chinese name)
    'Price': '最新价',
    'ChangePercent': '涨跌幅',   # percentage, e.g., 2.35 or -3.1
    'ChangeAmount': '涨跌额',
    'Volume': '成交量',          # in shares
    'Turnover': '成交额',        # in USD
    'Amplitude': '振幅',
    'High': '最高价',
    'Low': '最低价',
    'Open': '开盘价',
    'PrevClose': '昨收价',
    'PE': '市盈率',
    'MarketCap': '总市值',       # in USD
    'TurnoverRate': '换手率',
}

# East Money US exchange suffixes -> friendly exchange name
EXCHANGE_SUFFIX_MAP = {
    'OQ': 'NASDAQ',
    'N': 'NYSE',
    'A': 'AMEX',
    'P': 'NYSE Arca',
    'L': 'NYSE',
    'B': 'NYSE',
    'V': 'NYSE Arca',
    'C': 'NYSE',
    'I': 'NASDAQ',
    'Q': 'NASDAQ',
    'Z': 'BATS',
    'U': 'NYSE',
    'W': 'NYSE',
    'X': 'NYSE',
    'Y': 'NYSE',
    'T': 'NYSE',
    'S': 'NYSE',
    'H': 'NYSE',
    'O': 'NASDAQ',
}

# Technical columns (not computed for US to avoid hammering the data source; left as NaN)
TECHNICAL_COLUMNS = ['RSI', 'SMA10', 'SMA20', 'SMA50', 'SMA100', 'SMA200', 'MACD_MACD', 'MACD_Signal', 'VWAP']


def load_config(config_path=None):
    """Loads configuration from config.json (falls back to module-level path)."""
    path = config_path or CONFIG_PATH
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logging.info(f"US screener configuration loaded from {path}.")
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found at {path}")
        return None
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from the configuration file at {path}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading the config: {e}")
        return None


def is_us_market_hours():
    """
    Check if current time is within US regular trading hours (US/Eastern).
    Regular session: 9:30 - 16:00, weekdays only.
    """
    now_eastern = datetime.now(US_EASTERN_TZ)

    if now_eastern.weekday() >= 5:  # Saturday=5, Sunday=6
        logging.info(f"Skipping: Weekend in US. Current time: {now_eastern.strftime('%A, %H:%M:%S %Z')}")
        return False

    current_time = now_eastern.time()
    regular_start = datetime.strptime("09:30", "%H:%M").time()
    regular_end = datetime.strptime("16:00", "%H:%M").time()

    if regular_start <= current_time < regular_end:
        return True

    logging.info(f"Skipping: Outside US regular trading hours. Current ET: {now_eastern.strftime('%H:%M:%S %Z')}")
    return False


def fetch_us_market_data(config):
    """
    Fetches US real-time market data using akshare (East Money).
    Returns raw DataFrame with East Money columns, or empty DataFrame on failure.
    """
    try:
        import akshare as ak
    except ImportError as e:
        logging.error(f"akshare import FAILED for US data: {e}", exc_info=True)
        return pd.DataFrame()

    try:
        logging.info("Fetching US real-time market data from East Money (akshare stock_us_spot_em)...")
        df = ak.stock_us_spot_em()

        if df is None or df.empty:
            logging.warning("No US data returned from East Money.")
            return pd.DataFrame()

        logging.info(f"Fetched {len(df)} US stocks from East Money.")
        return df

    except Exception as e:
        logging.error(f"Error fetching US market data: {e}")
        return pd.DataFrame()


def apply_filters(df, filters_config):
    """
    Apply filter thresholds to US data.
    Catches unusually large movers in BOTH directions (abs(change) >= threshold).
    """
    if df is None or df.empty:
        return pd.DataFrame()

    fc = filters_config or {}
    min_change = fc.get('us_min_change_percent', 5.0)      # |涨跌幅| threshold
    max_change = fc.get('us_max_change_percent', 30.0)     # exclude extreme >30% noise
    min_volume = fc.get('us_min_volume', 500000)            # in shares
    min_price = fc.get('us_min_price', 3.0)
    max_price = fc.get('us_max_price', 2000.0)
    min_market_cap = fc.get('us_min_market_cap', 300000000)  # $300M

    df_filtered = df.copy()

    # Change filter (absolute value, both up and down movers)
    if '涨跌幅' in df_filtered.columns:
        df_filtered['涨跌幅'] = pd.to_numeric(df_filtered['涨跌幅'], errors='coerce')
        df_filtered['_abs_change'] = df_filtered['涨跌幅'].abs()
        df_filtered = df_filtered[
            (df_filtered['_abs_change'] >= min_change) &
            (df_filtered['_abs_change'] <= max_change)
        ]

    # Volume filter (成交量)
    if '成交量' in df_filtered.columns:
        df_filtered['成交量'] = pd.to_numeric(df_filtered['成交量'], errors='coerce')
        df_filtered = df_filtered[df_filtered['成交量'] >= min_volume]

    # Price filter
    if '最新价' in df_filtered.columns:
        df_filtered['最新价'] = pd.to_numeric(df_filtered['最新价'], errors='coerce')
        df_filtered = df_filtered[
            (df_filtered['最新价'] >= min_price) &
            (df_filtered['最新价'] <= max_price)
        ]

    # Market cap filter (总市值)
    if '总市值' in df_filtered.columns:
        df_filtered['总市值'] = pd.to_numeric(df_filtered['总市值'], errors='coerce')
        df_filtered = df_filtered[df_filtered['总市值'] >= min_market_cap]

    # Drop helper column
    df_filtered = df_filtered.drop(columns=['_abs_change'], errors='ignore')

    logging.info(f"After US filters: {len(df_filtered)} stocks remain.")
    return df_filtered


def normalize_to_standard(df):
    """
    Normalize US DataFrame to standard column names matching the pipeline schema.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    standard_df = pd.DataFrame()

    text_columns = {'Ticker', 'CompanyName'}

    for std_name, src_name in US_COLUMN_MAP.items():
        if src_name in df.columns:
            if std_name in text_columns:
                standard_df[std_name] = df[src_name].astype(str)
            else:
                standard_df[std_name] = pd.to_numeric(df[src_name], errors='coerce')

    # --- Derive clean Ticker (strip East Money exchange suffix, e.g. AAPL.OQ -> AAPL) ---
    if 'Ticker' in standard_df.columns:
        def clean_ticker(code):
            if not isinstance(code, str) or not code:
                return code
            return code.split('.')[0]
        standard_df['Ticker'] = standard_df['Ticker'].apply(clean_ticker)

    # --- Derive Exchange from suffix (e.g. AAPL.OQ -> NASDAQ) ---
    if 'Ticker' in standard_df.columns and '代码' in df.columns:
        def get_exchange(code):
            if not isinstance(code, str) or '.' not in code:
                return 'OTHER'
            suffix = code.split('.')[-1].upper()
            return EXCHANGE_SUFFIX_MAP.get(suffix, 'OTHER')
        # Build a temporary mapping from raw 代码 -> exchange
        raw_code = df['代码'].astype(str)
        exchange_series = raw_code.apply(get_exchange)
        standard_df['Exchange'] = exchange_series.values
    elif 'Ticker' in standard_df.columns:
        standard_df['Exchange'] = 'OTHER'

    # --- Sector (not provided by East Money US spot) ---
    standard_df['Sector'] = np.nan

    # --- RelVolume (not provided by East Money US spot) ---
    standard_df['RelVolume'] = np.nan

    # Initialize technical columns as NaN (not computed for US)
    for tech_col in TECHNICAL_COLUMNS:
        standard_df[tech_col] = np.nan

    # Safety: ensure core columns exist
    for col in ['Ticker', 'CompanyName', 'Price', 'ChangePercent', 'Volume', 'MarketCap']:
        if col not in standard_df.columns:
            standard_df[col] = np.nan

    logging.info(f"Normalized US data. Shape: {standard_df.shape}, Columns: {standard_df.columns.tolist()}")
    return standard_df


def get_us_screener_data(config_path='config/config.json', filter_weak_stocks=True):
    """
    Main entry point for US screener.
    Fetches data, applies filters, normalizes to standard schema.

    Returns:
        pd.DataFrame: Normalized DataFrame with standard column names, or empty DataFrame.
    """
    config = load_config(config_path)
    if not config:
        logging.error("Could not load configuration for US screener.")
        return pd.DataFrame()

    # Get US-specific filter config
    screener_config = config.get('us_screeners', {})
    filters_config = screener_config.get('filters', {})
    if not filters_config:
        # Fall back to global screeners.filters for common settings
        filters_config = config.get('screeners', {}).get('filters', {})

    # Fetch raw data
    raw_data = fetch_us_market_data(config)
    if raw_data is None or raw_data.empty:
        logging.warning("No US data fetched.")
        return pd.DataFrame()

    # Apply filters
    filtered_data = apply_filters(raw_data, filters_config)
    if filtered_data.empty:
        logging.info("No US stocks passed filter thresholds.")
        return pd.DataFrame()

    # Normalize to standard format
    normalized_data = normalize_to_standard(filtered_data)

    # Sort by absolute change percent descending (biggest movers first, both directions)
    if 'ChangePercent' in normalized_data.columns:
        normalized_data = normalized_data.copy()
        normalized_data['_abs'] = normalized_data['ChangePercent'].abs()
        normalized_data = normalized_data.sort_values('_abs', ascending=False).drop(columns=['_abs'])

    logging.info(f"US screener returning {len(normalized_data)} stocks.")
    return normalized_data


if __name__ == "__main__":
    logging.info("--- Testing US Screener ---")
    data = get_us_screener_data()
    if data is not None and not data.empty:
        print(f"\n--- US Screener Results ({len(data)} stocks) ---")
        display_cols = [c for c in ['Ticker', 'CompanyName', 'Exchange', 'Price', 'ChangePercent', 'Volume', 'MarketCap'] if c in data.columns]
        print(data[display_cols].head(20).to_string())
        print("--------------------------------------\n")
    else:
        print("No US data returned.")
