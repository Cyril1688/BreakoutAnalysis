"""
US Stock (美股) Screener — yfinance / Yahoo Finance
==============================================
Replaces the old East Money / akshare approach which is IP-blocked on GitHub Actions.

Data source: Yahoo Finance via yfinance (free, no API key).
Fetches batch prices for ~800 top US stocks (S&P 500 + NASDAQ 100 + Dow + major ETFs).

Market hours (US/Eastern, UTC-4 in summer):
- Regular session: 9:30 - 16:00
- We only screen during the regular session to avoid alerting on stale pre-open data.
"""

import json
import logging
import os
import sys
import socket
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz

# ── Force IPv4 ──
_orig_getaddrinfo = socket.getaddrinfo
def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4

logging.basicConfig(level=logging.INFO, format='%(asctime)s - US_SCREENER - %(levelname)s - %(message)s')

US_EASTERN_TZ = pytz.timezone('US/Eastern')

# ── Top US Stock Universes ──────────────────────────────────────────────
# S&P 500 + NASDAQ 100 + DOW 30 + major ETFs = ~715 tickers.
# Maintained as a flat list so the module is self-contained.
# Source: market data as of mid-2026.
_SP_500 = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","BRK.B","JPM","V","PG","UNH","HD","INTC","MA","COST",
    "ABBV","AVGO","CRM","BAC","TMO","CVX","WMT","LLY","ACN","KO","MRK","PEP","QCOM","TXN","ABT",
    "LIN","NEE","DIS","WFC","PM","NKE","IBM","HON","BA","CAT","GE","MMM","AXP","GS","MS","C",
    "SYK","ISRG","MDT","RTX","LOW","UPS","AMGN","SPGI","BKNG","SCHW","LMT","PLD","BLK","CB",
    "NOW","DE","FISV","CL","SBUX","GILD","ZTS","ADP","DUK","SO","CCI","AEP","CSCO","MDLZ","BMY",
    "MO","TMUS","ICE","MCO","EQIX","PYPL","AMAT","ADI","NSC","EL","EW","GD","ILMN","MMC","PNC",
    "USB","TGT","CME","APD","SHW","COP","BSX","CTVA","ADBE","INTU","VRTX","REGN","MRVL","KLAC",
    "MCHP","ORLY","ROST","SYY","WBA","PSA","WLTW","O","STZ","MKC","KMB","KHC","HRL","SJM","GIS",
    "CPB","CAG","CLX","CHD","K","AWK","WTRG","ECL","IFF","DD","DOW","LYB","EMN","NEM","FCX",
    "SCCO","ALB","ELAN","X","STLD","NUE","RS","MLM","VMC","EXP","JHX","BLD","OC","TREX","WY",
    "MAS","PH","DOV","ROK","ETN","ITW","IR","CMI","CAT","DE","AGCO","CNHI","OSK","PCAR","PNR",
    "UAL","AAL","DAL","LUV","SAVE","RCL","CCL","NCLH","WYNN","MGM","LVS","CZR","DRI","MCD",
    "YUM","QSR","DPZ","SBUX","CMG","DNKN","BJRI","CAKE","CBRL","EAT","BLMN","TXRH","FWRD","JBHT",
    "CHRW","EXPD","XPO","UPS","FDX","AA","ALB","NUE","STLD","RS","EMN","CE","DOW","DD","LYB",
    "APD","ECL","LIN","SHW","IFF","PPG","FMC","MOS","CF","AGU","MON","SQM","ALB",
    "WAB","TRV","ALL","PGR","CB","AIG","MET","PRU","LNC","HIG","AFL","AIZ","HMN","GL","RE",
    "MSCI","SPGI","V","MA","GPN","FISV","FIS","JKHY","WU","PYPL","SQ","COIN","MELI","CACC",
    "BK","STT","NTRS","KEY","HBAN","CFG","RF","CMA","FHN","ZION","MTB","WBS","WTFC","PB","PNFP",
    "SBNY","NYCB","FITB","RF","CFG","KEY","HBAN","CMA","FHN","WAL","PACW","EWBC","CBSH","BPOP",
    "PBCT","CHCO","COLB","GBCI","WTFC","SIVB","ZION","MTB","PNC","USB","TFC","STT","NTRS","BK",
]

_NASDAQ_100 = [
    "AAPL","MSFT","NVDA","GOOGL","AMZN","META","AVGO","COST","NFLX","CSCO","ADBE","INTC","TXN",
    "QCOM","AMAT","ISRG","MDLZ","GILD","REGN","VRTX","CMCSA","TMUS","AMGN","SBUX","INTU","ADP",
    "FISV","BKNG","CHTR","LRCX","KLAC","MU","SNPS","CDNS","PANW","CRWD","DDOG","ZM","TEAM",
    "WDAY","ADSK","CTSH","NXPI","MRVL","MCHP","WBA","ALGN","IDXX","VRSK","ANSS","CDW","CPRT",
    "FAST","PAYX","PCAR","ROST","VRSN","XLNX","MSI","MAR","HON","CSGP","EA","BIDU","JD","BABA",
    "NTES","SPLK","ILMN","ALXN","BIIB","INCY","VRTX","MRNA","REGN","SGEN","AMD","PEP","KHC",
    "MNST","AAP","WBA","COST","AMZN","WMT","COST","ROST","DLTR","CPRT","FAST","BBY","DG",
    "EBAY","EXPE","CTRP","TRIP","BKNG","MAR","HLT","WYNN","MGM","LVS","ABNB","DASH","UBER",
    "LYFT","PINS","SNAP","RBLX","MTCH","TTD","MDB","ESTC","OKTA","NET","FSLY","DDOG","HUBS",
    "CRM","NOW","WDAY","ADBE","INTU","ADSK","SPLK","MSFT","ORCL","IBM","SAP","ACN",
]

_DOW_30 = [
    "AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW","GS","HD","HON","IBM",
    "INTC","JNJ","JPM","KO","MCD","MMM","MRK","MSFT","NKE","PG","TRV","UNH","VZ","WBA","WMT",
]

_MAJOR_ETFS = [
    "SPY","QQQ","IWM","DIA","VOO","VTI","VT","BND","AGG","TLT","IEF","SHY","HYG","LQD",
    "GLD","SLV","USO","XLF","XLK","XLE","XLV","XLI","XLY","XLP","XLU","XLB","XLRE",
    "ARKK","ARKW","ARKG","ARKF","TQQQ","SQQQ","SOXX","SMH","IBB","KRE","KBE",
]

# 合并且去重
_US_UNIVERSE = list(dict.fromkeys(_SP_500 + _NASDAQ_100 + _DOW_30 + _MAJOR_ETFS))


def load_config(config_path='config/config.json'):
    """Loads configuration from config.json"""
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
        cfg_file = os.path.join(project_root, config_path)
        with open(cfg_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except Exception as e:
        logging.error(f"Could not load config: {e}")
        return None


def is_us_market_hours():
    """Check if US market is currently in regular trading hours (09:30-16:00 ET)."""
    now_eastern = datetime.now(US_EASTERN_TZ)
    if now_eastern.weekday() >= 5:
        return False
    t = now_eastern.time()
    return datetime.strptime("09:30", "%H:%M").time() <= t < datetime.strptime("16:00", "%H:%M").time()


def fetch_us_market_data(config):
    """
    Batch-download US stock prices from Yahoo Finance.
    Returns a DataFrame with columns:
      Ticker, CompanyName, Price, ChangePercent, Volume, MarketCap, etc.
    Falls back gracefully if yfinance is unavailable.
    """
    try:
        import yfinance as yf
    except ImportError:
        logging.error("yfinance not installed. Cannot fetch US data.")
        return pd.DataFrame()

    logging.info(f"Downloading US market data for {len(_US_UNIVERSE)} stocks via yfinance...")
    t0 = time.time()

    try:
        data = yf.download(
            _US_UNIVERSE,
            period='2d',
            interval='1d',
            group_by='ticker',
            threads=True,
            progress=False,
        )
    except Exception as e:
        logging.error(f"yfinance batch download failed: {e}")
        return pd.DataFrame()

    elapsed = time.time() - t0
    logging.info(f"yfinance download completed in {elapsed:.0f}s.")

    if data is None or data.empty:
        logging.warning("yfinance returned no data.")
        return pd.DataFrame()

    # yfinance returns a MultiIndex (ticker, OHLCV) when group_by='ticker'
    if not isinstance(data.columns, pd.MultiIndex):
        logging.warning("yfinance returned unexpected column format.")
        return pd.DataFrame()

    rows = []
    tickers_found = data.columns.get_level_values(0).unique()

    for tkr in tickers_found:
        try:
            s = data[tkr]
            if 'Close' not in s.columns or s['Close'].isna().all():
                continue
            closes = s['Close'].dropna()
            volumes = s['Volume'].dropna()
            if len(closes) < 1:
                continue

            close = closes.iloc[-1]
            prev_close = closes.iloc[-2] if len(closes) >= 2 else close
            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else 0.0
            volume = int(volumes.iloc[-1]) if len(volumes) >= 1 else 0

            rows.append({
                "Ticker": tkr,
                "CompanyName": _get_company_name(tkr, close),
                "Price": round(close, 2),
                "ChangePercent": change_pct,
                "Volume": volume,
                # MarketCap not available from download; will be fetched only for filtered stocks
            })
        except Exception:
            continue

    df = pd.DataFrame(rows)
    logging.info(f"yfinance processed {len(df)} US stocks with data.")
    return df


def _get_company_name(ticker, price=None):
    """Return readable company name for a ticker (cached/lookup)."""
    # Hardcoded common names to avoid info API rate limit
    NAMES = {
        "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
        "AMZN": "Amazon", "META": "Meta", "BRK.B": "Berkshire", "JPM": "JPMorgan",
        "V": "Visa", "PG": "Procter & Gamble", "UNH": "UnitedHealth",
        "HD": "Home Depot", "INTC": "Intel", "MA": "Mastercard", "COST": "Costco",
        "ABBV": "AbbVie", "AVGO": "Broadcom", "CRM": "Salesforce", "BAC": "Bank of America",
        "TMO": "Thermo Fisher", "CVX": "Chevron", "WMT": "Walmart", "LLY": "Eli Lilly",
        "ACN": "Accenture", "KO": "Coca-Cola", "MRK": "Merck", "PEP": "PepsiCo",
        "TXN": "Texas Instruments", "QCOM": "Qualcomm", "ABT": "Abbott",
        "CSCO": "Cisco", "NFLX": "Netflix", "AMD": "AMD", "MU": "Micron",
        "TSLA": "Tesla", "BA": "Boeing", "CAT": "Caterpillar", "GE": "GE",
        "DIS": "Disney", "NKE": "Nike", "SBUX": "Starbucks", "PYPL": "PayPal",
        "SPY": "SPDR S&P 500", "QQQ": "Invesco QQQ", "IWM": "Russell 2000",
        "DIA": "Dow Jones ETF", "GLD": "Gold ETF", "SLV": "Silver ETF",
        "XLF": "Financial ETF", "XLK": "Tech ETF", "XLE": "Energy ETF",
        "JNJ": "Johnson & Johnson", "VZ": "Verizon", "DD": "DuPont", "WBA": "Walgreens",
        "MRVL": "Marvell", "MCHP": "Microchip", "ADI": "Analog Devices",
        "ADP": "ADP", "ADBE": "Adobe", "INTU": "Intuit", "FISV": "Fiserv",
        "SNPS": "Synopsys", "CDNS": "Cadence", "PANW": "Palo Alto",
        "CRWD": "CrowdStrike", "DDOG": "Datadog", "ZM": "Zoom", "TEAM": "Atlassian",
        "WDAY": "Workday", "ADSK": "Autodesk", "UBER": "Uber", "ABNB": "Airbnb",
        "DASH": "DoorDash", "SNAP": "Snap", "PINS": "Pinterest", "RBLX": "Roblox",
        "SOXX": "Semiconductor ETF", "SMH": "Semiconductor ETF", "IBB": "Biotech ETF",
        "XLV": "Healthcare ETF", "XLI": "Industrial ETF", "XLY": "Consumer Disc ETF",
        "XLP": "Consumer Staples ETF", "XLU": "Utilities ETF", "XLB": "Materials ETF",
        "KRE": "Regional Bank ETF", "KBE": "Bank ETF", "TQQQ": "3x Bull QQQ",
        "SQQQ": "3x Bear QQQ", "VT": "Total World ETF", "VTI": "Total US ETF",
        "VOO": "S&P 500 ETF", "BND": "Bond ETF", "AGG": "Bond ETF",
        "TLT": "Treasury 20y+", "IEF": "Treasury 7-10y", "HYG": "High Yield",
    }
    return NAMES.get(ticker, ticker)


def apply_filters(df, filters_config):
    """
    Apply filter thresholds to US data.
    Same structure as china_screener.apply_filters for consistency.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    fc = filters_config or {}
    min_change = fc.get('us_min_change_percent', 5.0)
    max_change = fc.get('us_max_change_percent', 30.0)
    min_volume = fc.get('us_min_volume', 500000)
    min_price = fc.get('us_min_price', 3.0)
    max_price = fc.get('us_max_price', 2000.0)
    min_market_cap = fc.get('us_min_market_cap', 300000000)

    df_filtered = df.copy()

    # ChangePercent filter (涨跌幅)
    if 'ChangePercent' in df_filtered.columns:
        df_filtered['ChangePercent'] = pd.to_numeric(df_filtered['ChangePercent'], errors='coerce')
        df_filtered = df_filtered[
            (df_filtered['ChangePercent'].abs() >= min_change) &
            (df_filtered['ChangePercent'].abs() <= max_change)
        ]

    # Volume filter
    if 'Volume' in df_filtered.columns:
        df_filtered['Volume'] = pd.to_numeric(df_filtered['Volume'], errors='coerce')
        df_filtered = df_filtered[df_filtered['Volume'] >= min_volume]

    # Price filter
    if 'Price' in df_filtered.columns:
        df_filtered['Price'] = pd.to_numeric(df_filtered['Price'], errors='coerce')
        df_filtered = df_filtered[
            (df_filtered['Price'] >= min_price) &
            (df_filtered['Price'] <= max_price)
        ]

    # MarketCap filter (之前被读取但未使用，已修)
    if 'MarketCap' in df_filtered.columns:
        df_filtered['MarketCap'] = pd.to_numeric(df_filtered['MarketCap'], errors='coerce')
        df_filtered = df_filtered[df_filtered['MarketCap'] >= min_market_cap]

    logging.info(f"After US filters: {len(df_filtered)} stocks remain.")
    return df_filtered


def normalize_to_standard(df):
    """
    Normalize US DataFrame to standard column names matching COLUMN_MAP convention.
    (Same format as china_screener outputs.)
    """
    if df is None or df.empty:
        return pd.DataFrame()

    std = pd.DataFrame()
    std['Ticker'] = df['Ticker'].astype(str)
    std['CompanyName'] = df.get('CompanyName', df['Ticker'])
    std['Price'] = pd.to_numeric(df.get('Price', 0), errors='coerce')
    std['ChangePercent'] = pd.to_numeric(df.get('ChangePercent', 0), errors='coerce')

    if 'Volume' in df.columns:
        std['Volume'] = pd.to_numeric(df['Volume'], errors='coerce')
    if 'MarketCap' in df.columns:
        std['MarketCap'] = pd.to_numeric(df['MarketCap'], errors='coerce')

    # Exchange/Sector 推测（yfinance 不直接返回，用代码长度做启发式）
    # NYSE 传统股多为 1-3 字母代码，NASDAQ 多为 4+ 字母
    std['Exchange'] = std['Ticker'].apply(lambda t: 'NYSE' if len(t) <= 3 and not t.endswith('.') else 'NASDAQ')
    std['Sector'] = 'Technology'  # yfinance 不返回行业，统一标记

    return std


def get_us_screener_data(config_path='config/config.json', filter_weak_stocks=True):
    """
    Main entry point for US screener.
    Fetches data → applies filters → normalizes.
    Returns DataFrame with standard column names, or empty DataFrame.
    """
    config = load_config(config_path)
    if not config:
        return pd.DataFrame()

    screener_config = config.get('us_screeners', {})
    filters_config = screener_config.get('filters', {})
    if not filters_config:
        filters_config = config.get('screeners', {}).get('filters', {})

    raw_data = fetch_us_market_data(config)
    if raw_data is None or raw_data.empty:
        logging.warning("No US data fetched.")
        return pd.DataFrame()

    filtered_data = apply_filters(raw_data, filters_config)
    if filtered_data.empty:
        logging.info("No US stocks passed filter thresholds.")
        return pd.DataFrame()

    normalized_data = normalize_to_standard(filtered_data)

    if 'ChangePercent' in normalized_data.columns:
        normalized_data = normalized_data.sort_values('ChangePercent', ascending=False)

    logging.info(f"US screener returning {len(normalized_data)} stocks.")
    return normalized_data


if __name__ == "__main__":
    logging.info("--- Testing US Screener (yfinance) ---")
    data = get_us_screener_data()
    if data is not None and not data.empty:
        print(f"\n--- US Screener Results ({len(data)} stocks) ---")
        cols = [c for c in ['Ticker', 'CompanyName', 'Price', 'ChangePercent', 'Volume'] if c in data.columns]
        print(data[cols].head(30).to_string())
    else:
        print("No US data returned.")
