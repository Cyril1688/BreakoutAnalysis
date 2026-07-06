"""
Summarizer module for summarizing article content using a pre-trained model.
"""
import logging
import os
import torch
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import sys # Added
import os # Added

# --- Add project root to sys.path for direct script execution & consistent imports ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End of path addition ---

# Use absolute import from src
from src.newssummary.content_extractor import extract_article_content

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ArticleSummarizer:
    """
    Article summarizer using a pre-trained language model.
    """
    
    def __init__(self, model_name="sshleifer/distilbart-cnn-12-6", cache_dir=None):
        """
        Initialize the ArticleSummarizer with a pre-trained model.
        
        Args:
            model_name (str): Name of the pre-trained model to use
            cache_dir (str): Directory to cache the model files
        """
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.summarizer = None
        self.initialized = False
        
    def _initialize_model(self):
        """
        Initialize the summarization model.
        """
        if self.initialized:
            return
            
        try:
            logging.info(f"Initializing summarization model: {self.model_name}")
            
            # Check for GPU availability
            device = 0 if torch.cuda.is_available() else -1
            device_info = "GPU" if device == 0 else "CPU"
            logging.info(f"Using {device_info} for summarization")
            
            # Initialize the summarization pipeline
            self.summarizer = pipeline(
                "summarization", 
                model=self.model_name, 
                tokenizer=self.model_name,
                device=device
            )
            
            self.initialized = True
            logging.info("Summarization model initialized successfully")
            
        except Exception as e:
            logging.error(f"Error initializing summarization model: {e}")
            # Fallback to a smaller model if the initial one fails
            try:
                logging.info("Attempting to initialize with a smaller model")
                self.model_name = "facebook/bart-large-cnn"
                self.summarizer = pipeline(
                    "summarization", 
                    model=self.model_name, 
                    tokenizer=self.model_name,
                    device=device
                )
                self.initialized = True
                logging.info("Fallback summarization model initialized successfully")
            except Exception as e2:
                logging.error(f"Error initializing fallback model: {e2}")
                raise
    
    def summarize(self, text, max_length=150, min_length=50, do_sample=False):
        """
        Generate a summary of the provided text.
        
        Args:
            text (str): The text to summarize
            max_length (int): Maximum length of the summary in words
            min_length (int): Minimum length of the summary in words
            do_sample (bool): Whether to use sampling for generation
            
        Returns:
            str: The generated summary
        """
        if not text:
            logging.warning("Empty text provided for summarization")
            return ""
            
        # Initialize model if not already done
        if not self.initialized:
            self._initialize_model()
            
        try:
            # Truncate text if it's too long (model has a max input length)
            # Most models have a limit around 1024 tokens
            tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            tokens = tokenizer.encode(text, truncation=True, max_length=1024)
            truncated_text = tokenizer.decode(tokens, skip_special_tokens=True)
            
            # Generate summary
            summary = self.summarizer(
                truncated_text, 
                max_length=max_length, 
                min_length=min_length,
                do_sample=do_sample
            )
            
            # Extract summary text
            summary_text = summary[0]['summary_text']
            
            logging.info(f"Successfully generated summary of length {len(summary_text)}")
            return summary_text
            
        except Exception as e:
            logging.error(f"Error generating summary: {e}")
            # Return a truncated version of the text as fallback
            fallback_summary = text[:500] + "..." if len(text) > 500 else text
            logging.info("Using truncated text as fallback summary")
            return fallback_summary


# Singleton instance for reuse
_summarizer_instance = None

def get_summarizer():
    """
    Get or create a singleton instance of ArticleSummarizer.
    
    Returns:
        ArticleSummarizer: The summarizer instance
    """
    global _summarizer_instance
    if _summarizer_instance is None:
        _summarizer_instance = ArticleSummarizer()
    return _summarizer_instance


def summarize_article(url, max_length=150, min_length=50, headers=None, cookies=None, cookie_string=None):
    """
    Extract and summarize an article from a URL.
    
    Args:
        url (str): The URL of the article to summarize
        max_length (int): Maximum length of the summary in words
        min_length (int): Minimum length of the summary in words
        headers (dict): Optional HTTP headers to use for the request
        cookies (dict): Optional cookies to use for the request
        cookie_string (str): Optional full cookie string from browser
        
    Returns:
        dict: Dictionary containing:
            - 'summary': The generated summary
            - 'success': Boolean indicating if summarization was successful
            - 'error': Error message if summarization failed
    """
    result = {
        'summary': '',
        'success': False,
        'error': None
    }
    
    try:
        # Extract article content
        content = extract_article_content(url, headers=headers, cookies=cookies, cookie_string=cookie_string)
        
        if not content['success']:
            result['error'] = f"Content extraction failed: {content['error']}"
            return result
            
        # Get article text
        article_text = content['text']
        
        if not article_text:
            result['error'] = "No article text extracted"
            return result
            
        # Get summarizer instance
        summarizer = get_summarizer()
        
        # Generate summary
        summary = summarizer.summarize(
            article_text,
            max_length=max_length,
            min_length=min_length
        )
        
        result['summary'] = summary
        result['success'] = True
        
        return result
        
    except Exception as e:
        logging.error(f"Error summarizing article from {url}: {e}")
        result['error'] = f"Summarization error: {str(e)}"
        return result
