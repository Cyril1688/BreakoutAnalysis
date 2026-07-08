import logging
import os
import sys
import pandas as pd
from datetime import datetime, time as dt_time
import subprocess
import time
import pytz

# --- Add project root to sys.path ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End of path addition ---

try:
    from src.screeners.screener_client import get_all_screener_data, get_screener_data, get_market_config
    from src.llms.llm_client import LLMClient
    logging.info("Successfully imported required modules.")
except ImportError as e:
    logging.error(f"Failed to import required modules: {e}")
    sys.exit(1)

# 惰性导入 NewsCollector（依赖 alpaca-py，GitHub Actions 中可能未安装）
try:
    from src.newscollector.news_collector import NewsCollector
    NEWS_COLLECTOR_AVAILABLE = True
except ImportError:
    NEWS_COLLECTOR_AVAILABLE = False
    logging.warning("NewsCollector not available (alpaca-py not installed). US news will be skipped.")

# 惰性导入 AlpacaClient（依赖 alpaca-py，GitHub Actions 中可能未安装）
try:
    from src.utils.alpaca_client import AlpacaClient
    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logging.warning("AlpacaClient not available (alpaca-py not installed). US historical filtering disabled.")

# Try to import China news collector (optional)
try:
    from src.newscollector.china_news import ChinaNewsCollector
    CHINA_NEWS_AVAILABLE = True
except ImportError:
    CHINA_NEWS_AVAILABLE = False
    logging.warning("China news collector not available. A-share news will be skipped.")

# Try to import Feishu notifier (optional)
try:
    from src.notifications.feishu_notifier import send_notifications as send_feishu, load_config as load_feishu_config
    FEISHU_AVAILABLE = True
except ImportError as e:
    FEISHU_AVAILABLE = False
    logging.warning(f"Feishu notifier not available: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - TRADEALERTS - %(levelname)s - %(message)s')

# --- Constants ---
ANALYSIS_BASE_DIR = "analysis"
import json # Add json import

NOTIFY_JSON_PATH = "src/notifications/notify.json"
EMAIL_NOTIFY_JSON_PATH = "src/notifications/email_notify.json"
# NOTIFY_SCRIPT_PATH = "src/notifications/send_notification.bat" # No longer needed
DISCORD_NOTIFIER_SCRIPT_PATH = "src/notifications/discord_notifier.py"
EMAIL_NOTIFIER_SCRIPT_PATH = "src/mail_utils/send_email.py"
DATE_FORMAT = "%Y-%m-%d"

# 延迟导入 MarketBriefingClient（在 send_market_briefing 函数内导入）
# 以避免模型依赖 SDK 未安装时启动崩溃

# --- Load top-level config for use throughout the module ---
_CONFIG_PATH = os.path.join(project_root, 'config', 'config.json')
try:
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as _f:
        _GLOBAL_CONFIG = json.load(_f)
except Exception:
    _GLOBAL_CONFIG = {}

# TradingView chart ID (from config or fallback to empty string)
_TV_CHART_ID = _GLOBAL_CONFIG.get('tradingview', {}).get('chart_id', '')
_TV_COOKIES_SET = bool(_GLOBAL_CONFIG.get('tradingview', {}).get('cookies', {}).get('sessionid', ''))

def get_today_analysis_path():
    """Gets the path for today's analysis JSON file."""
    today_str = datetime.now().strftime(DATE_FORMAT)
    today_dir = os.path.join(ANALYSIS_BASE_DIR, today_str)
    os.makedirs(today_dir, exist_ok=True)
    # Change extension to .json
    return os.path.join(today_dir, "analysis.json") 

def load_processed_tickers(analysis_file_path):
    """Loads processed tickers from the daily analysis JSON file."""
    processed_data = {}
    if os.path.exists(analysis_file_path):
        try:
            with open(analysis_file_path, 'r') as f:
                processed_data = json.load(f)
            logging.info(f"Loaded {len(processed_data)} previously processed tickers from {analysis_file_path}")
        except json.JSONDecodeError:
            logging.error(f"Error decoding JSON from {analysis_file_path}. Starting fresh.")
            # Optionally backup the corrupted file here
            processed_data = {}
        except Exception as e:
            logging.error(f"Error reading analysis file {analysis_file_path}: {e}")
            processed_data = {}
    else:
        logging.info(f"Analysis file {analysis_file_path} not found. Starting fresh.")
        
    return set(processed_data.keys()) # Return only the set of tickers

def save_analysis(analysis_file_path, screener_data_df):
    """Loads existing data, updates with new data, and saves to the analysis JSON file."""
    if screener_data_df.empty:
        logging.info("No new screener data to save.")
        return
        
    # Ensure 'Ticker' column exists before proceeding
    if 'Ticker' not in screener_data_df.columns:
        logging.error("Cannot save analysis: DataFrame is missing 'Ticker' column.")
        return

    # Load existing data
    processed_data = {}
    if os.path.exists(analysis_file_path):
        try:
            with open(analysis_file_path, 'r') as f:
                processed_data = json.load(f)
            logging.info(f"Loaded {len(processed_data)} existing records from {analysis_file_path}")
        except json.JSONDecodeError:
            logging.warning(f"Could not decode existing JSON from {analysis_file_path}. Overwriting with new data.")
            processed_data = {}
        except Exception as e:
            logging.error(f"Error reading existing analysis file {analysis_file_path}: {e}. Starting fresh.")
            processed_data = {}

    # Replace NaN values with None (which becomes JSON null) before converting
    screener_data_df_cleaned = screener_data_df.where(pd.notna(screener_data_df), None)

    # Convert cleaned DataFrame data to dictionary format {ticker: {col: val, ...}}
    # Use 'records' orientation and then build the dict keyed by Ticker
    new_data_list = screener_data_df_cleaned.to_dict(orient='records')
    new_data_dict = {record['Ticker']: record for record in new_data_list if 'Ticker' in record}

    # Update existing data with new data (overwrites tickers if they reappear)
    processed_data.update(new_data_dict)
    
    # Add a timestamp for the last update
    processed_data['_last_updated'] = datetime.now().isoformat()

    # Clean the entire dictionary recursively before saving
    processed_data_cleaned = clean_value_for_json(processed_data)

    # Save cleaned data back to JSON
    try:
        with open(analysis_file_path, 'w') as f:
            json.dump(processed_data_cleaned, f, indent=4) # Use indent for readability
        # Log count based on the original processed_data before cleaning added _last_updated potentially
        log_count = len(processed_data) - 1 if '_last_updated' in processed_data else len(processed_data)
        logging.info(f"Saved/Updated {len(new_data_dict)} stocks. Total records in {analysis_file_path}: {log_count}") 
    except Exception as e:
        logging.error(f"Error writing to analysis JSON file {analysis_file_path}: {e}")


def clean_value_for_json(value):
    """Recursively cleans dict/list values for JSON compatibility (NaN, Inf -> None)."""
    if isinstance(value, dict):
        return {k: clean_value_for_json(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [clean_value_for_json(item) for item in value]
    elif isinstance(value, float):
        if pd.isna(value) or value == float('inf') or value == float('-inf'):
            return None # Convert NaN, Infinity, -Infinity to None (JSON null)
        return value
    else:
        return value

# --- LLM Output Parsing ---
def parse_llm_analysis(raw_analysis: str) -> str:
    """Removes the <think> block and surrounding whitespace from raw LLM output."""
    if not raw_analysis or not isinstance(raw_analysis, str):
        return "LLM analysis not available or invalid."

    think_end_tag = "</think>"
    think_end_index = raw_analysis.find(think_end_tag)

    if think_end_index != -1:
        analysis_part = raw_analysis[think_end_index + len(think_end_tag):]
        return analysis_part.strip()
    else:
        # If no <think> block, assume the whole output is the analysis
        # Check for common error messages from the client/model itself
        if raw_analysis.startswith("Error:") or raw_analysis.startswith("LLM analysis not available"):
             return raw_analysis # Return error messages as is
        # Otherwise, return the stripped raw analysis
        return raw_analysis.strip()


def format_large_number(num, market='us'):
    """Formats large numbers into K, M, B for US stocks or 万/亿 for A-shares."""
    if pd.isna(num):
        return "N/A"
    num = float(num)
    
    if market == 'china':
        # Chinese market uses 万 (10K) and 亿 (100M)
        if num >= 1_000_000_000:  # 10亿+
            return f"{num / 1_000_000_000:.2f}亿"
        elif num >= 10_000:  # 1万+
            return f"{num / 10_000:.2f}万"
        else:
            if num == int(num):
                return f"{int(num)}"
            else:
                return f"{num:.2f}"
    else:
        # US market: K, M, B
        if num >= 1_000_000_000:
            return f"{num / 1_000_000_000:.2f}B"
        elif num >= 1_000_000:
            return f"{num / 1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num / 1_000:.1f}K"
        else:
            if num == int(num):
                 return f"{int(num)}"
            else:
                 return f"{num:.2f}"


def prepare_notification_content(new_stocks_df, llm_client: LLMClient, news_data=None, market='us'):
    """
    Prepares a list of dictionaries, each representing a stock's structured data for notification,
    including LLM analysis.

    Args:
        new_stocks_df (pd.DataFrame): DataFrame containing data for new stocks.
        llm_client (LLMClient): Initialized LLM client instance.
        news_data (dict, optional): Dictionary containing news items keyed by ticker. Defaults to None.
        market (str): 'us' for US stocks, 'china' for A-shares.

    Returns:
        list: A list of dictionaries, where each dict contains structured info for one stock.
    """
    if new_stocks_df.empty:
        return [] # Return empty list if no new stocks
    if news_data is None:
        news_data = {}

    stock_notifications = [] # List to hold individual stock notification dicts

    # Define columns needed from the DataFrame
    notify_cols = [
        'Ticker', 'CompanyName', 'Price', 'ChangePercent', 'Volume', 'MarketCap', 'Sector',
        'RelVolume',
        'RSI', 'MACD_MACD', 'MACD_Signal',
        'SMA10', 'SMA20', 'SMA50', 'SMA100', 'SMA200', 'VWAP',
        'Pivot_S1', 'Pivot_S2', 'Pivot_S3', 'Pivot_R1', 'Pivot_R2', 'Pivot_R3'
    ]

    # Import screenshot service
    from src.screenshotapi.screenshot_service import take_tradingview_chart_screenshot
    
    # Initialize AlpacaClient for getting exchange information (if available)
    alpaca_client = None
    if ALPACA_AVAILABLE:
        try:
            alpaca_client = AlpacaClient()
        except Exception as e:
            logging.warning(f"AlpacaClient init failed: {e}")
    
    available_cols = [col for col in notify_cols if col in new_stocks_df.columns]

    # Helper function to get current date string for screenshot directory
    def get_current_date_str():
        return datetime.now().strftime(DATE_FORMAT)

    for _, row in new_stocks_df.iterrows():
        stock_data = {} # Dictionary for the current stock
        ticker = row.get('Ticker', 'N/A')
        stock_data['ticker'] = ticker
        stock_data['company_name'] = row.get('CompanyName', 'N/A')

        # Generate TradingView chart URL and download screenshot
        chart_image_path = None # Initialize path as None
        try:
            # Get the exchange:symbol format from AlpacaClient
            exchange_symbol = row.get('Exchange')

            # Skip screenshot if TradingView chart ID not configured
            if not _TV_CHART_ID or _TV_CHART_ID == 'YOUR_TRADINGVIEW_CHART_ID':
                logging.debug(f"TradingView chart_id not configured in config.json. Skipping screenshot for {ticker}.")
            elif not _TV_COOKIES_SET:
                logging.debug(f"TradingView cookies not configured. Skipping authenticated screenshot for {ticker}.")
            else:
                chart_url = f"https://www.tradingview.com/chart/{_TV_CHART_ID}/?symbol={exchange_symbol}%3A{ticker}"
                screenshot_filename = f"{ticker}_chart"

                logging.info(f"Requesting TradingView chart for {ticker}")
                logging.info(f"Using exchange symbol: {exchange_symbol}")
                logging.info(f"Chart URL: {chart_url}")

                chart_path_obj = take_tradingview_chart_screenshot(
                    chart_url=chart_url,
                    file_name=screenshot_filename,
                    custom_date_dir=get_current_date_str()
                )

                if chart_path_obj:
                    chart_image_path = str(chart_path_obj)
                    logging.info(f"Successfully saved TradingView chart for {ticker} to {chart_image_path}")
                else:
                    logging.warning(f"Failed to download TradingView chart for {ticker} - screenshot service returned None")
        except Exception as e:
            logging.error(f"Error downloading TradingView chart for {ticker}: {e}", exc_info=True)
        
        # Add the chart path to the stock_data dictionary if it exists
        if chart_image_path:
            stock_data['chart_image_path'] = chart_image_path

        # Build market-aware display names for columns
        display_names = {
            'Price': '价格' if market == 'china' else 'Price',
            'ChangePercent': '涨跌幅' if market == 'china' else 'Change%',
            'Volume': '成交量' if market == 'china' else 'Volume',
            'MarketCap': '总市值' if market == 'china' else 'MarketCap',
            'Sector': '板块' if market == 'china' else 'Sector',
            'RelVolume': '量比' if market == 'china' else 'RelVol',
        }

        # --- Core Data ---
        core_data_lines = []
        core_cols_to_display = ['Price', 'ChangePercent', 'Volume', 'MarketCap', 'Sector', 'RelVolume'] 
        for col in core_cols_to_display:
             if col in available_cols: 
                display_name = display_names.get(col, col)
                value = row.get(col)
                value_str = "N/A"
                if pd.notna(value):
                    if col in ['Volume', 'MarketCap']:
                        value_str = format_large_number(value, market=market)
                        if market == 'china' and col == 'Price':
                            value_str = f"¥{value_str}"
                    elif col == 'ChangePercent':
                         value_str = f"{value:.2f}%"
                    elif isinstance(value, float):
                        value_str = f"{value:.2f}"
                    else:
                        value_str = str(value)
                core_data_lines.append(f"**{display_name}:** {value_str}")
        stock_data['core_data_str'] = "\n".join(core_data_lines) if core_data_lines else "N/A"

        # --- Technicals ---
        technicals_lines = []
        tech_display = {
            'RSI': 'RSI',
            'MACD_MACD': 'MACD',
            'MACD_Signal': 'MACD信号',
            'SMA10': 'SMA10',
            'SMA20': 'SMA20',
            'SMA50': 'SMA50',
            'SMA100': 'SMA100',
            'SMA200': 'SMA200',
            'VWAP': 'VWAP',
        }
        tech_cols = ['RSI', 'MACD_MACD', 'MACD_Signal', 'SMA10', 'SMA20', 'SMA50', 'SMA100', 'SMA200', 'VWAP']
        tech_vals = {}
        for col in tech_cols:
            if col in available_cols:
                value = row.get(col)
                if isinstance(value, (int, float)) and pd.notna(value):
                    tech_vals[col] = float(value)
        # 兜底：若该股票在抓取阶段未计算到技术指标（如超出前 30 只），现算一次（仅 A 股）
        if not tech_vals and market == 'china':
            try:
                from src.screeners.china_screener import get_technical_indicators
                ind = get_technical_indicators(ticker)
                for col in tech_cols:
                    if col in ind and ind[col] is not None:
                        tech_vals[col] = float(ind[col])
            except Exception as te:
                logging.warning(f"Fallback technical calc failed for {ticker}: {te}")
        for col in tech_cols:
            if col in tech_vals:
                technicals_lines.append(f"**{tech_display.get(col, col)}:** {tech_vals[col]:.2f}")
        stock_data['technicals_str'] = "\n".join(technicals_lines) if technicals_lines else "N/A"

        # --- News ---
        stock_news_items = news_data.get(ticker, []) if news_data else []
        news_lines = []
        if stock_news_items:
            news_limit = 3 # Limit the number of news items per stock
            for idx, news_item in enumerate(stock_news_items[:news_limit]):
                title = news_item.get('title', 'N/A')
                summary = news_item.get('summary')
                # Truncate long summaries
                if summary and len(summary) > 150:
                    summary = summary[:150] + "..."
                
                news_lines.append(f"**- {title}** ({news_item.get('published_datetime', 'N/A')})")
                if summary:
                    news_lines.append(f"  {summary}") # Indent summary slightly

            if len(stock_news_items) > news_limit:
                news_lines.append(f"... (and {len(stock_news_items) - news_limit} more articles)")
        stock_data['news_str'] = "\n".join(news_lines) if news_lines else "No recent news found."

        # --- A股增强层 (板块/资金流/新闻, 非阻塞) ---
        if market == 'china':
            try:
                from src.enrichment.astock_enrich import enrich_stock
                stock_data['enrich'] = enrich_stock(ticker, row.get('CompanyName', ''))
            except Exception as e:
                logging.warning(f"A股增强层调用失败 {ticker}: {e}")
                stock_data['enrich'] = None

        # --- LLM Analysis ---
        parsed_analysis = "LLM analysis skipped (client not available)." # Default message
        if llm_client: # Only proceed if client is available and initialized properly
            try:
                # Prepare data dictionary for the LLM
                # Select relevant columns, handle NaN/None before passing
                llm_input_data = row[available_cols].where(pd.notna(row[available_cols]), None).to_dict()
                # Add news specifically for this ticker to the LLM input
                llm_input_data['News'] = news_data.get(ticker, []) if news_data else []
                
                # Add chart image path if available
                if 'chart_image_path' in stock_data:
                    llm_input_data['chart_image_path'] = stock_data['chart_image_path']

                logging.info(f"Requesting LLM analysis for {ticker}...")
                # Log the input data being sent to the LLM for debugging
                # logging.debug(f"LLM input data for {ticker}: {json.dumps(llm_input_data, indent=2)}") 
                raw_analysis = llm_client.analyze_stock(llm_input_data)
                # Log the raw response from the LLM client
                logging.info(f"Raw LLM analysis received for {ticker}: {raw_analysis}") 
                parsed_analysis = parse_llm_analysis(raw_analysis) # Use the helper function
                logging.info(f"Parsed LLM analysis for {ticker}: {parsed_analysis}")
                # logging.debug(f"Parsed LLM analysis for {ticker}:\n{parsed_analysis}")
            except Exception as e:
                 logging.error(f"Error during LLM analysis for {ticker}: {e}", exc_info=True)
                 parsed_analysis = f"Error during LLM analysis: {e}" # Include error in output
        else:
             logging.warning(f"LLM client not available for {ticker}, skipping analysis.")

        stock_data['llm_analysis_str'] = parsed_analysis # Assign the result or default/error message

        stock_notifications.append(stock_data) # Add the structured data for this stock

    return stock_notifications

def update_notify_json(structured_data):
    """Overwrites the notify.json and email_notify.json files with the new structured data."""
    if not structured_data:
        logging.info("No structured notification data to write.")
        for path in [NOTIFY_JSON_PATH, EMAIL_NOTIFY_JSON_PATH]:
            try:
                with open(path, 'w') as f:
                    json.dump([], f)
                logging.info(f"Cleared notification file: {path}")
            except Exception as e:
                logging.error(f"Error clearing notification file {path}: {e}")
        return

    for path in [NOTIFY_JSON_PATH, EMAIL_NOTIFY_JSON_PATH]:
        try:
            with open(path, 'w') as f:
                json.dump(structured_data, f, indent=4, default=str)
            logging.info(f"Updated notification file: {path} with {len(structured_data)} item(s).")
        except Exception as e:
            logging.error(f"Error writing to notification file {path}: {e}")

def send_notifications():
    """Executes Discord and Feishu notifications."""

    # --- Send Discord Notifications ---
    discord_webhook = _GLOBAL_CONFIG.get('discord', {}).get('webhook_url', '')
    if not discord_webhook or discord_webhook in ('', 'YOUR_DISCORD_STOCK_ALERTS_WEBHOOK_URL'):
        logging.info("Discord webhook not configured. Skipping Discord notifications.")
    else:
        if not os.path.exists(DISCORD_NOTIFIER_SCRIPT_PATH):
            logging.error(f"Discord notifier script not found: {DISCORD_NOTIFIER_SCRIPT_PATH}")
        else:
            python_executable = sys.executable 
            script_path = os.path.abspath(DISCORD_NOTIFIER_SCRIPT_PATH) 
            try:
                logging.info(f"Executing Discord notifier script: {script_path}")
                result = subprocess.run(
                    [python_executable, script_path], 
                    check=True, 
                    capture_output=True, 
                    text=True,
                    cwd=project_root
                )
                logging.info("Discord notifier script executed successfully.")
                logging.info(f"Script Output:\n{result.stdout}")
                if result.stderr:
                    logging.warning(f"Script Error Output:\n{result.stderr}")
            except subprocess.CalledProcessError as e:
                logging.error(f"Discord notifier script failed with exit code {e.returncode}")
                logging.error(f"Script Output:\n{e.stdout}")
                logging.error(f"Script Error Output:\n{e.stderr}")
            except Exception as e:
                logging.error(f"Error executing Discord notifier script {script_path}: {e}")

    # --- Send Feishu Notifications ---
    feishu_webhook = _GLOBAL_CONFIG.get('feishu', {}).get('webhook_url', '')
    if not feishu_webhook or feishu_webhook in ('', 'YOUR_FEISHU_WEBHOOK_URL'):
        logging.info("飞书 Webhook 未配置，跳过飞书通知。")
    elif FEISHU_AVAILABLE:
        try:
            notify_json_path = os.path.join(project_root, NOTIFY_JSON_PATH)
            if os.path.exists(notify_json_path):
                with open(notify_json_path, 'r', encoding='utf-8') as f:
                    feishu_data = json.load(f)
                if feishu_data:
                    feishu_config = load_feishu_config()
                    if feishu_config:
                        webhook = feishu_config.get('webhook_url', '')
                        send_feishu(webhook, feishu_data)
        except Exception as e:
            logging.error(f"发送飞书通知失败: {e}")
    else:
        logging.warning("飞书通知模块不可用 (feishu_notifier.py 未找到)")

    # Email sending is now handled exclusively by send_email_stock_alerts()


def is_market_hours():
    """
    Checks if the current time is within the defined trading hours
    (Mon-Fri, 4:00 AM to 1:00 PM PST/PDT) for US markets.
    """
    # Define the Pacific Time Zone
    pacific_tz = pytz.timezone('America/Los_Angeles')
    
    # Get the current time in UTC and convert it to Pacific Time
    now_utc = datetime.now(pytz.utc)
    now_pacific = now_utc.astimezone(pacific_tz)
    
    # Define start and end times
    start_time = dt_time(4, 0)  # 4:00 AM
    end_time = dt_time(13, 0) # 1:00 PM
    
    # Define the specific delay window
    delay_start_time = dt_time(6, 30) # 6:30 AM
    delay_end_time = dt_time(6, 50)   # 6:50 AM

    # Check if it's a weekday (Monday=0, Sunday=6)
    is_weekday = now_pacific.weekday() < 5
    
    # Check if the current time is within the main trading window
    is_within_main_window = start_time <= now_pacific.time() < end_time

    # Check if the current time is within the delayed streaming window
    is_within_delay_window = delay_start_time <= now_pacific.time() < delay_end_time
    
    if not is_weekday:
        logging.info(f"Skipping cycle: It's a weekend. Current time: {now_pacific.strftime('%A, %H:%M:%S')}")
        return False
        
    if not is_within_main_window:
        logging.info(f"Skipping cycle: Outside of trading hours (4 AM - 1 PM PST). Current time: {now_pacific.strftime('%H:%M:%S')}")
        return False
    
    # If within the main window, but also within the specific delay window, return False
    if is_within_delay_window:
        logging.info(f"Skipping cycle: Within known delayed streaming period (6:30 AM - 6:50 AM PST). Current time: {now_pacific.strftime('%H:%M:%S')}")
        return False
        
    logging.info(f"Within trading hours. Proceeding with cycle. Current time: {now_pacific.strftime('%A, %H:%M:%S')}")
    return True


def is_any_market_open():
    """
    Checks if ANY enabled market is currently open.
    Returns dict of open/closed status per market.
    """
    markets = get_market_config()
    status = {}

    # Check US market
    if markets.get('us', True):
        try:
            from src.screeners.us_screener import is_us_market_hours
            status['us'] = is_us_market_hours()
        except ImportError:
            # Fallback to the Pacific-based heuristic if us_screener is unavailable
            status['us'] = is_market_hours()
    else:
        status['us'] = False

    # Check China market
    if markets.get('china', False):
        try:
            from src.screeners.china_screener import is_china_market_hours
            status['china'] = is_china_market_hours()
        except ImportError:
            status['china'] = False
    else:
        status['china'] = False

    any_open = any(status.values())
    logging.info(f"Market status: US={'OPEN' if status.get('us') else 'CLOSED'}, "
                 f"China={'OPEN' if status.get('china') else 'CLOSED'}")
    return status


def is_email_enabled():
    """
    Checks if email communication is enabled in the config.
    Returns True if emails should be sent, False otherwise.
    """
    try:
        config_path = os.path.join(project_root, 'config', 'config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Check the global send_email setting
            email_config = config.get('email', {})
            send_email = email_config.get('send_email', True)  # Default to True if not specified
            
            if not send_email:
                logging.info("Email communication is disabled in config (send_email: false)")
                return False
            
            return True
        else:
            logging.warning("Config file not found, defaulting to email enabled")
            return True
    except Exception as e:
        logging.error(f"Error reading config for email setting: {e}, defaulting to email enabled")
        return True


def send_market_briefing():
    """Checks time and sends market briefing if appropriate."""
    pacific_tz = pytz.timezone('America/Los_Angeles')
    now_pacific = datetime.now(pacific_tz)
    today_str = now_pacific.strftime(DATE_FORMAT)
    today_dir = os.path.join(ANALYSIS_BASE_DIR, today_str)
    os.makedirs(today_dir, exist_ok=True)

    # --- Define Time Windows ---
    am_start = dt_time(7, 0)
    am_end = dt_time(8, 0)
    pm_start = dt_time(12, 30)
    pm_end = dt_time(13, 0)

    # --- Determine which briefing to send ---
    briefing_type = None
    if am_start <= now_pacific.time() <= am_end:
        briefing_type = "am"
    elif pm_start <= now_pacific.time() <= pm_end:
        briefing_type = "pm"

    if not briefing_type:
        logging.info("Not within a market briefing time window.")
        return

    marker_filename = f"market_briefing_{briefing_type}_sent"
    briefing_marker_path = os.path.join(today_dir, marker_filename)

    if os.path.exists(briefing_marker_path):
        logging.info(f"Market briefing for {briefing_type.upper()} already sent today.")
        return

    logging.info(f"Time to send the {briefing_type.upper()} market briefing.")

    # --- Initialize and send briefing ---
    try:
        from src.llms.llm_stock_market_client import MarketBriefingClient
        market_briefing_client = MarketBriefingClient()
        briefing_text = market_briefing_client.get_market_briefing()
        if briefing_text:
            briefing_notification = [{
                "title": f"Market Briefing - {now_pacific.strftime('%I:%M %p PST')}",
                "content": briefing_text
            }]
            update_notify_json(briefing_notification)
            send_notifications()

            # Also send email notification for market briefing
            if is_email_enabled():
                try:
                    from src.mail_utils.send_email import send_email_notification
                    # Prepare email content as a list with one dict item
                    email_content = [{
                        "title": f"Market Briefing - {now_pacific.strftime('%I:%M %p PST')}",
                        "content": briefing_text
                    }]
                    # Load config for email
                    config_path = os.path.join(project_root, 'config', 'config.json')
                    config = {}
                    if os.path.exists(config_path):
                        with open(config_path, 'r', encoding='utf-8') as f:
                            config = json.load(f)
                    send_email_notification(config, email_content)
                    logging.info("Market briefing email sent successfully.")
                except Exception as email_exc:
                    logging.error(f"Failed to send market briefing email: {email_exc}")

            with open(briefing_marker_path, 'w') as f:
                f.write("sent")
            logging.info(f"Successfully sent {briefing_type.upper()} market briefing and marked as sent.")
        else:
            logging.warning("Market briefing text is empty. Skipping notification.")
    except Exception as e:
        logging.error(f"Failed to send market briefing: {e}")


def send_china_market_briefing():
    """Send A-share market briefing (once per day)."""
    try:
        from src.llms.china_market_briefing import ChinaMarketBriefingClient
        
        china_tz = pytz.timezone('Asia/Shanghai')
        now_china = datetime.now(china_tz)
        today_str = now_china.strftime(DATE_FORMAT)
        today_dir = os.path.join(ANALYSIS_BASE_DIR, today_str)
        os.makedirs(today_dir, exist_ok=True)

        # Send once in morning (9:30-10:00) and once after close (15:00-15:30)
        am_start = dt_time(9, 30)
        am_end = dt_time(10, 0)
        pm_start = dt_time(15, 0)
        pm_end = dt_time(15, 30)
        
        briefing_type = None
        if am_start <= now_china.time() <= am_end:
            briefing_type = "am"
        elif pm_start <= now_china.time() <= pm_end:
            briefing_type = "pm"
        
        if not briefing_type:
            return

        marker_filename = f"china_briefing_{briefing_type}_sent"
        briefing_marker_path = os.path.join(today_dir, marker_filename)
        
        if os.path.exists(briefing_marker_path):
            logging.info(f"China market briefing for {briefing_type} already sent today.")
            return

        logging.info(f"Sending China market {briefing_type} briefing...")
        briefing_client = ChinaMarketBriefingClient()
        briefing_text = briefing_client.generate_china_briefing()

        if briefing_text:
            briefing_notification = [{
                "title": f"🇨🇳 A股市场简报 - {now_china.strftime('%H:%M')}",
                "content": briefing_text
            }]
            update_notify_json(briefing_notification)
            send_notifications()

            with open(briefing_marker_path, 'w') as f:
                f.write("sent")
            logging.info(f"China market {briefing_type} briefing sent successfully.")
    except ImportError as e:
        logging.debug(f"China market briefing not available: {e}")
    except Exception as e:
        logging.error(f"Error sending China market briefing: {e}")


def is_email_alert_time():
    """
    Checks if the current time is within email alert windows:
    - Morning: 7:00-8:00 AM PST (narrowed to reduce multiple sends)
    - Afternoon: 12:00-1:00 PM PST
    Returns tuple: (is_time, batch_type) where batch_type is 'morning' or 'afternoon'
    """
    pacific_tz = pytz.timezone('America/Los_Angeles')
    now_pacific = datetime.now(pacific_tz)
    
    # Define email alert time windows (morning narrowed to 30 minutes)
    morning_start = dt_time(7, 0)   # 7:00 AM
    morning_end = dt_time(8, 00)    # 7:30 AM
    afternoon_start = dt_time(12, 0) # 12:00 PM
    afternoon_end = dt_time(13, 0)   # 1:00 PM
    
    current_time = now_pacific.time()
    
    # Check if it's a weekday
    if now_pacific.weekday() >= 5:  # Saturday=5, Sunday=6
        return False, None
    
    if morning_start <= current_time <= morning_end:
        return True, 'morning'
    elif afternoon_start <= current_time <= afternoon_end:
        return True, 'afternoon'
    
    return False, None


def get_discord_notified_stocks_path(today_dir):
    """Gets the path for discord-notified-stocks.json file."""
    return os.path.join(today_dir, "discord-notified-stocks.json")


def get_email_notified_stocks_path(today_dir):
    """Gets the path for email-notified-stocks.json file."""
    return os.path.join(today_dir, "email-notified-stocks.json")


def save_discord_notified_stocks(today_dir, structured_data):
    """Saves the current structured notification data to discord-notified-stocks.json."""
    discord_file_path = get_discord_notified_stocks_path(today_dir)
    
    # Load existing data if file exists
    existing_data = []
    if os.path.exists(discord_file_path):
        try:
            with open(discord_file_path, 'r') as f:
                existing_data = json.load(f)
        except Exception as e:
            logging.error(f"Error reading existing discord notified stocks file: {e}")
            existing_data = []
    
    # Add new stocks to existing data (avoid duplicates by ticker)
    existing_tickers = {item.get('ticker') for item in existing_data if 'ticker' in item}
    new_stocks = [item for item in structured_data if 'ticker' in item and item.get('ticker') not in existing_tickers]
    
    # Also add non-stock items (like market briefings)
    non_stock_items = [item for item in structured_data if 'ticker' not in item]
    
    # Combine all data
    all_data = existing_data + new_stocks + non_stock_items
    
    try:
        with open(discord_file_path, 'w') as f:
            json.dump(all_data, f, indent=4)
        logging.info(f"Saved {len(new_stocks)} new stocks to discord-notified-stocks.json. Total: {len(all_data)}")
    except Exception as e:
        logging.error(f"Error saving discord notified stocks file: {e}")


def load_discord_notified_stocks(today_dir):
    """Loads all stocks from discord-notified-stocks.json."""
    discord_file_path = get_discord_notified_stocks_path(today_dir)
    
    if not os.path.exists(discord_file_path):
        return []
    
    try:
        with open(discord_file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading discord notified stocks file: {e}")
        return []


def load_email_notified_stocks(today_dir):
    """Loads stocks that have already been sent via email."""
    email_file_path = get_email_notified_stocks_path(today_dir)
    
    if not os.path.exists(email_file_path):
        return []
    
    try:
        with open(email_file_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading email notified stocks file: {e}")
        return []


def save_email_notified_stocks(today_dir, stocks_data):
    """Saves stocks that have been sent via email to email-notified-stocks.json."""
    email_file_path = get_email_notified_stocks_path(today_dir)
    
    try:
        with open(email_file_path, 'w') as f:
            json.dump(stocks_data, f, indent=4)
        logging.info(f"Saved {len(stocks_data)} stocks to email-notified-stocks.json")
    except Exception as e:
        logging.error(f"Error saving email notified stocks file: {e}")


def get_new_stocks_for_email(today_dir, batch_type):
    """
    Gets stocks that should be sent in the current email batch.
    For morning batch: all stocks collected so far
    For afternoon batch: only new stocks not sent in morning batch
    """
    discord_stocks = load_discord_notified_stocks(today_dir)
    
    if batch_type == 'morning':
        # Morning batch: send all stocks collected so far
        stock_items = [item for item in discord_stocks if 'ticker' in item]
        logging.info(f"Morning batch: Found {len(stock_items)} stocks to send")
        return stock_items
    
    elif batch_type == 'afternoon':
        # Afternoon batch: only send new stocks not already emailed
        email_notified_stocks = load_email_notified_stocks(today_dir)
        email_notified_tickers = {item.get('ticker') for item in email_notified_stocks if 'ticker' in item}
        
        # Get only stock items from discord that haven't been emailed
        new_stock_items = [
            item for item in discord_stocks 
            if 'ticker' in item and item.get('ticker') not in email_notified_tickers
        ]
        
        logging.info(f"Afternoon batch: Found {len(new_stock_items)} new stocks to send (out of {len(discord_stocks)} total)")
        return new_stock_items
    
    return []


def send_email_stock_alerts():
    """
    Checks if it's time to send email stock alerts and sends them if appropriate.
    Handles both morning (7-8:00 AM) and afternoon (12-1 PM) batches.
    """
    # Check if email is globally enabled
    if not is_email_enabled():
        return  # Email is disabled, skip all email operations
    
    is_time, batch_type = is_email_alert_time()
    
    if not is_time:
        return  # Not time for email alerts
    
    pacific_tz = pytz.timezone('America/Los_Angeles')
    now_pacific = datetime.now(pacific_tz)
    today_str = now_pacific.strftime(DATE_FORMAT)
    today_dir = os.path.join(ANALYSIS_BASE_DIR, today_str)
    os.makedirs(today_dir, exist_ok=True)
    
    # Check if this batch has already been sent
    email_marker_path = os.path.join(today_dir, f"email_stocks_{batch_type}_sent")
    if os.path.exists(email_marker_path):
        logging.info(f"Email stock alerts for {batch_type} batch already sent today. Marker path: {email_marker_path}")
        return
    
    logging.info(f"Time to send {batch_type} email stock alerts batch. Marker path: {email_marker_path}")
    
    # Double-check marker file existence immediately before sending
    if os.path.exists(email_marker_path):
        logging.info(f"Marker file found again before sending. Skipping duplicate send. Marker path: {email_marker_path}")
        return
    
    # Get stocks for this batch
    stocks_to_email = get_new_stocks_for_email(today_dir, batch_type)
    
    if not stocks_to_email:
        logging.info(f"No new stocks to send in {batch_type} batch.")
        return
    
    # Create email notification using existing email system
    try:
        # Load config for email
        config_path = os.path.join(project_root, 'config', 'config.json')
        config = {}
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
        
        # Import email function
        from src.mail_utils.send_email import send_email_notification
        
        # Send email with stock cards
        send_email_notification(config, stocks_to_email)
        
        # Update email-notified-stocks.json with all stocks sent so far
        if batch_type == 'morning':
            # For morning batch, save all stocks sent
            save_email_notified_stocks(today_dir, stocks_to_email)
        else:
            # For afternoon batch, add new stocks to existing list
            existing_email_stocks = load_email_notified_stocks(today_dir)
            all_emailed_stocks = existing_email_stocks + stocks_to_email
            save_email_notified_stocks(today_dir, all_emailed_stocks)
        
        # Mark this batch as sent
        with open(email_marker_path, 'w') as f:
            f.write("sent")
        
        logging.info(f"Successfully sent {batch_type} email batch with {len(stocks_to_email)} stocks and marked as sent.")
        
    except Exception as e:
        logging.error(f"Failed to send {batch_type} email stock alerts: {e}")


def process_market_data(market_name, screener_df, llm_client, today_dir):
    """
    Process screener data for a single market (US or China).
    Handles analysis, news collection, and notification preparation.
    
    Args:
        market_name (str): 'us' or 'china'
        screener_df (pd.DataFrame): Normalized screener data
        llm_client (LLMClient): LLM client instance
        today_dir (str): Today's analysis directory
    
    Returns:
        list: Structured notification data for this market
    """
    if screener_df is None or screener_df.empty:
        logging.info(f"No {market_name.upper()} market data to process.")
        return []

    logging.info(f"Processing {market_name.upper()} market: {len(screener_df)} stocks.")
    
    # Ensure 'Ticker' column exists
    if 'Ticker' not in screener_df.columns:
        logging.error(f"{market_name.upper()} screener data missing 'Ticker' column. Skipping.")
        return []

    # 1. Handle analysis file
    market_analysis_dir = os.path.join(today_dir, market_name)
    os.makedirs(market_analysis_dir, exist_ok=True)
    analysis_file_path = os.path.join(market_analysis_dir, "analysis.json")
    
    # 先加载已处理的股票（来自之前的批次），再保存当前批次
    # 避免 save→load 顺序颠倒导致新股票永远为空
    processed_tickers = _load_processed_tickers(analysis_file_path)
    _save_analysis(analysis_file_path, screener_df)

    # 2. Identify new stocks
    current_tickers = set(screener_df['Ticker'])
    new_tickers_list = list(current_tickers - processed_tickers)
    logging.info(f"[{market_name.upper()}] Found {len(new_tickers_list)} new tickers: {new_tickers_list[:10]}...")
    
    if not new_tickers_list:
        return []

    new_stocks_df = screener_df[screener_df['Ticker'].isin(new_tickers_list)].copy()

    # 3. Collect news (market-specific)
    news_results = {}
    if market_name == 'us' and NEWS_COLLECTOR_AVAILABLE:
        try:
            news_collector = NewsCollector()
            news_results = news_collector.collect_news(new_tickers_list)
        except Exception as e:
            logging.error(f"Error collecting US news: {e}")
            news_results = {}
    elif market_name == 'us' and not NEWS_COLLECTOR_AVAILABLE:
        logging.warning("US news collector not available (install alpaca-py to enable).")
    elif market_name == 'china' and CHINA_NEWS_AVAILABLE:
        try:
            china_news = ChinaNewsCollector()
            news_results = china_news.collect_news(new_tickers_list)
        except Exception as e:
            logging.error(f"Error collecting China news: {e}")
            news_results = {}
    else:
        logging.warning(f"No news collector available for {market_name} market.")

    # 4. Prepare notifications
    market_notifications = prepare_notification_content(
        new_stocks_df,
        llm_client,
        news_results if new_tickers_list else {},
        market=market_name
    )

    # Tag each notification with market
    for item in market_notifications:
        item['market'] = market_name

    return market_notifications


def _load_processed_tickers(analysis_file_path):
    """Loads processed tickers from a market-specific analysis JSON file."""
    processed_data = {}
    if os.path.exists(analysis_file_path):
        try:
            with open(analysis_file_path, 'r') as f:
                processed_data = json.load(f)
            logging.info(f"Loaded {len(processed_data)} previously processed tickers from {analysis_file_path}")
        except (json.JSONDecodeError, Exception) as e:
            logging.error(f"Error reading {analysis_file_path}: {e}. Starting fresh.")
            processed_data = {}
    else:
        logging.info(f"Analysis file {analysis_file_path} not found. Starting fresh.")
    return set(processed_data.keys()) if isinstance(processed_data, dict) else set()


def _save_analysis(analysis_file_path, screener_data_df):
    """Saves screener data to analysis JSON file."""
    if screener_data_df.empty or 'Ticker' not in screener_data_df.columns:
        return
        
    processed_data = {}
    if os.path.exists(analysis_file_path):
        try:
            with open(analysis_file_path, 'r') as f:
                processed_data = json.load(f)
        except Exception:
            processed_data = {}

    df_cleaned = screener_data_df.where(pd.notna(screener_data_df), None)
    new_data_list = df_cleaned.to_dict(orient='records')
    new_data_dict = {record['Ticker']: record for record in new_data_list if 'Ticker' in record}
    processed_data.update(new_data_dict)
    processed_data['_last_updated'] = datetime.now().isoformat()
    processed_data_cleaned = clean_value_for_json(processed_data)

    try:
        with open(analysis_file_path, 'w') as f:
            json.dump(processed_data_cleaned, f, indent=4)
        logging.info(f"Saved/Updated to {analysis_file_path}")
    except Exception as e:
        logging.error(f"Error writing to {analysis_file_path}: {e}")


def main():
    """Main execution function — supports dual-market (US + China)."""
    logging.info("--- Starting Trade Alerts Script (Dual-Market) ---")

    # Get today's directory for state files
    pacific_tz = pytz.timezone('America/Los_Angeles')
    now_pacific = datetime.now(pacific_tz)
    today_str = now_pacific.strftime(DATE_FORMAT)
    today_dir = os.path.join(ANALYSIS_BASE_DIR, today_str)
    os.makedirs(today_dir, exist_ok=True)

    # --- Check if any market is open ---
    market_status = is_any_market_open()
    if not any(market_status.values()):
        logging.info("All markets are closed. Ending cycle.")
        return

    # --- Send Market Briefings if applicable ---
    if market_status.get('us'):
        send_market_briefing()
        send_email_stock_alerts()
    
    if market_status.get('china'):
        send_china_market_briefing()

    # --- Initialize LLM Client ---
    try:
        config_path = os.path.join(project_root, 'config', 'config.json')
        llm_client = LLMClient(config_path=config_path)
        if not llm_client.model or not llm_client.prompt_template:
            logging.warning("LLMClient initialized but model or prompt may be missing.")
    except Exception as e:
        logging.error(f"Failed to initialize LLMClient: {e}. LLM analysis will be skipped.", exc_info=True)
        llm_client = None

    # --- Fetch data for ALL enabled markets ---
    logging.info("Fetching screener data for all enabled markets...")
    try:
        all_data = get_all_screener_data()
    except Exception as e:
        logging.error(f"Error fetching screener data: {e}")
        return

    us_data = all_data.get('us', pd.DataFrame())
    china_data = all_data.get('china', pd.DataFrame())

    total_stocks = len(us_data) + len(china_data)
    logging.info(f"Total stocks from all markets: {total_stocks} (US: {len(us_data)}, China: {len(china_data)})")

    if total_stocks == 0:
        logging.warning("No data received from any screener. Exiting.")
        return

    # --- Process each market ---
    all_notifications = []

    # Process US market if open
    if market_status.get('us') and not us_data.empty:
        logging.info("=== Processing US market ===")
        us_notifications = process_market_data('us', us_data, llm_client, today_dir)
        all_notifications.extend(us_notifications)
    else:
        logging.info(f"Skipping US market processing (open={market_status.get('us')}, data={len(us_data)}).")

    # Process China market if open
    if market_status.get('china') and not china_data.empty:
        logging.info("=== Processing China market ===")
        china_notifications = process_market_data('china', china_data, llm_client, today_dir)
        all_notifications.extend(china_notifications)
    else:
        logging.info(f"Skipping China market processing (open={market_status.get('china')}, data={len(china_data)}).")

    # --- Send combined notifications ---
    if all_notifications:
        logging.info(f"Sending {len(all_notifications)} notifications across all markets.")
        
        # Save to discord-notified-stocks.json
        save_discord_notified_stocks(today_dir, all_notifications)
        
        # Send Discord notifications
        update_notify_json(all_notifications)
        send_notifications()
    else:
        logging.info("No new stocks found for notification in this cycle. Will try again in 15 min.")
        update_notify_json([])

    logging.info("--- Trade Alerts Cycle Finished ---")


if __name__ == "__main__":
    # 支持 --once 参数：GitHub Actions 中单次运行
    if '--once' in sys.argv:
        logging.info("Running in single-cycle mode (--once)")
        try:
            main()
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
        sys.exit(0)

    # 默认：无限循环模式（本地服务器用）
    while True:
        try:
            main()
        except Exception as e:
            logging.error(f"An unexpected error occurred in the main loop: {e}")
            logging.error("Restarting loop after a short delay...")
            time.sleep(60)
        
        logging.info("Waiting 15 minutes for the next cycle...")
        time.sleep(900)
