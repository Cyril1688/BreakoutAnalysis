"""
Screenshot Service for capturing webpage screenshots using Playwright.
"""

import asyncio
import os
from pathlib import Path
from typing import Optional, Union, Dict, Any

# Lazy import playwright so missing dependency doesn't crash the whole pipeline
try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    async_playwright = Page = Browser = BrowserContext = None

from .config import (
    DEFAULT_IMAGE_TYPE,
    DEFAULT_VIEWPORT_WIDTH,
    DEFAULT_VIEWPORT_HEIGHT,
    DEFAULT_DEVICE_SCALE_FACTOR,
    BROWSER_TYPE,
    HEADLESS,
    NAVIGATION_TIMEOUT,
    WAIT_FOR_TIMEOUT,
    get_screenshot_dir
)
from .utils import (
    get_current_date_str,
    ensure_dir_exists,
    get_full_screenshot_path,
    log_screenshot_saved,
    log_error,
    logger
)


class ScreenshotService:
    """
    Service for capturing screenshots of webpages using Playwright.
    """
    
    def __init__(self):
        """Initialize the ScreenshotService."""
        self._browser = None
        self._context = None
    
    async def take_screenshot(
        self,
        page_url: str,
        file_name: str,
        img_type: str = DEFAULT_IMAGE_TYPE,
        viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
        viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
        device_scale_factor: float = DEFAULT_DEVICE_SCALE_FACTOR,
        wait_for_selector: Optional[str] = None,
        wait_for_load_state: Optional[str] = None,
        element_selector: Optional[str] = None,
        full_page: bool = True,
        clip: Optional[Dict[str, float]] = None,
        custom_date_dir: Optional[str] = None,
        auth_credentials: Optional[Dict[str, str]] = None,
        cookies: Optional[list] = None,
        extra_http_headers: Optional[Dict[str, str]] = None
    ) -> Optional[Path]:
        """
        Take a screenshot of a webpage.
        
        Args:
            page_url (str): URL of the webpage to screenshot
            file_name (str): Name for the screenshot file (without extension)
            img_type (str, optional): Image type/extension. Defaults to DEFAULT_IMAGE_TYPE.
            viewport_width (int, optional): Viewport width. Defaults to DEFAULT_VIEWPORT_WIDTH.
            viewport_height (int, optional): Viewport height. Defaults to DEFAULT_VIEWPORT_HEIGHT.
            device_scale_factor (float, optional): Device scale factor. Defaults to DEFAULT_DEVICE_SCALE_FACTOR.
            wait_for_selector (str, optional): Selector to wait for before taking screenshot. Defaults to None.
            wait_for_load_state (str, optional): Load state to wait for. Defaults to None.
            element_selector (str, optional): Selector for element to screenshot. Defaults to None.
            full_page (bool, optional): Whether to take full page screenshot. Defaults to True.
            clip (Dict[str, float], optional): Clip area for screenshot. Defaults to None.
            custom_date_dir (str, optional): Custom date directory. Defaults to None.
            auth_credentials (Dict[str, str], optional): HTTP authentication credentials. Defaults to None.
            cookies (list, optional): Cookies to set. Defaults to None.
            extra_http_headers (Dict[str, str], optional): Extra HTTP headers. Defaults to None.
            
        Returns:
            Optional[Path]: Path to the saved screenshot, or None if failed
        """
        try:
            # Create date directory
            date_str = custom_date_dir or get_current_date_str()
            screenshot_dir = get_screenshot_dir(date_str)
            ensure_dir_exists(screenshot_dir)
            
            # Get full screenshot path
            screenshot_path = get_full_screenshot_path(screenshot_dir, file_name, img_type)
            
            # Take screenshot
            async with async_playwright() as playwright:
                # Launch browser
                browser_module = getattr(playwright, BROWSER_TYPE)
                browser = await browser_module.launch(headless=HEADLESS)
                
                # Create browser context with viewport settings
                context_options = {
                    "viewport": {
                        "width": viewport_width,
                        "height": viewport_height
                    },
                    "device_scale_factor": device_scale_factor
                }
                
                # Add HTTP authentication if provided
                if auth_credentials:
                    context_options["http_credentials"] = auth_credentials
                
                context = await browser.new_context(**context_options)
                
                # Set cookies if provided
                if cookies:
                    await context.add_cookies(cookies)
                
                # Create page
                page = await context.new_page()
                
                # Set extra HTTP headers if provided
                if extra_http_headers:
                    await page.set_extra_http_headers(extra_http_headers)
                
                # Set navigation timeout
                page.set_default_navigation_timeout(NAVIGATION_TIMEOUT)
                
                # Navigate to URL
                await page.goto(page_url)
                
                # Wait for selector if provided
                if wait_for_selector:
                    await page.wait_for_selector(wait_for_selector, timeout=WAIT_FOR_TIMEOUT)
                
                # Wait for load state if provided
                if wait_for_load_state:
                    await page.wait_for_load_state(wait_for_load_state)
                
                # Take screenshot
                screenshot_options = {
                    "path": str(screenshot_path),
                    "type": img_type,
                    "full_page": full_page
                }
                
                # Add clip if provided
                if clip:
                    screenshot_options["clip"] = clip
                    # Full page and clip are mutually exclusive
                    screenshot_options.pop("full_page")
                
                if element_selector:
                    # Take screenshot of specific element
                    element = await page.query_selector(element_selector)
                    if element:
                        # Remove full_page option for element screenshots as it's not supported
                        if "full_page" in screenshot_options:
                            screenshot_options.pop("full_page")
                        await element.screenshot(**screenshot_options)
                    else:
                        raise ValueError(f"Element with selector '{element_selector}' not found")
                else:
                    # Take screenshot of entire page
                    await page.screenshot(**screenshot_options)
                
                # Close browser
                await browser.close()
            
            log_screenshot_saved(screenshot_path)
            return screenshot_path
        
        except Exception as e:
            log_error("Failed to take screenshot", e)
            return None
    
    @staticmethod
    async def take_tradingview_chart_screenshot(
        chart_url: str,
        file_name: str,
        img_type: str = DEFAULT_IMAGE_TYPE,
        custom_date_dir: Optional[str] = None,
        auth_credentials: Optional[Dict[str, str]] = None,
        cookies: Optional[list] = None
    ) -> Optional[Path]:
        """
        Take a screenshot of a TradingView chart.
        
        This is a specialized method for TradingView charts that uses
        optimized settings for capturing chart images.
        
        Args:
            chart_url (str): URL of the TradingView chart
            file_name (str): Name for the screenshot file (without extension)
            img_type (str, optional): Image type/extension. Defaults to DEFAULT_IMAGE_TYPE.
            custom_date_dir (str, optional): Custom date directory. Defaults to None.
            auth_credentials (Dict[str, str], optional): HTTP authentication credentials. Defaults to None.
            cookies (list, optional): Cookies to set. Defaults to None.
            
        Returns:
            Optional[Path]: Path to the saved screenshot, or None if failed
        """
        from .config import (
            TRADINGVIEW_WAIT_SELECTOR, 
            TRADINGVIEW_LOAD_STATE, 
            TRADINGVIEW_HEADERS,
            TRADINGVIEW_COOKIES,
            WAIT_FOR_TIMEOUT, 
            NAVIGATION_TIMEOUT
        )
        
        logger.info(f"Taking TradingView chart screenshot with the following parameters:")
        logger.info(f"  - URL: {chart_url}")
        logger.info(f"  - File name: {file_name}")
        logger.info(f"  - Wait selector: {TRADINGVIEW_WAIT_SELECTOR}")
        logger.info(f"  - Load state: {TRADINGVIEW_LOAD_STATE}")
        logger.info(f"  - Using authentication: Yes (headers and cookies)")
        logger.info(f"  - Wait timeout: {WAIT_FOR_TIMEOUT}ms")
        logger.info(f"  - Navigation timeout: {NAVIGATION_TIMEOUT}ms")
        
        # Use the cookies from config if none provided
        if cookies is None:
            cookies = TRADINGVIEW_COOKIES
            logger.info("Using default TradingView cookies from config")
        
        service = ScreenshotService()
        return await service.take_screenshot(
            page_url=chart_url,
            file_name=file_name,
            img_type=img_type,
            viewport_width=1920,
            viewport_height=1080,
            device_scale_factor=2,  # Higher resolution for charts
            wait_for_selector=TRADINGVIEW_WAIT_SELECTOR,
            wait_for_load_state=TRADINGVIEW_LOAD_STATE,
            full_page=True,  # Use full page screenshot like in the test script
            custom_date_dir=custom_date_dir,
            auth_credentials=auth_credentials,
            cookies=cookies,
            extra_http_headers=TRADINGVIEW_HEADERS
        )


# Synchronous wrapper for take_screenshot
def take_screenshot(*args, **kwargs):
    """
    Synchronous wrapper for take_screenshot.
    
    Args:
        *args: Positional arguments to pass to take_screenshot
        **kwargs: Keyword arguments to pass to take_screenshot
        
    Returns:
        Optional[Path]: Path to the saved screenshot, or None if failed
    """
    service = ScreenshotService()
    return asyncio.run(service.take_screenshot(*args, **kwargs))


# Synchronous wrapper for take_tradingview_chart_screenshot
def take_tradingview_chart_screenshot(*args, **kwargs):
    """
    Synchronous wrapper for take_tradingview_chart_screenshot.
    
    Args:
        *args: Positional arguments to pass to take_tradingview_chart_screenshot
        **kwargs: Keyword arguments to pass to take_tradingview_chart_screenshot
        
    Returns:
        Optional[Path]: Path to the saved screenshot, or None if failed
    """
    return asyncio.run(ScreenshotService.take_tradingview_chart_screenshot(*args, **kwargs))
