"""
News collector module for fetching news from TradingView.
"""

# 惰性导入：NewsCollector 依赖 alpaca-py，可能未安装
try:
    from src.newscollector.news_collector import NewsCollector
    _NEWS_COLLECTOR_OK = True
except ImportError:
    _NEWS_COLLECTOR_OK = False

try:
    from src.newscollector.news_client import NewsClient
    _NEWS_CLIENT_OK = True
except ImportError:
    _NEWS_CLIENT_OK = False

__all__ = ['NewsCollector', 'NewsClient']
