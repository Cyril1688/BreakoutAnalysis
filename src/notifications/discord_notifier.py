"""
Discord notifier script.

This script reads messages from notify.txt and sends them to Discord via webhook.
"""

import os
import json
import requests
from datetime import datetime, timezone
import textwrap # Import textwrap

# Discord API limits
DISCORD_MAX_MESSAGE_LENGTH = 2000
DISCORD_MAX_EMBED_FIELD_VALUE_LENGTH = 1024

def _chunk_text(text, max_len):
    """
    Splits a long text into chunks, ensuring each chunk is within max_len.
    Attempts to break at word boundaries or newlines.
    """
    if not text:
        return []

    chunks = []
    current_pos = 0
    total_length = len(text)

    while current_pos < total_length:
        # Determine the end position for the current chunk
        end_pos = min(current_pos + max_len, total_length)
        
        # Get the potential chunk content
        chunk_content = text[current_pos:end_pos]

        # If this is not the last chunk and the cut is in the middle of a word,
        # try to find a natural break point (space or newline) backwards.
        # Also check if the character at end_pos is not a space, meaning we might be in a word.
        if end_pos < total_length and not text[end_pos-1].isspace() and not text[end_pos].isspace():
            break_point = -1
            # Search backwards from end_pos - 1 to current_pos
            for i in range(end_pos - 1, current_pos - 1, -1):
                if text[i].isspace():
                    break_point = i + 1 # Include the space/newline in the chunk
                    break
            
            if break_point > current_pos: # Found a suitable break point
                chunk_content = text[current_pos:break_point]
                current_pos = break_point
            else: # No natural break found, just cut at max_len
                current_pos = end_pos
        else: # Last chunk or already at a natural break
            current_pos = end_pos
        
        chunks.append(chunk_content.strip()) # Strip leading/trailing whitespace from chunk
    
    return chunks


def load_config(config_path='config/config.json'):
    """Load configuration from JSON file."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        discord_config = config.get('discord', {})
        webhook_url = discord_config.get('webhook_url', '')
        report_webhook_url = discord_config.get('webhook_url_market_report', '')
        
        if not webhook_url or webhook_url == "YOUR_WEBHOOK_URL":
            print("Warning: Discord webhook URL not configured or is set to default value")
            print("Please update the webhook_url in config/config.json")
        if not report_webhook_url or report_webhook_url == "YOUR_WEBHOOK_URL":
            print("Warning: Discord market report webhook URL not configured or is set to default value")
            print("Please update the webhook_url_market_report in config/config.json")
        
        if not webhook_url or not report_webhook_url:
            return None
        
        return discord_config
    except Exception as e:
        print(f"Error loading Discord configuration: {str(e)}")
        return None

def read_notify_json(file_path=None):
    """Read the structured notification data from the notify.json file."""
    if file_path is None:
        # Default to notify.json in the notifications directory
        file_path = os.path.join(os.path.dirname(__file__), 'notify.json')
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        if not isinstance(data, list) or not data:
            print("Notify JSON is empty or not a list. Nothing to send.")
            return None
            
        print(f"Read {len(data)} stock notifications from {file_path}")
        return data # Returns a list of dictionaries
    except FileNotFoundError:
         print(f"Notify file not found: {file_path}. Nothing to send.")
         return None
    except json.JSONDecodeError:
         print(f"Error decoding JSON from {file_path}. Cannot send notifications.")
         return None
    except Exception as e:
        print(f"Error reading notify JSON file: {str(e)}")
        return None

def send_stock_embed(webhook_url, stock_data):
    """Sends a single stock's data as a formatted embed, optionally with an image."""
    
    # Handle market briefing notification
    if 'title' in stock_data and 'content' in stock_data and 'ticker' not in stock_data:
        print(f"Sending market briefing message")
        # Ensure content is not empty and is a string
        content = stock_data.get('content', '')
        if not isinstance(content, str):
            content = str(content) # Convert to string if not already

        # Prepare the title for the market briefing
        title_prefix = f"**{stock_data.get('title', 'Market Briefing')}**\n"
        
        # Reserve space for the part indicator suffix, e.g., " (Part 1/10)"
        # Max 3 digits for part numbers, so 15 chars for suffix.
        suffix_reserve = 15 

        # Manually chunk to handle different max_len for first chunk
        raw_content_chunks = []
        current_pos = 0
        total_content_length = len(content)

        # First chunk
        if total_content_length > 0:
            # Calculate max content length for the first chunk
            first_chunk_max_len = DISCORD_MAX_MESSAGE_LENGTH - len(title_prefix) - suffix_reserve
            
            first_chunk_end_pos = min(current_pos + first_chunk_max_len, total_content_length)
            first_chunk_content = content[current_pos:first_chunk_end_pos]
            
            # Try to find a natural break point for the first chunk
            if first_chunk_end_pos < total_content_length and not content[first_chunk_end_pos-1].isspace() and not content[first_chunk_end_pos].isspace():
                break_point = -1
                for i in range(first_chunk_end_pos - 1, current_pos - 1, -1):
                    if content[i].isspace():
                        break_point = i + 1
                        break
                if break_point > current_pos:
                    first_chunk_content = content[current_pos:break_point]
                    current_pos = break_point
                else:
                    current_pos = first_chunk_end_pos
            else:
                current_pos = first_chunk_end_pos
            raw_content_chunks.append(first_chunk_content.strip())

        # Subsequent chunks
        # Calculate max content length for subsequent chunks
        other_chunks_max_len = DISCORD_MAX_MESSAGE_LENGTH - suffix_reserve
        while current_pos < total_content_length:
            chunk_end_pos = min(current_pos + other_chunks_max_len, total_content_length)
            chunk_content = content[current_pos:chunk_end_pos]

            if chunk_end_pos < total_content_length and not content[chunk_end_pos-1].isspace() and not content[chunk_end_pos].isspace():
                break_point = -1
                for i in range(chunk_end_pos - 1, current_pos - 1, -1):
                    if content[i].isspace():
                        break_point = i + 1
                        break
                if break_point > current_pos:
                    chunk_content = content[current_pos:break_point]
                    current_pos = break_point
                else:
                    current_pos = chunk_end_pos
            else:
                current_pos = chunk_end_pos
            raw_content_chunks.append(chunk_content.strip())

        if not raw_content_chunks:
            print("No content to send for market briefing.")
            return False

        all_chunks_sent = True
        total_chunks = len(raw_content_chunks)
        for i, chunk_content in enumerate(raw_content_chunks):
            message_content = ""
            if i == 0:
                message_content = f"{title_prefix}{chunk_content}"
            else:
                message_content = chunk_content
            
            # Add part indicator if there's more than one chunk
            if total_chunks > 1:
                message_content += f" (Part {i+1}/{total_chunks})"
            
            # Final check to ensure length is not exceeded due to suffix
            if len(message_content) > DISCORD_MAX_MESSAGE_LENGTH:
                # This should ideally not happen if max_len calculations are correct
                message_content = message_content[:DISCORD_MAX_MESSAGE_LENGTH - 3] + "..." 

            payload = {"content": message_content}
            try:
                response = requests.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                print(f"Market briefing chunk {i+1}/{total_chunks} sent successfully!")
            except requests.exceptions.HTTPError as e:
                print(f"Error sending market briefing chunk {i+1}/{total_chunks}: {e}")
                if e.response is not None:
                    print(f"Discord API Response: {e.response.text}")
                all_chunks_sent = False
            except Exception as e:
                print(f"An unexpected error occurred while sending market briefing chunk {i+1}/{total_chunks}: {e}")
                all_chunks_sent = False
        return all_chunks_sent

    # Basic check for essential data
    if not stock_data or 'ticker' not in stock_data:
        print("Warning: Invalid stock_data received, skipping.")
        return False

    ticker = stock_data.get('ticker', 'N/A')
    company_name = stock_data.get('company_name', 'N/A')
    market = stock_data.get('market', 'us')  # 'us' or 'china'
    image_path = stock_data.get('chart_image_path')
    
    # Add market badge to title
    market_badge = "🇨🇳 A股" if market == 'china' else "🇺🇸 US"

    # Prepare fields - max 25 fields per embed
    fields = []
    embed_description = "" # Default empty description

    # --- Always Add Default Fields ---
    print(f"Preparing default fields for {ticker}")

    # Helper to add chunked fields
    def add_chunked_field(field_name_base, content_str, is_inline):
        if content_str and content_str != "N/A":
            # Reserve space for the part indicator suffix, e.g., " (Part 1/10)"
            suffix_reserve = 15 
            # Calculate max content length for chunks
            chunk_max_len = DISCORD_MAX_EMBED_FIELD_VALUE_LENGTH - suffix_reserve

            content_chunks = _chunk_text(content_str, chunk_max_len)
            total_chunks = len(content_chunks)
            for i, chunk in enumerate(content_chunks):
                field_name = field_name_base
                if total_chunks > 1:
                    field_name = f"{field_name_base} (Part {i+1}/{total_chunks})"
                fields.append({"name": field_name, "value": chunk, "inline": is_inline})

    add_chunked_field("📊 Core Data", stock_data.get('core_data_str'), True)
    add_chunked_field("📈 Technicals", stock_data.get('technicals_str'), True)

    # Add News field if available - ONLY if LLM analysis is NOT valid
    llm_analysis_str = stock_data.get('llm_analysis_str') # Get LLM analysis string first
    llm_analysis_valid = (
        llm_analysis_str and
        llm_analysis_str != "LLM analysis skipped (client not available)." and
        not llm_analysis_str.startswith("Error during LLM analysis") and
        llm_analysis_str != "LLM analysis not available or invalid."
    )

    if not llm_analysis_valid: # If LLM is NOT valid, add the default news field
        news_str = stock_data.get('news_str')
        if news_str and news_str != "No recent news found.":
             print(f"Adding default News field for {ticker} (LLM analysis invalid/missing)")
             add_chunked_field("📰 Recent News", news_str, False)
        else:
             print(f"No default news found for {ticker}")

    # --- Add LLM Analysis Field (If Valid) ---
    if llm_analysis_valid:
        print(f"Adding LLM analysis field for {ticker}")
        add_chunked_field("🤖 AI Insights", llm_analysis_str, False)
    elif llm_analysis_str: # Log if analysis exists but is invalid/skipped
         print(f"LLM analysis for {ticker} exists but is invalid/skipped: '{llm_analysis_str}'")
    else:
        print(f"No LLM analysis available for {ticker}")


    # Choose embed color based on market
    # US: Blue, China: Red (red = 上涨 in Chinese market convention)
    embed_color = 0xE53935 if market == 'china' else 0x5865F2

    # Construct the embed
    embed = {
        "title": f"{market_badge} {ticker} - {company_name}",
        "description": embed_description,
        "color": embed_color,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    files = None
    # if image_path and os.path.exists(image_path):
    #     file_name = os.path.basename(image_path)
    #     embed['image'] = {'url': f'attachment://{file_name}'}
    #     files = {'file': (file_name, open(image_path, 'rb'), 'image/png')}

    payload = {"embeds": [embed]}
    
    try:
        if files:
            response = requests.post(webhook_url, files=files, data={'payload_json': json.dumps(payload)}, timeout=10)
        else:
            response = requests.post(webhook_url, json=payload, timeout=10)
            
        response.raise_for_status()
        print(f"Embed for {ticker} sent successfully!")
        return True
    except Exception as e:
        print(f"Error sending embed for {ticker}: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
             try:
                 print(f"Discord API Response: {e.response.json()}")
             except json.JSONDecodeError:
                 print(f"Discord API Response Text: {e.response.text}")
        return False
    finally:
        if files:
            files['file'][1].close()

def clear_notify_json(file_path=None):
    """Clear the notify.json file by writing an empty list."""
    if file_path is None:
        # Default to notify.json in the notifications directory
        file_path = os.path.join(os.path.dirname(__file__), 'notify.json')
    try:
        with open(file_path, 'w') as f:
            json.dump([], f) # Write empty list to clear
        print(f"Cleared notification file: {file_path}")
        return True
    except Exception as e:
        print(f"Error clearing notify json file: {str(e)}")
        return False

def send_discord_notification(discord_config, stock_notifications):
    """Sends a list of stock notifications to Discord."""
    if not stock_notifications:
        print("No notifications to send.")
        return True

    all_sent_successfully = True
    for stock_data in stock_notifications:
        # Choose appropriate webhook based on notification type
        if 'title' in stock_data and 'content' in stock_data and 'ticker' not in stock_data:
            # Market briefing
            webhook_url = discord_config.get('webhook_url_market_report')
        else:
            webhook_url = discord_config.get('webhook_url')
        success = send_stock_embed(webhook_url, stock_data)
        if not success:
            all_sent_successfully = False
    return all_sent_successfully

def main():
    """Main function to read notify.json and send embeds to Discord."""
    print("Discord Notifier - Starting...")
    
    # Get the path to the notify.json file
    notify_file_path = os.path.join(os.path.dirname(__file__), 'notify.json')
    
    # Load webhook URL from config
    discord_config = load_config()
    if not discord_config:
        return
    
    # Read structured data from notify.json
    stock_notifications = read_notify_json(notify_file_path)
    if not stock_notifications:
        return
    
    all_sent_successfully = send_discord_notification(discord_config, stock_notifications)
            
    # Clear notify.json only if all messages were sent successfully
    if all_sent_successfully:
        print("All notifications sent successfully. Clearing notify file.")
        clear_notify_json(notify_file_path)
    else:
         print("Some notifications failed to send. Notify file will not be cleared.")

if __name__ == "__main__":
    main()
