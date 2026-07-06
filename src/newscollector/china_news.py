"""
Chinese Stock News Collector (A-Share)
Fetches news for A-share stocks from various Chinese financial news sources.

Supported sources:
- East Money (东方财富) individual stock news
- Sina Finance (新浪财经) individual stock news
- akshare integration for financial news
"""

import logging
import os
import sys
import json
import requests
from datetime import datetime, timedelta
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - CHINA_NEWS - %(levelname)s - %(message)s')

CHINA_TZ = pytz.timezone('Asia/Shanghai')


class ChinaNewsCollector:
    """
    Collects news for A-share stocks from Chinese financial sources.
    """

    def __init__(self, config_path=None):
        self.config = {}
        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except Exception as e:
                logging.warning(f"Could not load config for China news: {e}")

        self.back_hours = self.config.get('china_news', {}).get('back_hours', 48)
        self.max_news_per_stock = self.config.get('china_news', {}).get('max_news_per_stock', 3)
        
        # Headers for web requests (mimic browser)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://www.eastmoney.com/',
        }

    def get_east_money_news(self, ticker):
        """
        Fetch news for an A-share stock from East Money API.
        
        East Money API:
        GET https://push2.eastmoney.com/api/qt/stock/get
        GET https://so.eastmoney.com/news/s?keyword={stock_name}
        """
        news_items = []
        
        try:
            # East Money stock news API
            url = f"https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                'cb': 'jQuery',
                'param': json.dumps({
                    'uid': '',
                    'keyword': ticker,
                    'type': ['cmsArticleWebOld'],
                    'client': 'web',
                    'clientType': 'web',
                    'clientVersion': 'curr',
                    'param': {
                        'cmsArticleWebOld': {
                            'searchScope': 'default',
                            'sort': 'default',
                            'pageIndex': 1,
                            'pageSize': 5,
                        }
                    }
                })
            }
            
            # Alternative: use akshare for news
            # ak.stock_individual_info_em(symbol) can provide basic info
            # For news, we can try a direct API call to East Money
            
            # Simpler approach: use a direct news search
            # East Money individual stock news
            secid = self._get_secid(ticker)
            if secid:
                news_url = (
                    f"https://push2.eastmoney.com/api/qt/stock/news/get"
                    f"?secid={secid}&count=5&type=1"
                )
                resp = requests.get(news_url, headers=self.headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('data') and data['data'].get('news'):
                        for article in data['data']['news']:
                            news_items.append({
                                'title': article.get('title', ''),
                                'summary': article.get('intro', ''),
                                'url': article.get('articleUrl', ''),
                                'source': '东方财富',
                                'published_datetime': article.get('date', ''),
                            })

        except Exception as e:
            logging.error(f"Error fetching East Money news for {ticker}: {e}")

        return news_items

    def _get_secid(self, ticker):
        """Get East Money secid for a stock ticker."""
        # Clear ticker (remove suffix)
        ticker = ticker.strip().zfill(6)
        
        # Determine exchange
        if ticker.startswith('6'):
            exchange = '1'  # SSE
        elif ticker.startswith('0') or ticker.startswith('3'):
            exchange = '0'  # SZSE
        elif ticker.startswith('4') or ticker.startswith('8'):
            exchange = '0'  # BSE
        else:
            return None
        
        return f"{exchange}.{ticker}"

    def get_akshare_news(self, ticker):
        """
        Use akshare to get stock news if available.
        """
        try:
            import akshare as ak
            
            # Get stock individual info (includes news links)
            try:
                news_df = ak.stock_individual_news_em(symbol=ticker)
                if news_df is not None and not news_df.empty:
                    news_items = []
                    for _, row in news_df.head(5).iterrows():
                        news_items.append({
                            'title': row.get('新闻标题', row.get('title', '')),
                            'summary': row.get('新闻内容', row.get('content', '')),
                            'url': row.get('新闻链接', row.get('url', '')),
                            'source': '东方财富',
                            'published_datetime': str(row.get('发布时间', row.get('date', ''))),
                        })
                    return news_items
            except Exception as e:
                logging.debug(f"akshare news failed for {ticker}: {e}")
                pass
                
        except ImportError:
            logging.debug("akshare not available for news collection.")
        except Exception as e:
            logging.debug(f"akshare news error for {ticker}: {e}")
        
        return []

    def collect_news(self, tickers):
        """
        Collect news for a list of A-share tickers.
        
        Args:
            tickers (list): List of A-share ticker symbols (e.g., ['600519', '000001'])
        
        Returns:
            dict: {ticker: [news_item, ...], ...}
        """
        if not tickers:
            return {}

        logging.info(f"Collecting China news for {len(tickers)} tickers...")
        results = {}

        for ticker in tickers:
            ticker = ticker.strip().zfill(6)
            
            # Try akshare first (more comprehensive)
            news_items = self.get_akshare_news(ticker)
            
            # Fall back to East Money API
            if not news_items:
                news_items = self.get_east_money_news(ticker)

            # Filter by time and limit
            if news_items:
                # Sort and limit
                news_items = news_items[:self.max_news_per_stock]
                results[ticker] = news_items
                logging.info(f"[China] {ticker}: {len(news_items)} news items")
            else:
                results[ticker] = []

        total_news = sum(len(v) for v in results.values())
        logging.info(f"China news collection complete. Total items: {total_news}")
        return results


if __name__ == "__main__":
    logging.info("--- Testing China News Collector ---")
    collector = ChinaNewsCollector()
    
    # Test with some popular A-shares
    test_tickers = ['600519', '000858', '300750']
    news = collector.collect_news(test_tickers)
    
    for ticker, items in news.items():
        print(f"\n=== {ticker} ===")
        if items:
            for item in items:
                print(f"  - {item['title']} ({item['source']})")
        else:
            print("  No news found.")
