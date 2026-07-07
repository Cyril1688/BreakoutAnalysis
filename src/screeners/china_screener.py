"""
A-share (Chinese Stock Market) Screener
Uses akshare (East Money) to fetch A-share real-time data and technical indicators.

Market hours (China time, UTC+8):
- Morning: 9:30 - 11:30
- Afternoon: 13:00 - 15:00
- Pre-market auction: 9:15 - 9:25
"""

import json
import logging
import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
import socket
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - CHINA_SCREENER - %(levelname)s - %(message)s')

# ── 强制 IPv4 (避免 GitHub runner / 沙箱 IPv6 路由不可达导致 East Money 连接 reset) ──
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4
try:
    import urllib3.util.connection as _uc
    _uc.allowed_gai_family = lambda: socket.AF_INET
except Exception:
    pass

# China timezone
CHINA_TZ = pytz.timezone('Asia/Shanghai')

# Config path relative to project root
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.json')

# Column mapping for A-share data -> standard format
# Maps akshare (East Money) column names to standardized names matching COLUMN_MAP in screener_client.py
CHINA_COLUMN_MAP = {
    'Ticker': '代码',            # e.g., '600519'
    'CompanyName': '名称',       # e.g., '贵州茅台'
    'Price': '最新价',
    'ChangePercent': '涨跌幅',   # percentage, e.g., 2.35
    'ChangeAmount': '涨跌额',
    'Volume': '成交量',          # in shares
    'Turnover': '成交额',        # in Yuan
    'Amplitude': '振幅',
    'High': '最高',
    'Low': '最低',
    'Open': '今开',
    'PrevClose': '昨收',
    'VolumeRatio': '量比',
    'TurnoverRate': '换手率',
    'PE': '市盈率-动态',
    'PB': '市净率',
    'MarketCap': '总市值',
    'CirculatingMarketCap': '流通市值',
    'Speed': '涨速',
    'Change5Min': '5分钟涨跌',
    'Change60D': '60日涨跌幅',
    'ChangeYTD': '年初至今涨跌幅',
}

# Technical columns we'll compute
TECHNICAL_COLUMNS = ['RSI', 'SMA10', 'SMA20', 'SMA50', 'SMA100', 'SMA200', 'MACD_MACD', 'MACD_Signal', 'VWAP']


def load_config():
    """Loads the configuration from config.json"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logging.info("Configuration loaded successfully.")
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found at {CONFIG_PATH}")
        return None
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from the configuration file at {CONFIG_PATH}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading the config: {e}")
        return None


def get_technical_indicators(symbol, periods=250):
    """
    Calculate technical indicators from historical A-share data.
    Uses akshare to fetch daily history and computes SMA, RSI, MACD.
    """
    try:
        import akshare as ak
    except ImportError:
        logging.warning("akshare not installed. Technical indicators unavailable for A-shares.")
        return {}

    try:
        # Determine the correct akshare symbol format
        # A-share codes: 6xxxxx -> SH, 0xxxxx/3xxxxx -> SZ
        if symbol.startswith('6'):
            ak_symbol = f"{symbol}"
        else:
            ak_symbol = f"{symbol}"

        end_date = datetime.now()
        start_date = end_date - timedelta(days=periods + 60)  # Extra buffer

        hist = ak.stock_zh_a_hist(
            symbol=ak_symbol,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            end_date=end_date.strftime("%Y%m%d"),
            adjust="qfq"  # 前复权
        )

        if hist is None or hist.empty:
            logging.warning(f"No historical data for A-share {symbol}")
            return {}

        # Sort by date ascending for calculations
        hist = hist.sort_values('日期')
        closes = hist['收盘'].values.astype(float)
        highs = hist['最高'].values.astype(float)
        lows = hist['最低'].values.astype(float)
        volumes = hist['成交量'].values.astype(float)

        indicators = {}

        # SMA calculations
        if len(closes) >= 10:
            indicators['SMA10'] = float(np.mean(closes[-10:]))
        if len(closes) >= 20:
            indicators['SMA20'] = float(np.mean(closes[-20:]))
        if len(closes) >= 50:
            indicators['SMA50'] = float(np.mean(closes[-50:]))
        if len(closes) >= 100:
            indicators['SMA100'] = float(np.mean(closes[-100:]))
        if len(closes) >= 200:
            indicators['SMA200'] = float(np.mean(closes[-200:]))

        # RSI (14-day)
        if len(closes) >= 15:
            deltas = np.diff(closes[-15:])
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains)
            avg_loss = np.mean(losses)
            if avg_loss == 0:
                indicators['RSI'] = 100.0
            else:
                rs = avg_gain / avg_loss
                indicators['RSI'] = float(100 - (100 / (1 + rs)))

        # MACD (12, 26, 9)
        if len(closes) >= 26:
            ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values[-1]
            ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values[-1]
            macd_line = ema12 - ema26
            # Signal line (9-day EMA of MACD)
            macd_values = pd.Series(closes).ewm(span=12, adjust=False).mean() - pd.Series(closes).ewm(span=26, adjust=False).mean()
            signal_line = macd_values.ewm(span=9, adjust=False).mean().values[-1]
            indicators['MACD_MACD'] = float(macd_line)
            indicators['MACD_Signal'] = float(signal_line)

        # VWAP approximation (using all available data)
        if len(highs) > 0 and len(lows) > 0 and len(closes) > 0:
            typical_price = (highs[-1] + lows[-1] + closes[-1]) / 3
            if volumes[-1] > 0:
                indicators['VWAP'] = float(typical_price)

        return indicators

    except ImportError:
        logging.warning("akshare not available for technical analysis.")
        return {}
    except Exception as e:
        logging.error(f"Error calculating technical indicators for A-share {symbol}: {e}")
        return {}


def fetch_china_market_data(config):
    """
    Fetches A-share real-time data.
    Primary: akshare (East Money). Fallback: Sina + Tencent (for GitHub Actions / IP-blocked envs).
    Returns raw DataFrame with standard Chinese column names (兼容 apply_filters + normalize_to_standard).
    """

    # ── Primary: akshare (East Money) ──
    akshare_ok = False
    try:
        import akshare as ak
        akshare_ok = True
    except ImportError:
        logging.warning("akshare not installed, skipping East Money primary fetch.")

    if akshare_ok:
        try:
            logging.info("Fetching A-share real-time data from East Money (akshare)...")
            for attempt in range(3):
                try:
                    df = ak.stock_zh_a_spot_em()
                    if df is not None and not df.empty:
                        logging.info(f"Fetched {len(df)} A-share stocks from East Money.")
                        return df
                except Exception as e:
                    msg = str(e)
                    if attempt < 2:
                        logging.warning(f"East Money attempt {attempt+1} failed ({msg[:80]}); retrying...")
                        time.sleep(1.5 * (attempt + 1))
                    else:
                        logging.warning(f"East Money failed after 3 attempts ({msg[:120]}).")
        except Exception as e:
            logging.warning(f"East Money primary fetch error: {e}")

    # ── Fallback: Sina / Tencent ──
    logging.info("East Money unavailable. Falling back to Sina + Tencent...")
    try:
        # 用绝对导入而非相对导入（CI 环境下 `.sina_fetcher` 相对导入失败）
        from src.screeners.sina_fetcher import fetch_fallback_data
        df_fb = fetch_fallback_data()
        if df_fb is not None and not df_fb.empty:
            logging.info(f"Fetched {len(df_fb)} A-share stocks from Sina/Tencent (fallback).")
            return df_fb
        logging.warning("Fallback sources returned empty.")
    except ImportError:
        # 兜底：如果绝对导入也失败（例如作为独立脚本运行时），动态加路径
        try:
            import sys
            _fb_dir = os.path.dirname(os.path.abspath(__file__))
            if _fb_dir not in sys.path:
                sys.path.insert(0, _fb_dir)
            from sina_fetcher import fetch_fallback_data
            df_fb = fetch_fallback_data()
            if df_fb is not None and not df_fb.empty:
                logging.info(f"Fetched {len(df_fb)} A-share stocks from Sina/Tencent (fallback).")
                return df_fb
        except Exception as e2:
            logging.error(f"Fallback import (sys.path) also failed: {e2}", exc_info=True)
    except Exception as e:
        logging.error(f"Fallback source error: {e}", exc_info=True)

    logging.warning("All A-share data sources exhausted. Returning empty DataFrame.")
    return pd.DataFrame()


def apply_filters(df, filters_config):
    """
    Apply filter thresholds to A-share data.
    A-shares have daily price limits: 10% for main board, 20% for ChiNext(300)/STAR(688), 5% for ST.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    fc = filters_config or {}
    min_change = fc.get('china_min_change_percent', 5)
    min_volume = fc.get('china_min_volume', 1000000)  # in shares
    min_price = fc.get('china_min_price', 2.0)
    max_price = fc.get('china_max_price', 500.0)
    min_market_cap = fc.get('china_min_market_cap', 500000000)  # 5亿
    min_volume_ratio = fc.get('china_min_volume_ratio', 1.5)
    max_change = fc.get('china_max_change_percent', 15)  # Exclude stocks that hit limit up

    df_filtered = df.copy()

    # Apply filters
    # ChangePercent filter (涨跌幅)
    if '涨跌幅' in df_filtered.columns:
        df_filtered['涨跌幅'] = pd.to_numeric(df_filtered['涨跌幅'], errors='coerce')
        df_filtered = df_filtered[
            (df_filtered['涨跌幅'] >= min_change) &
            (df_filtered['涨跌幅'] <= max_change)
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

    # Volume ratio filter (量比)
    if '量比' in df_filtered.columns:
        df_filtered['量比'] = pd.to_numeric(df_filtered['量比'], errors='coerce')
        df_filtered = df_filtered[df_filtered['量比'] >= min_volume_ratio]

    logging.info(f"After A-share filters: {len(df_filtered)} stocks remain.")
    return df_filtered


def normalize_to_standard(df):
    """
    Normalize A-share DataFrame to standard column names matching COLUMN_MAP convention.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    standard_df = pd.DataFrame()

    # Map columns: CHINA_COLUMN_MAP defines {standard_name: source_name}
    # Text columns that should NOT be converted to numeric
    text_columns = {'Ticker', 'CompanyName'}
    
    for std_name, src_name in CHINA_COLUMN_MAP.items():
        if src_name in df.columns:
            if std_name in text_columns:
                standard_df[std_name] = df[src_name].astype(str)
            else:
                standard_df[std_name] = pd.to_numeric(df[src_name], errors='coerce')

    # Ensure Ticker is string
    if 'Ticker' in standard_df.columns:
        standard_df['Ticker'] = standard_df['Ticker'].astype(str).str.zfill(6)

    # Add Exchange column based on ticker prefix
    if 'Ticker' in standard_df.columns:
        def get_exchange(ticker):
            if ticker.startswith('6'):
                return 'SSE'  # Shanghai
            elif ticker.startswith('0') or ticker.startswith('3'):
                return 'SZSE'  # Shenzhen
            elif ticker.startswith('4') or ticker.startswith('8'):
                return 'BSE'  # Beijing
            return 'OTHER'
        standard_df['Exchange'] = standard_df['Ticker'].apply(get_exchange)

    # Add Sector placeholder (East Money spot data doesn't include sector directly)
    # We can infer from exchange/code
    if 'Ticker' in standard_df.columns:
        def infer_sector(ticker):
            if ticker.startswith('688'):
                return 'Technology Services'  # STAR board
            elif ticker.startswith('300'):
                return 'Electronic Technology'  # ChiNext
            elif ticker.startswith('60'):
                return 'Industrial'  # Shanghai main
            elif ticker.startswith('00'):
                return 'Industrial'  # Shenzhen main
            elif ticker.startswith('4') or ticker.startswith('8'):
                return 'Industrial'  # BSE
            return 'Other'
        standard_df['Sector'] = standard_df['Ticker'].apply(infer_sector)

    # RelVolume - use 量比 (volume ratio)
    if 'VolumeRatio' in standard_df.columns:
        standard_df['RelVolume'] = standard_df['VolumeRatio']

    logging.info(f"Normalized A-share data. Shape: {standard_df.shape}, Columns: {standard_df.columns.tolist()}")
    return standard_df


def enrich_with_technicals(df, max_stocks=30):
    """
    For the top stocks, fetch historical data and calculate technical indicators.
    Only processes top stocks to avoid rate limiting.
    """
    if df is None or df.empty:
        return df

    # Sort by ChangePercent descending and take top N
    if 'ChangePercent' in df.columns:
        df = df.sort_values('ChangePercent', ascending=False)

    # Limit how many stocks we compute technicals for
    stocks_to_process = df.head(max_stocks).copy()

    tech_data = {}
    for _, row in stocks_to_process.iterrows():
        ticker = row['Ticker']
        indicators = get_technical_indicators(ticker)
        if indicators:
            tech_data[ticker] = indicators

    # Add technical columns to the full DataFrame
    for tech_col in TECHNICAL_COLUMNS:
        df[tech_col] = np.nan

    for ticker, indicators in tech_data.items():
        for col, val in indicators.items():
            if col in df.columns:
                df.loc[df['Ticker'] == ticker, col] = val

    logging.info(f"Enriched {len(tech_data)} A-shares with technical indicators.")
    return df


def is_china_market_hours():
    """
    Check if current time is within A-share trading hours (China time).
    Morning: 9:30 - 11:30
    Afternoon: 13:00 - 15:00
    """
    now_china = datetime.now(CHINA_TZ)

    # Check weekday (Monday=0, Sunday=6)
    if now_china.weekday() >= 5:
        logging.info(f"Skipping: Weekend in China. Current time: {now_china.strftime('%A, %H:%M:%S')}")
        return False

    current_time = now_china.time()

    morning_start = datetime.strptime("09:30", "%H:%M").time()
    morning_end = datetime.strptime("11:30", "%H:%M").time()
    afternoon_start = datetime.strptime("13:00", "%H:%M").time()
    afternoon_end = datetime.strptime("15:00", "%H:%M").time()

    if morning_start <= current_time < morning_end:
        return True
    elif afternoon_start <= current_time < afternoon_end:
        return True

    logging.info(f"Skipping: Outside A-share trading hours. Current China time: {now_china.strftime('%H:%M:%S')}")
    return False


def get_china_screener_data(config_path='config/config.json', filter_weak_stocks=True):
    """
    Main entry point for A-share screener.
    Fetches data, applies filters, normalizes, and enriches with technicals.

    Returns:
        pd.DataFrame: Normalized DataFrame with standard column names, or empty DataFrame.
    """
    config = load_config()
    if not config:
        logging.error("Could not load configuration for China screener.")
        return pd.DataFrame()

    # Get China-specific filter config
    screener_config = config.get('china_screeners', {})
    filters_config = screener_config.get('filters', {})

    # Also fall back to global screeners.filters for common settings
    global_filters = config.get('screeners', {}).get('filters', {})
    if not filters_config:
        filters_config = global_filters

    # Fetch raw data
    raw_data = fetch_china_market_data(config)
    if raw_data is None or raw_data.empty:
        logging.warning("No A-share data fetched.")
        return pd.DataFrame()

    # Apply filters
    filtered_data = apply_filters(raw_data, filters_config)
    if filtered_data.empty:
        logging.info("No A-share stocks passed filter thresholds.")
        return pd.DataFrame()

    # Normalize to standard format
    normalized_data = normalize_to_standard(filtered_data)

    # Enrich with technical indicators for top stocks
    enriched_data = enrich_with_technicals(normalized_data, max_stocks=30)

    # Sort by change percent descending
    if 'ChangePercent' in enriched_data.columns:
        enriched_data = enriched_data.sort_values('ChangePercent', ascending=False)

    logging.info(f"China screener returning {len(enriched_data)} stocks.")
    return enriched_data


if __name__ == "__main__":
    logging.info("--- Testing China Screener ---")
    data = get_china_screener_data()
    if data is not None and not data.empty:
        print(f"\n--- A-Share Screener Results ({len(data)} stocks) ---")
        display_cols = [c for c in ['Ticker', 'CompanyName', 'Price', 'ChangePercent', 'Volume', 'MarketCap', 'RelVolume', 'RSI', 'SMA20', 'SMA50'] if c in data.columns]
        print(data[display_cols].head(20).to_string())
        print("--------------------------------------\n")
    else:
        print("No A-share data returned.")
