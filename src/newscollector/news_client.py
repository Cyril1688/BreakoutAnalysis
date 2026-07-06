"""
Client for fetching news from TradingView news-mediator API.
"""
import json
import logging
import requests
import sys
import os
from datetime import datetime, timedelta
from urllib.parse import urlencode

# --- Add project root to sys.path for direct script execution & consistent imports ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End of path addition ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Import necessary components using absolute path from src
# Note: This still relies on AlpacaClient existing at src.utils.alpaca_client
from src.utils.alpaca_client import AlpacaClient

class NewsClient:
    """Client for fetching news from TradingView news-mediator API"""

    def __init__(self, alpaca_client: AlpacaClient): # Added type hint
        """
        Initialize the NewsClient with an AlpacaClient instance.

        Args:
            alpaca_client: An instance of AlpacaClient for resolving exchange symbols
        """
        self.alpaca_client = alpaca_client
        self.base_url = "https://news-mediator.tradingview.com/news-flow/v2/news"

    def get_news_for_symbol(self, symbol, back_hours=24):
        """
        Get news for a specific symbol within the specified time window
        
        Args:
            symbol (str): Stock symbol without exchange prefix
            back_hours (int): Number of hours to look back for news
            
        Returns:
            list: List of news articles matching criteria
        """
        try:
            # Get exchange symbol from Alpaca
            exchange_symbol = self.alpaca_client.get_exchange_symbol(symbol)
            logging.info(f"Resolved {symbol} to {exchange_symbol}")
            
            # Calculate time threshold
            current_time = datetime.now()
            time_threshold = current_time - timedelta(hours=back_hours)
            time_threshold_unix = int(time_threshold.timestamp())
            
            # Construct URL with proper filters
            params = {
                'filter': [
                    'lang:en',
                    'market:stock',
                    'market_country:US',
                    f'symbol:{exchange_symbol}'
                ],
                'client': 'screener',
                'streaming': 'false'
            }
            
            url = f"{self.base_url}?{urlencode(params, doseq=True)}"
            logging.info(f"Requesting news from: {url}")
            
            # Make request to TradingView API
            response = requests.get(url)
            response.raise_for_status()  # Raise exception for HTTP errors
            
            # Parse response
            news_data = response.json()
            
            # Filter by time
            filtered_news = []
            if 'items' in news_data:
                for item in news_data['items']:
                    published_time = item.get('published', 0)
                    if published_time >= time_threshold_unix:
                        # Add full article URL
                        story_path = item.get('storyPath', '')
                        if story_path:
                            item['full_url'] = f"https://www.tradingview.com{story_path}"
                        
                        filtered_news.append(item)

                # Sort by published time (descending) and take the latest 3
                if filtered_news:
                    filtered_news.sort(key=lambda x: x.get('published', 0), reverse=True)
                    latest_news = filtered_news[:3]
                    logging.info(f"Found {len(filtered_news)} news items for {symbol}, returning latest {len(latest_news)} from the last {back_hours} hours")
                else:
                    latest_news = []
                    logging.info(f"Found 0 news items for {symbol} in the last {back_hours} hours")

            else:
                logging.warning(f"No news items found in response for {symbol}")
                latest_news = []

            return latest_news

        except Exception as e:
            logging.error(f"Error fetching news for {symbol}: {e}")
            return []
            
    def get_general_us_news(self, back_hours=1):
        """
        Get general US stock market news within the specified time window
        
        Args:
            back_hours (int): Number of hours to look back for news
            
        Returns:
            list: List of news articles matching criteria
        """
        try:
            # Calculate time threshold
            current_time = datetime.now()
            time_threshold = current_time - timedelta(hours=back_hours)
            time_threshold_unix = int(time_threshold.timestamp())
            
            # Use the general US news URL
            url = "https://news-mediator.tradingview.com/news-flow/v2/news?filter=lang:en&filter=market:stock&filter=market_country:US&client=screener&streaming=false"
            logging.info(f"Requesting general US news from: {url}")
            
            # Make request to TradingView API
            response = requests.get(url)
            response.raise_for_status()  # Raise exception for HTTP errors
            
            # Parse response
            news_data = response.json()
            
            # Filter by time
            filtered_news = []
            if 'items' in news_data:
                for item in news_data['items']:
                    published_time = item.get('published', 0)
                    if published_time >= time_threshold_unix:
                        # Add full article URL
                        story_path = item.get('storyPath', '')
                        if story_path:
                            item['full_url'] = f"https://www.tradingview.com{story_path}"
                        
                        filtered_news.append(item)
                
                # Limit to top 5 news items
                top_5_news = filtered_news[:5]
                logging.info(f"Found {len(filtered_news)} general US news items, returning top {len(top_5_news)} from the last {back_hours} hours")
            else:
                logging.warning("No general news items found in response")
                top_5_news = [] # Ensure we return an empty list if no items found
            
            return top_5_news
            
        except Exception as e:
            logging.error(f"Error fetching general US news: {e}")
            return []
