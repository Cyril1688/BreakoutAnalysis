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
        logging.info("Configuration loaded successfully for pre-market gappers.")
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

def build_request_payload():
    """Builds the request payload for the pre-market gappers screener."""
    # Filters based on the pre-market gappers screenshot
    filters = [
        {"left": "premarket_change", "operation": "greater", "right": 10},
        {"left": "premarket_volume", "operation": "greater", "right": 1000000},
        # Filter for Pre-market Vol > Avg Volume 10D
        {"left": "premarket_volume", "operation": "greater", "right": "average_volume_10d_calc"},
        # Add price filter if needed, e.g., {"left": "premarket_close", "operation": "greater", "right": 1}
    ]

    # Columns based on the screenshot and previous requests - Re-adding all
    columns = [
        "name",                               # Ticker symbol
        "exchange",
        "description",                        # Company name
        "close",                              # Previous Close Price
        "premarket_close",                    # Pre-Market Price (more relevant)
        "premarket_change",                   # Pre-Market Change %
        "premarket_volume",                   # Pre-Market Volume
        "change",                             # Regular Session Change %
        "volume",                             # Regular Session Volume
        "relative_volume_10d_calc",           # Regular Session Rel Volume
        "market_cap_basic",                   # Market Cap
        "price_earnings_ttm",                 # P/E
        "earnings_per_share_basic_ttm",       # EPS dil TTM
        # "earnings_per_share_growth_ttm_yoy",  # Removed - Causes API Error
        # "dividend_yield_forward",             # Removed - Causes API Error
        "sector",                             # Sector
        "Recommend.All",                      # Analyst Rating
        "logoid",
        # Technical Indicators
        "RSI",
        "SMA10",
        "SMA20",
        "SMA50",
        "SMA100",
        "SMA200",
        "MACD.macd",
        "MACD.signal",
        "VWAP",
        "Pivot.M.Classic.S1",
        "Pivot.M.Classic.S2",
        "Pivot.M.Classic.S3",
        "Pivot.M.Classic.R1",
        "Pivot.M.Classic.R2",
        "Pivot.M.Classic.R3"
    ]

    payload = {
        "filter": filters,
        "options": {"lang": "en"},
        "markets": ["america"],
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": columns,
        "sort": {"sortBy": "premarket_change", "sortOrder": "desc"}, # Sort by highest pre-market change %
        "range": [0, 150] # Fetch top 150 results
    }
    return payload

def fetch_screener_data(config):
    """Fetches and parses the pre-market gappers screener data using the TradingView API."""
    if not config:
        logging.error("Configuration is missing for pre-market gappers.")
        return None

    screener_config = config.get('screeners', {})
    headers = screener_config.get('browser_headers', {'Content-Type': 'application/json'})
    if 'Content-Type' not in headers:
         headers['Content-Type'] = 'application/json'

    payload = build_request_payload()
    logging.info(f"Attempting to fetch pre-market gappers data from API: {API_URL}")
    logging.debug(f"Request Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=20)
        # Check for HTTP errors and log details if found
        try:
            response.raise_for_status()
            logging.info(f"Successfully fetched pre-market gappers data from API. Status code: {response.status_code}")
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
            logging.warning("API response for pre-market gappers does not contain 'data' or 'data' is empty.")
            return pd.DataFrame()

        stock_list = api_data['data']
        total_count = api_data.get('totalCount', len(stock_list))
        logging.info(f"API returned {len(stock_list)} pre-market gappers (total potential: {total_count}).")

        column_names = payload['columns']
        processed_data = []
        for stock in stock_list:
            if 'd' in stock and len(stock['d']) == len(column_names):
                 processed_data.append(dict(zip(column_names, stock['d'])))
            else:
                 logging.warning(f"Skipping pre-market stock due to mismatched data/columns: {stock.get('s', 'N/A')}")

        if not processed_data:
             logging.error("No pre-market gappers data could be processed into the DataFrame structure.")
             return pd.DataFrame()

        df = pd.DataFrame(processed_data)
        logging.info(f"Successfully parsed pre-market gappers API data into DataFrame. Shape: {df.shape}")

        # Apply sector and market cap filtering
        def sector_market_cap_filter(row):
            if row['sector'] in ['Electronic Technology', 'Technology Services']:
                return True
            else:
                try:
                    return float(row['market_cap_basic']) > 200_000_000
                except (ValueError, TypeError):
                    return False

        df_filtered = df[df.apply(sector_market_cap_filter, axis=1)]
        logging.info(f"DataFrame shape after sector and market cap filtering: {df_filtered.shape}")
        return df_filtered

    except requests.exceptions.RequestException as e:
        logging.error(f"API request failed for pre-market gappers: {e}")
        return None
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON response from API for pre-market gappers.")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during pre-market gappers API fetching or parsing: {e}")
        return None

if __name__ == "__main__":
    config = load_config()
    if config:
        screener_data = fetch_screener_data(config)
        if screener_data is not None:
            if not screener_data.empty:
                print("Pre-Market Gappers Screener Data (from API):")
                print(screener_data.to_string())
            else:
                print("API returned no matching pre-market gappers or data could not be parsed.")
        else:
            print("Failed to retrieve or parse pre-market gappers screener data from API.")
    else:
        print("Failed to load configuration for pre-market gappers.")
