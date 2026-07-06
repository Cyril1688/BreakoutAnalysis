import json
import os
import logging
import pandas as pd # Import pandas
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus
# Import historical data client and requests
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestQuoteRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.data.enums import DataFeed, Adjustment # Import DataFeed and Adjustment enums
from dateutil.relativedelta import relativedelta # For easy date calculation

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - ALPACACLIENT - %(levelname)s - %(message)s')

class AlpacaClient:
    def __init__(self, config_path='config/config.json'):
        """
        Initialize the simplified Alpaca client with configuration.

        Args:
            config_path (str): Path to the configuration file relative to project root.
        """
        # Adjust config path to be relative to the project root, not the script location
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        self.config_path = os.path.join(project_root, config_path)

        self.config = self._load_config(self.config_path)
        if not self.config:
            raise ValueError(f"Failed to load configuration from {self.config_path}.")

        # Alpaca Config
        alpaca_config = self.config.get('alpaca', {})
        self.api_key = alpaca_config.get('api_key')
        self.api_secret = alpaca_config.get('api_secret')
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API key or secret is missing in config.")

        try:
            self.trading_client = TradingClient(
                api_key=self.api_key,
                secret_key=self.api_secret,
                paper=alpaca_config.get('use_paper', True)
            )
            logging.info("Alpaca TradingClient initialized successfully.")
        except Exception as e:
            logging.error(f"Failed to initialize Alpaca TradingClient: {e}")
            raise

        # Resolve data feed setting: 'sip' (premium) or 'iex' (free, default)
        # SIP = consolidated feed from all exchanges (recommended for best accuracy)
        # IEX = free feed from IEX exchange only (acceptable for screening)
        feed_str = alpaca_config.get('data_feed', 'iex').lower()
        if feed_str == 'sip':
            self.data_feed = DataFeed.SIP
        else:
            self.data_feed = DataFeed.IEX
            if feed_str != 'iex':
                logging.warning(f"Unknown data_feed value '{feed_str}' in config. Defaulting to IEX.")
        logging.info(f"Alpaca data feed set to: {self.data_feed.value.upper()} "
                     f"({'premium consolidated' if self.data_feed == DataFeed.SIP else 'free IEX-only'})")

        # Initialize Historical Data Client
        try:
            self.data_client = StockHistoricalDataClient(
                api_key=self.api_key,
                secret_key=self.api_secret
            )
            logging.info("Alpaca StockHistoricalDataClient initialized successfully.")
        except Exception as e:
            logging.error(f"Failed to initialize Alpaca StockHistoricalDataClient: {e}")
            # Decide if this is critical. For now, log and continue.
            self.data_client = None


    def _load_config(self, config_path):
        """Load configuration from JSON file."""
        if not os.path.exists(config_path):
             logging.error(f"Configuration file absolute path not found: {config_path}")
             # Try relative path from CWD as fallback (less reliable)
             config_path_rel = os.path.join('config', 'config.json')
             if os.path.exists(config_path_rel):
                 config_path = config_path_rel
                 logging.warning(f"Using relative config path: {config_path}")
             else:
                 logging.error(f"Relative config path also not found: {config_path_rel}")
                 return None

        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            # This case should ideally be caught by os.path.exists, but added for safety
            logging.error(f"Configuration file not found at {config_path}")
            return None
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON from {config_path}")
            return None
        except Exception as e:
             logging.error(f"Unexpected error loading config {config_path}: {e}")
             return None

    def get_exchange_symbol(self, symbol):
        """
        Get the full exchange:symbol format for a given symbol.
        Returns format like 'NASDAQ:AAPL' for 'AAPL'.

        Args:
            symbol (str): Stock symbol without exchange prefix.

        Returns:
            str: Full exchange:symbol format (e.g., 'NASDAQ:AAPL') or None if error.
        """
        try:
            # Create a request to get asset details
            request_params = GetAssetsRequest(
                symbol_or_symbols=symbol,
                asset_class=AssetClass.US_EQUITY,
                status=AssetStatus.ACTIVE
            )
            logging.debug(f"Requesting asset details for: {symbol}")
            # Get asset details from Alpaca
            assets = self.trading_client.get_all_assets(request_params)

            if not assets:
                logging.warning(f"No active asset information found for symbol: {symbol}. Falling back to NASDAQ prefix.")
                # Fallback to a default exchange (NASDAQ is common for many stocks)
                return f"NASDAQ:{symbol}"

            # Get the first asset (should be only one for a specific symbol)
            asset = assets[0]

            # Map Alpaca exchange to TradingView exchange format
            # Note: This mapping might need adjustments based on TradingView's exact requirements
            exchange_map = {
                'NASDAQ': 'NASDAQ',
                'NYSE': 'NYSE',
                'AMEX': 'AMEX',
                'ARCA': 'ARCA', # Changed from NYSE based on common usage
                'BATS': 'BATS',
                'IEX': 'IEXG', # TradingView often uses IEXG
                # Add more mappings as needed
            }

            # Get exchange from asset
            alpaca_exchange = asset.exchange
            logging.debug(f"Alpaca exchange for {symbol}: {alpaca_exchange}")

            # Map to TradingView format or use default (NASDAQ)
            tv_exchange = exchange_map.get(alpaca_exchange, 'NASDAQ')
            logging.info(f"Resolved {symbol} to {tv_exchange}:{symbol}")
            return f"{tv_exchange}:{symbol}"

        except Exception as e:
            logging.error(f"Error getting exchange symbol for {symbol}: {e}")
            # Fallback to a default in case of API error
            logging.warning(f"Falling back to NASDAQ prefix for {symbol} due to error.")
            return f"NASDAQ:{symbol}"
        
    def get_current_price(self, symbol):
        """
        Get the current market price for a symbol using the latest quote.
        
        Args:
            symbol (str): The stock symbol (e.g., 'AAPL')
            
        Returns:
            float: The current market price (mid price between ask and bid)
        """
        try:
            logging.info(f"Getting latest quote for {symbol}")
            
            # Create request for latest quote
            request_params = StockLatestQuoteRequest(symbol_or_symbols=symbol)

            # Get the latest quote using data_client
            latest_quote = self.data_client.get_stock_latest_quote(request_params) # CORRECTED: Use self.data_client

            # Process the response based on its format
            if isinstance(latest_quote, dict) and symbol in latest_quote:
                # Multi-symbol response format
                quote = latest_quote[symbol]
                ask_price = quote.ask_price
                bid_price = quote.bid_price
                
                # Calculate mid price (average of ask and bid)
                mid_price = (ask_price + bid_price) / 2
                
                logging.info(f"Latest quote for {symbol}: Ask=${ask_price:.2f}, Bid=${bid_price:.2f}, Mid=${mid_price:.2f}")
                return float(mid_price)
            else:
                # Single symbol response format
                ask_price = latest_quote.ask_price
                bid_price = latest_quote.bid_price
                
                # Calculate mid price (average of ask and bid)
                mid_price = (ask_price + bid_price) / 2
                
                logging.info(f"Latest quote for {symbol}: Ask=${ask_price:.2f}, Bid=${bid_price:.2f}, Mid=${mid_price:.2f}")
                return float(mid_price)
                
        except Exception as e:
            logging.error(f"Error getting latest quote for {symbol}: {e}")
            
            # Fallback to using bars if quote request fails
            try:
                logging.warning(f"Falling back to bars data for {symbol}")
                eastern = ZoneInfo("America/New_York") # Use defined timezone
                end = datetime.now(eastern)
                # Look back 1 day for daily bars as a fallback
                start = end - timedelta(days=1)

                # Use StockBarsRequest with data_client
                request_params = StockBarsRequest(
                    symbol_or_symbols=[symbol],
                    timeframe=TimeFrame.Day, # Use daily bars for fallback
                    start=start,
                    end=end,
                    feed=self.data_feed
                )
                bars_data = self.data_client.get_stock_bars(request_params) # CORRECTED: Use self.data_client

                # Check the returned BarsSet object correctly
                if symbol in bars_data.df and not bars_data.df.loc[symbol].empty:
                    # Get the most recent close price from the DataFrame
                    price = float(bars_data.df.loc[symbol]['close'].iloc[-1]) # CORRECTED: Access df attribute
                    logging.info(f"Using recent bar close price for {symbol}: ${price:.2f}")
                    return price
                else:
                    logging.error(f"No fallback price data available for {symbol} using daily bars.")
                    return None
            except Exception as fallback_error:
                logging.error(f"Fallback method also failed for {symbol}: {fallback_error}")
                return None

    def get_historical_price_change(self, symbol):
        """
        Calculates the 1-year and 5-year percentage price change for a symbol using a simplified approach.
        
        For 1-year change: Makes a request with start date exactly one year prior and timeframe as Week.
        For 5-year change: Makes a request with start date exactly 5 years prior and timeframe as Week.
        
        Prints the earliest bar info that Alpaca is sending for both requests.

        Args:
            symbol (str): The stock symbol (e.g., 'AAPL').

        Returns:
            dict: A dictionary containing:
                  'current_price': The latest price used for calculation (float or None).
                  'change_1y': Percentage change over 1 year (float or None if data unavailable).
                  'change_5y': Percentage change over 5 years (float or None if data unavailable).
                  'error': Error message if calculation failed (str or None).
        """
        if not self.data_client:
            logging.error("StockHistoricalDataClient not initialized.")
            return {'current_price': None, 'change_1y': None, 'change_5y': None, 'error': "Data client not available."}

        logging.info(f"Calculating historical price changes for {symbol}")
        results = {'current_price': None, 'change_1y': None, 'change_5y': None, 'error': ""}
        eastern = ZoneInfo("America/New_York")
        now = datetime.now(eastern)

        # --- Get Current Price ---
        try:
            # Use latest quote first for current price
            quote_request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            latest_quote = self.data_client.get_stock_latest_quote(quote_request)
            if symbol in latest_quote:
                quote = latest_quote[symbol]
                current_price = (quote.ask_price + quote.bid_price) / 2
                results['current_price'] = float(current_price)
                logging.info(f"Current price (quote) for {symbol}: {current_price}")
            else:
                raise ValueError("Symbol not found in latest quote response.")
        except Exception as e_quote:
            logging.warning(f"Failed to get latest quote for {symbol}: {e_quote}. Falling back to latest bar.")
            try:
                # Fallback: Get the latest daily bar's close price
                bars_request = StockBarsRequest(
                    symbol_or_symbols=[symbol],
                    timeframe=TimeFrame.Day,
                    start=now - timedelta(days=5),
                    end=now,
                    feed=self.data_feed,
                    adjustment=Adjustment.ALL
                )
                latest_bars = self.data_client.get_stock_bars(bars_request)
                if symbol in latest_bars.df and not latest_bars.df.loc[symbol].empty:
                    current_price = latest_bars.df.loc[symbol]['close'].iloc[-1]
                    results['current_price'] = float(current_price)
                    logging.info(f"Current price (last bar) for {symbol}: {current_price}")
                else:
                    results['error'] = f"Could not retrieve current price for {symbol} via quote or bars."
                    logging.error(results['error'])
                    return results  # Cannot proceed without current price
            except Exception as e_bars:
                results['error'] = f"Failed to get current price for {symbol} via quote and bars: {e_bars}"
                logging.error(results['error'])
                return results

        current_price = results['current_price']  # Use the determined current price

        # --- Calculate Historical Changes ---
        for years_back in [1, 5]:
            # Calculate exact start date (years_back years ago from now)
            start_date = now - relativedelta(years=years_back)
            
            try:
                # Create request for weekly bars from the start date to now
                bars_request = StockBarsRequest(
                    symbol_or_symbols=[symbol],
                    timeframe=TimeFrame.Week,  # Use weekly timeframe as requested
                    start=start_date,
                    end=now,
                    feed=self.data_feed,
                    adjustment=Adjustment.ALL
                )
                
                logging.info(f"Requesting {years_back}-year historical weekly bars for {symbol}: Start={start_date}, End={now}")
                historical_bars = self.data_client.get_stock_bars(bars_request)
                
                # Check if we received data
                if hasattr(historical_bars, 'df') and symbol in historical_bars.df.index.get_level_values('symbol').unique() and not historical_bars.df.loc[symbol].empty:
                    # Get the bars dataframe for this symbol
                    bars_df = historical_bars.df.loc[symbol]
                    
                    # Get the earliest bar (first row in the dataframe)
                    earliest_bar = bars_df.iloc[0]
                    earliest_date = earliest_bar.name if not isinstance(earliest_bar.name, tuple) else earliest_bar.name[1]
                    earliest_price = earliest_bar['close']
                    
                    # Print the earliest bar info
                    logging.debug(f"Earliest bar for {symbol} ({years_back}-year request):")
                    logging.debug(f"  Date: {earliest_date}")
                    logging.debug(f"  Open: {earliest_bar['open']}")
                    logging.debug(f"  High: {earliest_bar['high']}")
                    logging.debug(f"  Low: {earliest_bar['low']}")
                    logging.debug(f"  Close: {earliest_price}")
                    logging.debug(f"  Volume: {earliest_bar['volume']}")
                    
                    # Calculate percentage change
                    change = ((current_price - earliest_price) / earliest_price) * 100
                    change_rounded = round(float(change), 2)
                    
                    # Store the result
                    if years_back == 1:
                        results['change_1y'] = change_rounded
                        logging.info(f"1Y change for {symbol}: {change_rounded:.2f}% (from {earliest_date} to now)")
                    else:  # 5-year
                        results['change_5y'] = change_rounded
                        logging.info(f"5Y change for {symbol}: {change_rounded:.2f}% (from {earliest_date} to now)")
                else:
                    logging.warning(f"No historical data received for {symbol} for {years_back}-year request")
                    if years_back == 1:
                        results['change_1y'] = None
                    else:  # 5-year
                        results['change_5y'] = None
            
            except Exception as e:
                logging.error(f"Error calculating {years_back}-year change for {symbol}: {e}")
                if years_back == 1:
                    results['error'] += f" Failed 1Y calc: {e};"
                else:
                    results['error'] += f" Failed 5Y calc: {e};"
        
        # Remove trailing semicolon if errors occurred
        results['error'] = results['error'].strip(';')
        if not results['error']:  # If no errors, set to None instead of empty string
            results['error'] = None
            
        logging.info(f"Historical change calculation complete for {symbol}: {results}")
        return results


if __name__ == "__main__":
    logging.info("Starting AlpacaClient (simplified) test...")
    try:
        # Example: Test getting exchange for a known symbol
        # Adjust config path relative to the new location if running directly
        client = AlpacaClient(config_path='../../config/config.json')
        test_symbol = "AAPL" # Example symbol
        exchange_symbol = client.get_exchange_symbol(test_symbol)
        if exchange_symbol:
            logging.info(f"Test successful: Exchange symbol for {test_symbol} is {exchange_symbol}")
        else:
             logging.error(f"Test failed: Could not get exchange symbol for {test_symbol}")

        test_symbol_2 = "MSFT"
        exchange_symbol_2 = client.get_exchange_symbol(test_symbol_2)
        if exchange_symbol_2:
             logging.info(f"Test successful: Exchange symbol for {test_symbol_2} is {exchange_symbol_2}")
        else:
             logging.error(f"Test failed: Could not get exchange symbol for {test_symbol_2}")

        # --- Test Historical Change ---
        logging.info("\n--- Testing Historical Price Change ---")
        test_symbol_hist = "AAPL" # A stock likely to have 5+ years of data
        hist_changes = client.get_historical_price_change(test_symbol_hist)
        logging.info(f"Historical changes for {test_symbol_hist}: {hist_changes}")

        test_symbol_hist_new = "SNOW" # A newer stock (IPO 2020)
        hist_changes_new = client.get_historical_price_change(test_symbol_hist_new)
        logging.info(f"Historical changes for {test_symbol_hist_new}: {hist_changes_new}")

        test_symbol_invalid = "INVALIDXYZ" # An invalid symbol
        hist_changes_invalid = client.get_historical_price_change(test_symbol_invalid)
        logging.info(f"Historical changes for {test_symbol_invalid}: {hist_changes_invalid}")
        # --- End Test Historical Change ---


    except ValueError as e:
        logging.error(f"Test execution failed during initialization: {e}")
    except Exception as e:
         import traceback
         logging.error(f"An unexpected error occurred during testing: {e}")
         logging.error(traceback.format_exc())
    finally:
        logging.info("AlpacaClient (simplified) test finished.")
