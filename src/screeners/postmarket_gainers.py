import json
import logging
import requests
import pandas as pd
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Define config path relative to the script location
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.json')
API_URL = "https://scanner.tradingview.com/america/scan" # Using the America endpoint - MAY NEED ADJUSTMENT FOR POSTMARKET

def load_config():
    """Loads the configuration from config.json"""
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
        logging.info("Configuration loaded successfully for postmarket gainers.")
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

def build_postmarket_request_payload():
    """Builds the request payload for the postmarket gainer screener."""
    # Filters - STARTING WITH MARKET GAINERS FILTERS - MAY NEED ADJUSTMENT FOR POSTMARKET
    # Specifically, the 'change' filter might need to point to a postmarket change field if available.
    # TradingView might use fields like 'postmarket_change' or similar.
    # For now, using 'change' as a placeholder.
    filters = [
        {"left": "postmarket_change", "operation": "greater", "right": 5}, # Adjusted threshold slightly for postmarket
        {"left": "volume", "operation": "greater", "right": 300000}, # Lowered volume threshold for postmarket
        {"left": "close", "operation": "greater", "right": 0.5},
        {"left": "close", "operation": "less", "right": 100}
    ]

    # Columns - Keeping the same columns as market gainers for now
    columns = [
        "name",
        "description",
        "close", # This might represent the closing price of the regular session
        "postmarket_close", # Attempting to add postmarket specific price
        "change", # Regular session change %
        "postmarket_change", # Attempting to add postmarket change %
        "volume", # Regular session volume
        "postmarket_volume", # Attempting to add postmarket volume
        "relative_volume_10d_calc",
        "market_cap_basic",
        "price_earnings_ttm",
        "sector",
        "logoid",
        "RSI",
        "SMA10",
        "SMA20",
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
        # Sorting by postmarket change if the column exists, otherwise fallback to regular change
        "sort": {"sortBy": "postmarket_change", "sortOrder": "desc"},
        "range": [0, 100] # Fetch top 100 results for postmarket
    }
    return payload

def fetch_postmarket_gainers_data(config):
    """Fetches and parses the postmarket gainer screener data using the TradingView API."""
    if not config:
        logging.error("Configuration is missing for postmarket gainers.")
        return None

    screener_config = config.get('screeners', {})
    headers = screener_config.get('browser_headers', {'Content-Type': 'application/json'})
    if 'Content-Type' not in headers:
         headers['Content-Type'] = 'application/json'

    payload = build_postmarket_request_payload()
    logging.info(f"Attempting to fetch postmarket data from API: {API_URL}")
    logging.debug(f"Postmarket Request Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=20)
        try:
            response.raise_for_status()
            logging.info(f"Successfully fetched postmarket data from API. Status code: {response.status_code}")
            api_data = response.json()
        except requests.exceptions.HTTPError as http_err:
            logging.error(f"HTTP error occurred fetching postmarket data: {http_err}")
            logging.error(f"Status Code: {response.status_code}")
            try:
                error_details = response.json()
                logging.error(f"API Error Details (Postmarket): {json.dumps(error_details, indent=2)}")
            except json.JSONDecodeError:
                logging.error(f"Could not decode JSON error response (Postmarket). Response Text: {response.text}")
            return None

        if 'data' not in api_data or not api_data['data']:
            logging.warning("Postmarket API response does not contain 'data' or 'data' is empty.")
            # Check if the sort column was invalid and try again with 'change'
            if payload['sort']['sortBy'] == 'postmarket_change':
                 logging.warning("Attempting fallback sort by 'change' for postmarket gainers.")
                 payload['sort']['sortBy'] = 'change'
                 payload['columns'].remove('postmarket_change') # Remove potentially invalid columns
                 payload['columns'].remove('postmarket_close')
                 payload['columns'].remove('postmarket_volume')
                 # Also adjust the filter if it used postmarket_change
                 for f in payload['filter']:
                     if f['left'] == 'postmarket_change':
                         f['left'] = 'change' # Fallback filter
                         logging.warning("Fallback filter applied to 'change'.")
                         break # Assuming only one change filter

                 logging.debug(f"Fallback Postmarket Request Payload: {json.dumps(payload, indent=2)}")
                 response = requests.post(API_URL, headers=headers, json=payload, timeout=20)
                 response.raise_for_status() # Raise error if fallback fails too
                 api_data = response.json()
                 if 'data' not in api_data or not api_data['data']:
                      logging.error("Fallback attempt also yielded no data for postmarket gainers.")
                      return pd.DataFrame()

            else:
                 return pd.DataFrame() # Return empty DataFrame if already tried fallback or initial sort was 'change'


        stock_list = api_data['data']
        total_count = api_data.get('totalCount', len(stock_list))
        logging.info(f"API returned {len(stock_list)} postmarket stocks (total potential: {total_count}).")

        column_names = payload['columns'] # Use potentially updated columns from fallback
        processed_data = []
        for stock in stock_list:
            if 'd' in stock and len(stock['d']) == len(column_names):
                 processed_data.append(dict(zip(column_names, stock['d'])))
            else:
                 logging.warning(f"Skipping postmarket stock due to mismatched data/columns: {stock.get('s', 'N/A')}")


        if not processed_data:
             logging.error("No postmarket data could be processed into the DataFrame structure.")
             return pd.DataFrame()

        df = pd.DataFrame(processed_data)
        logging.info(f"Successfully parsed postmarket API data into DataFrame. Shape: {df.shape}")
        return df

    except requests.exceptions.RequestException as e:
        logging.error(f"Postmarket API request failed: {e}")
        return None
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON response from postmarket API.")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during postmarket API fetching or parsing: {e}")
        return None

if __name__ == "__main__":
    config = load_config()
    if config:
        screener_data = fetch_postmarket_gainers_data(config)
        if screener_data is not None:
            if not screener_data.empty:
                print("Postmarket Gainers Screener Data (from API):")
                print(screener_data.to_string())
            else:
                print("API returned no matching postmarket stocks or data could not be parsed.")
        else:
            print("Failed to retrieve or parse postmarket gainers screener data from API.")
    else:
        print("Failed to load configuration for postmarket gainers.")
