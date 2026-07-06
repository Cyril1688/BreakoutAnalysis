"""
Utility functions for the Screenshot API.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('screenshot_api')

def get_current_date_str():
    """
    Get the current date as a string in YYYY-MM-DD format.
    
    Returns:
        str: Current date in YYYY-MM-DD format
    """
    return datetime.now().strftime('%Y-%m-%d')

def ensure_dir_exists(directory):
    """
    Ensure that a directory exists, creating it if necessary.
    
    Args:
        directory (str or Path): Directory path to ensure exists
        
    Returns:
        Path: Path object for the directory
    """
    dir_path = Path(directory)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

def sanitize_filename(filename):
    """
    Sanitize a filename to ensure it's valid across operating systems.
    
    Args:
        filename (str): Original filename
        
    Returns:
        str: Sanitized filename
    """
    # Replace invalid characters with underscores
    sanitized = re.sub(r'[\\/*?:"<>|]', '_', filename)
    # Remove leading/trailing whitespace and periods
    sanitized = sanitized.strip().strip('.')
    # Ensure filename is not empty
    if not sanitized:
        sanitized = "screenshot"
    return sanitized

def get_full_screenshot_path(base_dir, filename, img_type="png"):
    """
    Get the full path for a screenshot file.
    
    Args:
        base_dir (str or Path): Base directory for the screenshot
        filename (str): Filename for the screenshot (without extension)
        img_type (str, optional): Image type/extension. Defaults to "png".
        
    Returns:
        Path: Full path for the screenshot file
    """
    sanitized_filename = sanitize_filename(filename)
    # Ensure the image type doesn't have a leading dot
    img_type = img_type.lstrip('.')
    return Path(base_dir) / f"{sanitized_filename}.{img_type}"

def log_screenshot_saved(filepath):
    """
    Log that a screenshot was saved successfully.
    
    Args:
        filepath (str or Path): Path where the screenshot was saved
    """
    logger.info(f"Screenshot saved to: {filepath}")

def log_error(message, error=None):
    """
    Log an error message.
    
    Args:
        message (str): Error message
        error (Exception, optional): Exception object. Defaults to None.
    """
    if error:
        logger.error(f"{message}: {str(error)}")
    else:
        logger.error(message)
