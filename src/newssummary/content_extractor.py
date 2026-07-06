"""
Content extractor module for extracting article content from URLs.
"""
import logging
import requests
import re
import time  # Added for retry delay
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Default User-Agent to mimic a browser
DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'

def extract_article_content(url, timeout=15, headers=None, cookies=None, cookie_string=None, retries=3, retry_delay=2): # Increased timeout, added retries
    """
    Extract the main content from a news article URL.
    
    Args:
        url (str): The URL of the news article
        timeout (int): Timeout in seconds for article download
        headers (dict): Optional HTTP headers to use for the request
        cookies (dict): Optional cookies to use for the request
        cookie_string (str): Optional full cookie string from browser
        
    Returns:
        dict: Dictionary containing article information with keys:
            - 'title': Article title
            - 'text': Main article text
            - 'success': Boolean indicating if extraction was successful
            - 'error': Error message if extraction failed
    """
    result = {
        'title': '',
        'text': '',
        'success': False,
        'error': None
    }
    
    if not url:
            result['error'] = "No URL provided"
            return result

    session = requests.Session() # Use a session object

    for attempt in range(retries):
        try:
            # Prepare headers for this attempt
            request_headers = headers.copy() if headers else {}
            # Add User-Agent if not already present
            if 'User-Agent' not in request_headers:
                request_headers['User-Agent'] = DEFAULT_USER_AGENT
            # Add cookie string to headers if provided
            if cookie_string:
                request_headers['Cookie'] = cookie_string

            # Make the request using the session
            response = session.get(url, headers=request_headers, cookies=cookies, timeout=timeout)

            # Check for successful status code
            if response.status_code == 200:
                # Success, break the retry loop
                break
            # Check for server errors (5xx) to retry
            elif 500 <= response.status_code < 600:
                logging.warning(f"Attempt {attempt + 1}/{retries}: Received HTTP {response.status_code} for {url}. Retrying in {retry_delay}s...")
                if attempt < retries - 1:
                    time.sleep(retry_delay)
                    continue # Go to the next attempt
                else:
                    # Last attempt failed
                    result['error'] = f"Failed to download article after {retries} attempts: HTTP {response.status_code}"
                    return result
            else:
                # Other client-side error (e.g., 4xx), don't retry
                result['error'] = f"Failed to download article: HTTP {response.status_code}"
                return result

        except requests.exceptions.RequestException as e:
            logging.warning(f"Attempt {attempt + 1}/{retries}: Request error for {url}: {e}. Retrying in {retry_delay}s...")
            if attempt < retries - 1:
                time.sleep(retry_delay)
                continue # Go to the next attempt
            else:
                # Last attempt failed with request exception
                logging.error(f"Request error for {url} after {retries} attempts: {e}")
                result['error'] = f"Request error after {retries} attempts: {str(e)}"
                return result
    else:
        # This else block executes if the loop completes without breaking (i.e., all retries failed)
        # This case should theoretically be covered by the checks inside the loop, but added for safety.
        if 'error' not in result or not result['error']: # Check if error wasn't already set
             result['error'] = f"Failed to download article after {retries} attempts (unknown reason)."
        return result

    # --- Request successful, proceed with parsing ---
    try:
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        if title_tag:
            result['title'] = title_tag.text.strip()
        
        # Extract article content
        # For TradingView news articles, the main content is in a div with class "tv-news-view__container"
        article_container = soup.find('div', class_='tv-news-view__container')
        
        if article_container:
            # Extract paragraphs
            paragraphs = article_container.find_all('p')
            article_text = '\n\n'.join([p.text.strip() for p in paragraphs])
            
            # If no paragraphs found, try to get all text from the container
            if not article_text:
                article_text = article_container.get_text(separator='\n\n', strip=True)
            
            result['text'] = article_text
        else:
            # Try to find any article content
            article_content = soup.find('article') or soup.find('div', class_=re.compile(r'article|content|story'))
            if article_content:
                paragraphs = article_content.find_all('p')
                article_text = '\n\n'.join([p.text.strip() for p in paragraphs])
                
                if not article_text:
                    article_text = article_content.get_text(separator='\n\n', strip=True)
                
                result['text'] = article_text
        
        # Check if we got meaningful content
        if not result['text']:
            logging.warning(f"Extracted content from {url} is empty")
            result['success'] = False
            result['error'] = "Extracted content is empty"
            return result
        
        # Check if the article is behind a login wall
        login_phrases = [
            "login or create",
            "sign in",
            "create an account",
            "subscribe",
            "membership",
            "free account"
        ]
        
        if len(result['text']) < 100 and any(phrase in result['text'].lower() for phrase in login_phrases):
            logging.warning(f"Article at {url} appears to be behind a login wall")
            result['success'] = False
            result['error'] = "Article is behind a login wall"
            return result
        
        # Check if content is too short
        if len(result['text']) < 50:
            logging.warning(f"Extracted content from {url} is too short")
            result['success'] = False
            result['error'] = "Extracted content is too short"
            return result
        
        # If we got here, we have successfully extracted content
        result['success'] = True
        logging.info(f"Successfully extracted content from {url}")
        return result
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Request error for {url}: {e}")
        result['error'] = f"Request error: {str(e)}"
        return result
        
    except Exception as e:
        logging.error(f"Unexpected error extracting content from {url}: {e}")
        result['error'] = f"Unexpected error: {str(e)}"
        return result
