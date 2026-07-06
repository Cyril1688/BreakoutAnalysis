import json
import logging
import requests
import pandas as pd
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define config path relative to the script location
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.json')
API_URL = "https://scanner.tradingview.com/america/scan" # Using the America endpoint

def load_config():
    """Loads the configuration from config.json"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
        logging.info("Configuration loaded successfully.")
        # We might not need browser headers/cookies anymore, but keep loading for now
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

def build_request_payload(filters_config=None):
    """Builds the request payload based on the desired screener criteria."""
    fc = filters_config or {}

    # Read configurable thresholds (with sensible fallback defaults)
    min_change     = fc.get('min_change_percent', 6)
    min_volume     = fc.get('min_volume', 1_000_000)
    min_price      = fc.get('min_price', 0.5)
    max_price      = fc.get('max_price', 100)
    min_rel_volume = fc.get('min_relative_volume', 2)

    filters = [
        {"left": "change",                  "operation": "greater", "right": min_change},
        {"left": "volume",                  "operation": "greater", "right": min_volume},
        {"left": "close",                   "operation": "greater", "right": min_price},
        {"left": "close",                   "operation": "less",    "right": max_price},
        {"left": "relative_volume_10d_calc","operation": "greater", "right": min_rel_volume},
    ]

    # Columns based on the screenshot analysis
    columns = [
        "name",                     # Ticker symbol
        "exchange",
        "description",              # Company name
        "close",                    # Price
        "change",                   # Change %
        "volume",                   # Volume
        "relative_volume_10d_calc", # Rel Volume
        "market_cap_basic",         # Market Cap
        "price_earnings_ttm",       # P/E
        "sector",                   # Sector
        "logoid",
        "RSI",
        "SMA10", "SMA20", "SMA50", "SMA100", "SMA200",
        "MACD.macd", "MACD.signal",
        "VWAP",
        "Pivot.M.Classic.S1", "Pivot.M.Classic.S2", "Pivot.M.Classic.S3",
        "Pivot.M.Classic.R1", "Pivot.M.Classic.R2", "Pivot.M.Classic.R3"
    ]

    payload = {
        "filter": filters,
        "options": {"lang": "en"},
        "markets": ["america"],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": columns,
        "sort": {"sortBy": "change", "sortOrder": "desc"},
        "range": [0, 150]
    }
    return payload

def fetch_screener_data(config):
    """Fetches and parses the market gainer screener data using the TradingView API."""
    if not config:
        logging.error("Configuration is missing.")
        return None

    screener_config = config.get('screeners', {})
    headers = screener_config.get('browser_headers', {'Content-Type': 'application/json'})
    if 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json'

    # Pass filters config to payload builder
    filters_config = screener_config.get('filters', {})
    payload = build_request_payload(filters_config)
    logging.info(f"Attempting to fetch data from API: {API_URL}")
    logging.debug(f"Request Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=20)
        # Check for HTTP errors and log details if found
        try:
            response.raise_for_status()
            logging.info(f"Successfully fetched data from API. Status code: {response.status_code}")
            api_data = response.json()
        except requests.exceptions.HTTPError as http_err:
            logging.error(f"HTTP error occurred: {http_err}")
            logging.error(f"Status Code: {response.status_code}")
            try:
                # Attempt to log the detailed error message from the response body
                error_details = response.json()
                logging.error(f"API Error Details: {json.dumps(error_details, indent=2)}")
            except json.JSONDecodeError:
                logging.error(f"Could not decode JSON error response. Response Text: {response.text}")
            return None # Return None as the request failed

        if 'data' not in api_data or not api_data['data']:
            logging.warning("API response does not contain 'data' or 'data' is empty.")
            return pd.DataFrame() # Return empty DataFrame

        # The actual stock data is in api_data['data'], which is a list of dictionaries
        stock_list = api_data['data']
        total_count = api_data.get('totalCount', len(stock_list))
        logging.info(f"API returned {len(stock_list)} stocks (total potential: {total_count}).")

        # Convert the list of dictionaries into a DataFrame
        # The keys in the dictionaries correspond to the 'columns' requested
        # We need to map the 'd' list within each stock entry to the column names
        column_names = payload['columns']
        processed_data = []
        for stock in stock_list:
            if 'd' in stock and len(stock['d']) == len(column_names):
                 processed_data.append(dict(zip(column_names, stock['d'])))
            else:
                 logging.warning(f"Skipping stock due to mismatched data/columns: {stock.get('s', 'N/A')}")


        if not processed_data:
             logging.error("No data could be processed into the DataFrame structure.")
             return pd.DataFrame()

        df = pd.DataFrame(processed_data)
        logging.info(f"Successfully parsed API data into DataFrame. Shape: {df.shape}")

        # Apply sector and market cap filtering
        fc = config.get('screeners', {}).get('filters', {})
        min_market_cap_non_tech = fc.get('min_market_cap_non_tech', 200_000_000)
        large_cap_threshold     = fc.get('large_cap_threshold', 10_000_000_000)
        large_cap_min_change    = fc.get('large_cap_min_change_percent', 6)
        small_cap_min_change    = fc.get('small_cap_min_change_percent', 10)

        def sector_market_cap_filter(row):
            if row['sector'] in ['Electronic Technology', 'Technology Services']:
                return True
            else:
                try:
                    return float(row['market_cap_basic']) > min_market_cap_non_tech
                except (ValueError, TypeError):
                    return False

        df_filtered = df[df.apply(sector_market_cap_filter, axis=1)]
        logging.info(f"DataFrame shape after sector and market cap filtering: {df_filtered.shape}")

        def dynamic_change_filter(row):
            try:
                market_cap     = float(row['market_cap_basic'])
                change_percent = float(row['change'])
                if market_cap > large_cap_threshold:
                    return change_percent > large_cap_min_change
                else:
                    return change_percent > small_cap_min_change
            except (ValueError, TypeError):
                return False

        df_final_filtered = df_filtered[df_filtered.apply(dynamic_change_filter, axis=1)]
        logging.info(f"DataFrame shape after dynamic change filtering: {df_final_filtered.shape}")
        return df_final_filtered

    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed: {e}")
        return None
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON response from API.")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during API fetching or parsing: {e}")
        return None

if __name__ == "__main__":
    config = load_config()
    if config:
        screener_data = fetch_screener_data(config)
        if screener_data is not None:
            if not screener_data.empty:
                print("Market Gainers Screener Data (from API):")
                print(screener_data.to_string()) # Print full DataFrame
            else:
                print("API returned no matching stocks or data could not be parsed.")
        else:
            print("Failed to retrieve or parse market gainers screener data from API.")
    else:
        print("Failed to load configuration.")
