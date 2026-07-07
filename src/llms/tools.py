import logging
from typing import List, Dict

# Configure logging for the tools module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - TOOL - %(levelname)s - %(message)s')

# Lazy singleton: DDGS imported on first use so missing duckduckgo_search doesn't block model import
_ddgs = None

def _get_ddgs():
    global _ddgs
    if _ddgs is None:
        try:
            from duckduckgo_search import DDGS
            _ddgs = DDGS()
        except ImportError:
            logging.warning("duckduckgo_search not installed. Internet search tool unavailable.")
            _ddgs = False  # sentinel
    return _ddgs

def search_internet(query: str, max_results: int = 3) -> List[Dict]:
    """
    Performs an internet search using DuckDuckGo. To be used as a tool by the LLM.

    Args:
        query (str): The search query provided by the LLM.
        max_results (int): Maximum number of search results to return.

    Returns:
        List[Dict]: A list of search result dictionaries, each containing
                    'title', 'href', and 'body'. Returns empty list on error.
    """
    ddgs = _get_ddgs()
    if not ddgs:
        logging.warning(f"Internet search unavailable (duckduckgo_search not installed).")
        return []
    try:
        logging.info(f"Performing internet search for: {query}")
        results = ddgs.text(query, max_results=max_results)
        filtered_results = [
            {'title': r.get('title', ''), 'href': r.get('href', ''), 'body': r.get('body', '')}
            for r in results if r.get('body')
        ]
        logging.info(f"Found {len(filtered_results)} relevant search results.")
        return filtered_results
    except Exception as e:
        logging.error(f"Error during internet search for '{query}': {e}", exc_info=True)
        return []
