"""
Main entry point for news collector.

Usage:
    python -m src.newscollector AAPL MSFT GOOG
"""
import sys
import os

# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.newscollector.news_collector import main

if __name__ == "__main__":
    main()
