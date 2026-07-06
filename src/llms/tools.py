import logging
from typing import List, Dict
from duckduckgo_search import DDGS

# Configure logging for the tools module
logging.basicConfig(level=logging.INFO, format='%(asctime)s - TOOL - %(levelname)s - %(message)s')

# --- Search Tool Functionality ---
ddgs = DDGS()

def search_internet(query: str, max_results: int = 3) -> List[Dict]:
    """
    Performs an internet search using DuckDuckGo. To be used as a tool by the LLM.

    Args:
        query (str): The search query provided by the LLM.
        max_results (int): Maximum number of results to return.

    Returns:
        List[Dict]: A list of search result dictionaries, each containing
                    'title', 'href', and 'body'. Returns empty list on error.
    """
    try:
        logging.info(f"Performing internet search for: {query}")
        # Use DDGS().text which returns dictionaries directly
        results = ddgs.text(query, max_results=max_results)
        # Ensure results have the expected keys and filter out those without body
        filtered_results = [
            {'title': r.get('title', ''), 'href': r.get('href', ''), 'body': r.get('body', '')}
            for r in results if r.get('body')
        ]
        logging.info(f"Found {len(filtered_results)} relevant search results.")
        # Return the list of dictionaries, Ollama expects the tool output as JSON/dict
        return filtered_results
    except Exception as e:
        logging.error(f"Error during internet search for '{query}': {e}", exc_info=True)
        return [] # Return empty list on error
