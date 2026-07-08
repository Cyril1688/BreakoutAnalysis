import logging
import pandas as pd
from datetime import datetime
import pytz
import argparse
import os
import sys
import json # Added for JSON output

# Add the src directory to sys.path to allow importing sibling modules
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.append(SRC_DIR)

# Import fetch functions from the specific screeners (non-fatal - US can be disabled)
# Primary: akshare-based us_screener (no API keys required)
US_SCREENER_MODE = None
try:
    from us_screener import get_us_screener_data, is_us_market_hours
    US_SCREENER_AVAILABLE = True
    US_SCREENER_MODE = 'akshare'
    logging.info("Successfully imported US screener (akshare-based, no API keys).")
except ImportError as e:
    # Fallback: legacy TradingView-based screeners (require TV cookies/account)
    try:
        from market_gainers import fetch_screener_data as fetch_market_data, load_config as load_market_config
        from premarket_gappers import fetch_screener_data as fetch_premarket_data, load_config as load_premarket_config
        US_SCREENER_AVAILABLE = True
        US_SCREENER_MODE = 'tradingview'
        logging.info("Successfully imported legacy US screener (TradingView-based).")
    except ImportError as e2:
        US_SCREENER_AVAILABLE = False
        fetch_market_data = None
        fetch_premarket_data = None
        load_market_config = None
        load_premarket_config = None
        get_us_screener_data = None
        is_us_market_hours = None
        logging.error(f"Failed to import US screener functions: {e2}")
        logging.warning("US market monitoring will be disabled.")

# Import China screener (optional - gracefully degrade if not available)
try:
    from china_screener import get_china_screener_data, is_china_market_hours
    CHINA_SCREENER_AVAILABLE = True
    logging.info("Successfully imported China screener (A-share).")
except ImportError as e:
    CHINA_SCREENER_AVAILABLE = False
    logging.warning(f"China screener not available: {e}. A-share monitoring disabled.")

# Import Alpaca Client for historical data
try:
    # Adjust path assuming utils is a sibling directory to screeners
    UTILS_DIR = os.path.abspath(os.path.join(SRC_DIR, '../utils'))
    if UTILS_DIR not in sys.path:
        sys.path.append(UTILS_DIR)
    from alpaca_client import AlpacaClient
    logging.info("Successfully imported AlpacaClient.")
except ImportError as e:
    logging.error(f"Failed to import AlpacaClient: {e}")
    logging.error("Ensure alpaca_client.py is in the src/utils directory.")
    # Decide if this is fatal. For now, we might allow running without filtering.
    AlpacaClient = None # Set to None if import fails

# Configure logging
# Move logging config up slightly to catch import errors better if needed
logging.basicConfig(level=logging.INFO, format='%(asctime)s - SCREENER_CLIENT - %(levelname)s - %(message)s')

# Define the US Eastern timezone
EASTERN_TZ = pytz.timezone('US/Eastern')

# --- Column Normalization Mapping ---
# Define a standard set of column names we want in the final output.
# Map the API field names from all screeners to these standard names.
# Note: Some fields might only exist in certain screener types.
COLUMN_MAP = {
    # Standard Name : { 'market': api_field_market, 'premarket': api_field_premarket } # Removed 'postmarket'
    'Ticker':           {'market': 'name', 'premarket': 'name'},
    'Exchange':         {'market': 'exchange', 'premarket': 'exchange'},
    'CompanyName':      {'market': 'description', 'premarket': 'description'},
    'Price':            {'market': 'close', 'premarket': 'premarket_close'}, # Use session-specific price if available
    'ChangePercent':    {'market': 'change', 'premarket': 'premarket_change'}, # Use session-specific change if available
    'Volume':           {'market': 'volume', 'premarket': 'premarket_volume'}, # Use session-specific volume if available
    'MarketCap':        {'market': 'market_cap_basic', 'premarket': 'market_cap_basic'},
    'Sector':           {'market': 'sector', 'premarket': 'sector'},
    'RelVolume':        {'market': 'relative_volume_10d_calc', 'premarket': 'relative_volume_10d_calc'},
    'PrevClose':        {'market': 'close', 'premarket': 'close'}, # Previous day's close (regular session close)
    'RegularChangePercent': {'market': 'change', 'premarket': 'change'}, # Regular session change
    'RegularVolume':    {'market': 'volume', 'premarket': 'volume'}, # Regular session volume
    'PE':               {'market': 'price_earnings_ttm', 'premarket': 'price_earnings_ttm'},
    'EPS':              {'market': 'earnings_per_share_basic_ttm', 'premarket': 'earnings_per_share_basic_ttm'},
    'AnalystRating':    {'market': 'Recommend.All', 'premarket': 'Recommend.All'},
    'LogoID':           {'market': 'logoid', 'premarket': 'logoid'},
    # Technical Indicators (assuming names are consistent if available)
    'RSI':              {'market': 'RSI', 'premarket': 'RSI'},
    'SMA10':            {'market': 'SMA10', 'premarket': 'SMA10'},
    'SMA20':            {'market': 'SMA20', 'premarket': 'SMA20'},
    'SMA50':            {'market': 'SMA50', 'premarket': 'SMA50'},
    'SMA100':           {'market': 'SMA100', 'premarket': 'SMA100'},
    'SMA200':           {'market': 'SMA200', 'premarket': 'SMA200'},
    'MACD_MACD':        {'market': 'MACD.macd', 'premarket': 'MACD.macd'},
    'MACD_Signal':      {'market': 'MACD.signal', 'premarket': 'MACD.signal'},
    'VWAP':             {'market': 'VWAP', 'premarket': 'VWAP'},
    'Pivot_S1':         {'market': 'Pivot.M.Classic.S1', 'premarket': 'Pivot.M.Classic.S1'},
    'Pivot_S2':         {'market': 'Pivot.M.Classic.S2', 'premarket': 'Pivot.M.Classic.S2'},
    'Pivot_S3':         {'market': 'Pivot.M.Classic.S3', 'premarket': 'Pivot.M.Classic.S3'},
    'Pivot_R1':         {'market': 'Pivot.M.Classic.R1', 'premarket': 'Pivot.M.Classic.R1'},
    'Pivot_R2':         {'market': 'Pivot.M.Classic.R2', 'premarket': 'Pivot.M.Classic.R2'},
    'Pivot_R3':         {'market': 'Pivot.M.Classic.R3', 'premarket': 'Pivot.M.Classic.R3'},
}

def is_premarket_hours(current_time_eastern):
    """Checks if the current Eastern time is before 9:30 AM."""
    # Market opens at 9:30 AM Eastern Time
    market_open_hour = 9
    market_open_minute = 30
    return current_time_eastern.time() < datetime.strptime(f"{market_open_hour}:{market_open_minute}", "%H:%M").time()

# Removed is_postmarket_hours function

def normalize_dataframe(df, screener_type):
    """
    Normalizes the DataFrame columns based on the screener type,
    prioritizing primary mappings like Price, Volume, ChangePercent.
    """
    if df is None or df.empty:
        return pd.DataFrame() # Return empty DataFrame if input is None or empty

    rename_map = {}
    potential_columns = set() # Keep track of standard names we *could* have based on map and df

    # First pass: build initial rename map (last entry for a source field wins)
    # Also track all potential standard columns based on the map and available source fields
    for standard_name, source_map in COLUMN_MAP.items():
        source_field = source_map.get(screener_type)
        if source_field and source_field in df.columns:
            rename_map[source_field] = standard_name
            potential_columns.add(standard_name)
        elif source_field: # If source field defined in map but not in df, still add standard_name to potential
             potential_columns.add(standard_name)

    # Define priority mappings: Standard Name -> Source Field Map
    priority_mappings = {
        'Price': COLUMN_MAP['Price'],
        'Volume': COLUMN_MAP['Volume'],
        'ChangePercent': COLUMN_MAP['ChangePercent'],
    }

    # Second pass: Ensure priority mappings overwrite others if source field exists
    for standard_name, source_map in priority_mappings.items():
         source_field = source_map.get(screener_type)
         if source_field and source_field in df.columns:
             # Force the mapping for this priority field
             rename_map[source_field] = standard_name
             potential_columns.add(standard_name) # Ensure it's considered potential

    # Rename columns based on the corrected map
    df_renamed = df.rename(columns=rename_map)

    # Select and reorder columns based on the original COLUMN_MAP order
    # Filter this order to only include columns that are actually present in df_renamed
    # and were considered potential based on the mapping and df content.
    final_columns_ordered = [
        col for col in COLUMN_MAP.keys()
        if col in potential_columns and col in df_renamed.columns
    ]

    # Create the final DataFrame with the correct columns in the desired order
    final_df = df_renamed[final_columns_ordered]

    logging.info(f"Normalized DataFrame. Shape: {final_df.shape}, Columns: {final_df.columns.tolist()}")
    return final_df

def filter_stocks_by_history(df, alpaca_client):
    """
    Filters the DataFrame based on historical price change rules.

    Args:
        df (pd.DataFrame): The normalized DataFrame with a 'Ticker' column.
        alpaca_client (AlpacaClient): An initialized AlpacaClient instance.

    Returns:
        pd.DataFrame: The filtered DataFrame.
    """
    if alpaca_client is None:
        logging.warning("AlpacaClient not available. Skipping historical filtering.")
        return df
    if df.empty:
        logging.info("Input DataFrame is empty. No filtering needed.")
        return df
    if 'Ticker' not in df.columns:
        logging.error("DataFrame must contain a 'Ticker' column for filtering.")
        return pd.DataFrame() # Return empty if no Ticker

    logging.info(f"Starting historical filtering on {len(df)} stocks...")
    tickers_to_keep = []
    processed_count = 0

    for index, row in df.iterrows():
        ticker = row['Ticker']
        processed_count += 1
        logging.debug(f"Processing ({processed_count}/{len(df)}): {ticker}")

        try:
            # Rule 0: If price is above SMA200, include the stock regardless of other rules
            if 'Price' in df.columns and 'SMA200' in df.columns and row['Price'] > row['SMA200']:
                logging.info(f"KEEPING {ticker}: Price ({row['Price']}) is above SMA200 ({row['SMA200']}).")
                tickers_to_keep.append(ticker)
                continue

            # Get historical price changes using the simplified implementation
            hist_data = alpaca_client.get_historical_price_change(ticker)

            if hist_data.get('error'):
                logging.warning(f"Could not get historical data for {ticker}: {hist_data['error']}. Keeping stock.")
                tickers_to_keep.append(ticker)
                continue

            change_1y = hist_data.get('change_1y')
            change_5y = hist_data.get('change_5y')

            # Rule 1: Filter OUT if lost > 70% in 1 year
            if change_1y is not None and change_1y < -70:
                logging.info(f"Filtering OUT {ticker}: 1Y change ({change_1y:.2f}%) < -70%.")
                continue # Filter out

            # Rule 2: Filter OUT if lost > 80% in 5 years
            # Exception: Keep if 1Y change > 0%
            if change_5y is not None and change_5y < -80:
                is_trending_positive_1y = change_1y is not None and change_1y > 0
                if not is_trending_positive_1y:
                    logging.info(f"Filtering OUT {ticker}: 5Y change ({change_5y:.2f}%) < -80% AND 1Y change not positive.")
                    continue # Filter out
                else:
                    logging.info(f"KEEPING {ticker} despite 5Y loss ({change_5y:.2f}%): 1Y change ({change_1y:.2f}%) is positive.")

            # If not filtered out by any rule, keep it
            tickers_to_keep.append(ticker)

        except Exception as e:
            logging.error(f"Unexpected error filtering {ticker}: {e}. Keeping stock.")
            tickers_to_keep.append(ticker) # Keep stock if filtering fails unexpectedly

    filtered_df = df[df['Ticker'].isin(tickers_to_keep)].copy()
    logging.info(f"Finished historical filtering. Kept {len(filtered_df)} out of {len(df)} stocks.")
    return filtered_df


def get_market_config(project_root=None):
    """Read which markets are enabled from config.json"""
    if project_root is None:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
    config_path = os.path.join(project_root, 'config', 'config.json')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        markets_config = config.get('markets', {'us': True, 'china': False})
        logging.info(f"Market config: US={'enabled' if markets_config.get('us', True) else 'disabled'}, "
                     f"China={'enabled' if markets_config.get('china', False) else 'disabled'}")
        return markets_config
    except Exception as e:
        logging.warning(f"Could not read market config ({e}). Defaulting to US only.")
        return {'us': True, 'china': False}


def get_all_screener_data(config_path='config/config.json', filter_weak_stocks=True):
    """
    Fetches screener data for ALL enabled markets.
    Returns a dict: {'us': pd.DataFrame, 'china': pd.DataFrame}
    """
    result = {'us': pd.DataFrame(), 'china': pd.DataFrame()}

    markets = get_market_config()

    # --- US Market ---
    if markets.get('us', True):
        if not US_SCREENER_AVAILABLE:
            logging.info("US screener not available. Skipping US market.")
        elif US_SCREENER_MODE == 'akshare':
            logging.info("=== Fetching US market screener data (akshare) ===")
            try:
                if is_us_market_hours():
                    us_data = get_us_screener_data(config_path=config_path, filter_weak_stocks=filter_weak_stocks)
                    result['us'] = us_data if us_data is not None else pd.DataFrame()
                    logging.info(f"US screener returned {len(result['us'])} stocks.")
                else:
                    logging.info("US market is closed (outside 09:30-16:00 ET). Skipping US screener.")
            except Exception as e:
                logging.error(f"Error fetching US screener data: {e}")
                result['us'] = pd.DataFrame()
        else:
            # Legacy TradingView-based path
            logging.info("=== Fetching US market screener data (TradingView legacy) ===")
            try:
                us_data = get_screener_data(config_path=config_path, filter_weak_stocks=filter_weak_stocks)
                result['us'] = us_data if us_data is not None else pd.DataFrame()
                logging.info(f"US screener returned {len(result['us'])} stocks.")
            except Exception as e:
                logging.error(f"Error fetching US screener data: {e}")
    else:
        logging.info("US market monitoring is disabled in config.")

    # --- China A-Share Market ---
    if markets.get('china', False):
        if CHINA_SCREENER_AVAILABLE:
            logging.info("=== Fetching China A-share screener data ===")
            try:
                # Check if it's China market hours
                if is_china_market_hours():
                    china_data = get_china_screener_data(config_path=config_path, filter_weak_stocks=filter_weak_stocks)
                    result['china'] = china_data if china_data is not None else pd.DataFrame()
                    logging.info(f"China screener returned {len(result['china'])} stocks.")
                else:
                    logging.info("China market is closed. Skipping A-share screener.")
            except Exception as e:
                logging.error(f"Error fetching China screener data: {e}")
        else:
            logging.warning("China screener module not available. Install akshare and restart.")
    else:
        logging.info("China A-share market monitoring is disabled in config.")

    return result


def get_screener_data(config_path='config/config.json', filter_weak_stocks=True):
    """
    Fetches data from the appropriate screener based on the time of day
    and returns a normalized DataFrame.
    """
    # Determine current time in US/Eastern
    now_utc = datetime.now(pytz.utc)
    now_eastern = now_utc.astimezone(EASTERN_TZ)
    logging.info(f"Current time in US/Eastern: {now_eastern.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")

    config = None
    raw_data = None
    screener_type = None
    config = None

    if not US_SCREENER_AVAILABLE:
        logging.warning("US screener not available. Skipping US market data.")
        return pd.DataFrame()

    if is_premarket_hours(now_eastern):
        logging.info("Current time is during pre-market hours. Fetching pre-market gappers.")
        screener_type = 'premarket'
        config = load_premarket_config()
        if config:
            raw_data = fetch_premarket_data(config)
        else:
            logging.error("Failed to load pre-market configuration.")
            return pd.DataFrame() # Return empty DataFrame on config error

    # Removed postmarket logic block
    # elif is_postmarket_hours(now_eastern):
    #     ...

    else: # Regular market hours
        logging.info("Current time is during regular market hours. Fetching market gainers.")
        screener_type = 'market'
        config = load_market_config()
        if config:
            raw_data = fetch_market_data(config)
        else:
            logging.error("Failed to load market configuration.")
            return pd.DataFrame() # Return empty DataFrame on config error

    # Normalize the data only if raw_data is not None
    normalized_data = pd.DataFrame() # Initialize as empty
    if raw_data is not None and not raw_data.empty:
        normalized_data = normalize_dataframe(raw_data, screener_type)
    elif raw_data is not None and raw_data.empty:
         logging.info(f"No raw data matched screener criteria for type: {screener_type}. Returning empty DataFrame.")
         return pd.DataFrame() # Return empty if screener found nothing
    else:
        logging.warning(f"No raw data fetched for screener type: {screener_type}. Returning empty DataFrame.")
        return pd.DataFrame() # Return empty if fetch failed

    # --- Apply Historical Filtering ---
    if not normalized_data.empty and filter_weak_stocks:
        alpaca_client = None
        if AlpacaClient: # Check if import succeeded
            try:
                # Adjust config path relative to project root for AlpacaClient
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
                alpaca_config_path = os.path.join(project_root, config_path)
                alpaca_client = AlpacaClient(config_path=alpaca_config_path)
            except ValueError as e:
                logging.warning(
                    f"Alpaca API credentials not configured — historical stock filtering will be skipped. "
                    f"Set alpaca.api_key and alpaca.api_secret in config/config.json to enable. ({e})"
                )
            except Exception as e:
                logging.warning(f"Could not initialize AlpacaClient ({e}). Historical filtering disabled.")

        filtered_data = filter_stocks_by_history(normalized_data, alpaca_client)
    else:
        filtered_data = normalized_data

    return filtered_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Screener Client')
    parser.add_argument('--no-filter', dest='filter_weak_stocks', action='store_false', 
                      help='Disable filtering of weak stocks (default: filtering enabled)')
    args = parser.parse_args()

    logging.info("--- Running Screener Client Test (with Historical Filtering) ---")
    logging.info(f"Filter weak stocks: {args.filter_weak_stocks}")
    # Provide the config path relative to the project root when calling
    # Assuming this script is run from the project root or VS Code context is root
    data = get_screener_data(config_path='config/config.json', filter_weak_stocks=args.filter_weak_stocks)

    # Save the DataFrame to JSON, regardless of content (will write empty list if None/empty)
    output_filename = "screener_results.json"
    try:
        if data is not None:
            # Convert NaN/NaT to None for JSON compatibility
            data_cleaned = data.where(pd.notnull(data), None)
            # Convert DataFrame to list of records (dictionaries)
            records = data_cleaned.to_dict(orient='records')
            with open(output_filename, 'w') as f:
                json.dump(records, f, indent=4)
            logging.info(f"Successfully saved results to {output_filename}")
        else:
             # Write an empty list if data is None
             with open(output_filename, 'w') as f:
                json.dump([], f, indent=4)
             logging.info(f"Screener client returned None, saved empty list to {output_filename}")
    except Exception as e:
        logging.error(f"Failed to save results to {output_filename}: {e}")

    # Now print the results
    if data is not None and not data.empty:
        print("\n--- Filtered Screener Client Results ---")
        print(f"Showing {len(data)} stocks after applying historical filters:")
        print(data.to_string())
        print("--------------------------------------\n")
    elif data is not None and data.empty:
         print("\n--- Filtered Screener Client Results ---")
         print(" (No stocks matched the initial screener criteria OR all were filtered out by historical rules)")
         print("--------------------------------------\n")
    else:
        print("\n--- Screener Client Results ---")
        print("Failed to retrieve data from the screener client.")
        print("-----------------------------\n")
        # JSON saving logic moved above

    logging.info("--- Screener Client Test Finished ---")
