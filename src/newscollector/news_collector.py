"""
News collector for fetching and processing news for multiple stock symbols.
"""
import json
import logging
import argparse
from datetime import datetime

import sys
import os

# --- Add project root to sys.path for direct script execution ---
# Calculate the project root directory (two levels up from 'src/newscollector')
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End of path addition ---

# Use absolute imports from src
from src.utils.alpaca_client import AlpacaClient
from src.newscollector.news_client import NewsClient
from src.newssummary.summarizer import summarize_article

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NewsCollector:
    """
    Collects news for specified stock symbols and outputs in JSON format
    """
    
    def __init__(self, config_path='config/config.json', headers=None, cookies=None, cookie_string=None):
        """
        Initialize the NewsCollector with configuration.
        
        Args:
            config_path (str): Path to the configuration file
            headers (dict): Optional HTTP headers to use for article requests
            cookies (dict): Optional cookies to use for article requests
            cookie_string (str): Optional full cookie string from browser
        """
        self.config_path = config_path
        self.headers = headers
        self.cookies = cookies
        self.cookie_string = cookie_string
        self.load_config()
        self.alpaca_client = AlpacaClient(config_path=config_path)
        self.news_client = NewsClient(self.alpaca_client)
        
    def load_config(self):
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
                
            # Get news collector config
            self.news_config = self.config.get('news_collector', {})
            self.back_hours = self.news_config.get('back_hours', 24)
            self.summarize_articles = self.news_config.get('summarize_articles', False)
            
            # Get browser headers and cookies from config if not provided
            if not self.headers and 'browser_headers' in self.news_config:
                self.headers = self.news_config.get('browser_headers')
                
            if not self.cookies and 'browser_cookies' in self.news_config:
                self.cookies = self.news_config.get('browser_cookies')
                
            if not self.cookie_string and 'browser_cookie_string' in self.news_config:
                self.cookie_string = self.news_config.get('browser_cookie_string')
            
            logging.info(f"Loaded configuration: back_hours={self.back_hours}, summarize_articles={self.summarize_articles}")
        except Exception as e:
            logging.error(f"Error loading configuration: {e}")
            # Set default values
            self.back_hours = 24
            self.summarize_articles = False
            
    def collect_news(self, symbols):
        """
        Collect news for the specified symbols
        
        Args:
            symbols (list): List of stock symbols
            
        Returns:
            dict: News data organized by symbol
        """
        if not symbols:
            logging.info("No symbols provided, collecting general US market news")
            # Use 1 hour for back_hours when fetching general news
            general_back_hours = 1
            news_items = self.news_client.get_general_us_news(back_hours=general_back_hours)
            
            # Store the general news under a special key
            result = {"GENERAL": []}
            
            if news_items:
                # Format the results
                formatted_items = []
                for item in news_items:
                    formatted_item = {
                        'title': item.get('title', ''),
                        'published': item.get('published', 0),
                        'published_datetime': datetime.fromtimestamp(item.get('published', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        'url': item.get('full_url', ''),
                        'provider': item.get('provider', {}).get('name', '')
                    }
                    
                    # Add summary if enabled
                    if self.summarize_articles:
                        logging.info(f"Summarizing article: {formatted_item['url']}")
                        summary_result = summarize_article(
                            formatted_item['url'],
                            headers=self.headers,
                            cookies=self.cookies,
                            cookie_string=self.cookie_string
                        )
                        
                        if summary_result['success']:
                            formatted_item['summary'] = summary_result['summary']
                            logging.info(f"Successfully summarized article: {formatted_item['title']}")
                        else:
                            error = summary_result['error']
                            if "login wall" in error.lower():
                                formatted_item['summary'] = "Article requires login to read. Summary not available."
                                logging.warning(f"Article requires login: {formatted_item['url']}")
                            else:
                                formatted_item['summary'] = f"Failed to summarize: {error}"
                                logging.warning(f"Failed to summarize article: {formatted_item['url']} - {error}")
                    
                    formatted_items.append(formatted_item)
                
                result["GENERAL"] = formatted_items
            
            # Override back_hours for output
            self.back_hours = general_back_hours
            
            return result
            
        result = {}
        
        for symbol in symbols:
            logging.info(f"Collecting news for {symbol}")
            news_items = self.news_client.get_news_for_symbol(symbol, self.back_hours)
            
            if news_items:
                # Format the results
                formatted_items = []
                for item in news_items:
                    formatted_item = {
                        'title': item.get('title', ''),
                        'published': item.get('published', 0),
                        'published_datetime': datetime.fromtimestamp(item.get('published', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                        'url': item.get('full_url', ''),
                        'provider': item.get('provider', {}).get('name', '')
                    }
                    
                    # Add summary if enabled
                    if self.summarize_articles:
                        logging.info(f"Summarizing article: {formatted_item['url']}")
                        summary_result = summarize_article(
                            formatted_item['url'],
                            headers=self.headers,
                            cookies=self.cookies,
                            cookie_string=self.cookie_string
                        )
                        
                        if summary_result['success']:
                            formatted_item['summary'] = summary_result['summary']
                            logging.info(f"Successfully summarized article: {formatted_item['title']}")
                        else:
                            error = summary_result['error']
                            if "login wall" in error.lower():
                                formatted_item['summary'] = "Article requires login to read. Summary not available."
                                logging.warning(f"Article requires login: {formatted_item['url']}")
                            else:
                                formatted_item['summary'] = f"Failed to summarize: {error}"
                                logging.warning(f"Failed to summarize article: {formatted_item['url']} - {error}")
                        
                    formatted_items.append(formatted_item)
                
                result[symbol] = formatted_items
            else:
                result[symbol] = []
                
        return result
        
    def output_results(self, results):
        """
        Output the results in JSON format
        
        Args:
            results (dict): News data organized by symbol
        
        Returns:
            str: JSON string of the results
        """
        output = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'back_hours': self.back_hours,
            'news': results
        }
        
        return json.dumps(output, indent=2)


def main():
    """
    Main entry point for news collector
    """
    parser = argparse.ArgumentParser(description='Collect news for stock symbols')
    parser.add_argument('symbols', nargs='*', help='Stock symbols to collect news for. If not provided, general US market news will be collected.')
    parser.add_argument('--config', default='config/config.json', help='Path to configuration file')
    parser.add_argument('--output', help='Output file path (if not specified, prints to stdout)')
    
    args = parser.parse_args()
    
    try:
        # Initialize news collector
        collector = NewsCollector(config_path=args.config)
        
        # Collect news
        results = collector.collect_news(args.symbols)
        
        # Format and output results
        output_json = collector.output_results(results)
        
        if args.output:
            # Write to file
            with open(args.output, 'w') as f:
                f.write(output_json)
            logging.info(f"Results written to {args.output}")
        else:
            # Print to stdout
            print(output_json)
            
    except Exception as e:
        logging.error(f"Error in news collection: {e}")
        import traceback
        logging.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
