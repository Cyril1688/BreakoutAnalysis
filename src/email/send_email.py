import os.path
import json
import os.path
import json
import base64
import logging
from email.message import EmailMessage
from datetime import datetime
import argparse # Added for command-line arguments

# Google API Libraries (ensure installed via requirements.txt)
import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd # For formatting DataFrame as HTML

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - EMAIL - %(levelname)s - %(message)s')

# --- Constants ---
# If modifying these scopes, delete the file token.json.
# Simplified scopes as profile fetch is removed
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly", # Needed for contacts
    "https://www.googleapis.com/auth/gmail.send" # Needed to send email
]
# TOKEN_PATH = 'token.json' # Stores user's access and refresh tokens. - Path now comes from config
# CREDENTIALS_PATH = 'credentials.json' # Downloaded from Google Cloud Console. - Path now comes from config

def get_google_credentials(config):
    """
    Gets valid Google API credentials, handling the OAuth flow if needed.
    Reads credential/token paths from the config.
    """
    creds = None
    email_config = config.get('email', {})
    token_path = email_config.get('token_path', 'token.json') # Default if not in config
    credentials_path = email_config.get('credentials_path', 'credentials.json') # Default if not in config

    # The token file stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first time.
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
            logging.info(f"Credentials loaded from {token_path}.")
        except Exception as e:
            logging.warning(f"Could not load credentials from {token_path}: {e}. Will attempt re-authentication.")
            creds = None # Force re-authentication

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                logging.info("Credentials expired, refreshing...")
                creds.refresh(Request())
                logging.info("Credentials refreshed successfully.")
            except Exception as e:
                logging.error(f"Failed to refresh credentials: {e}. Need to re-authenticate.")
                creds = None # Force re-authentication
        else:
            logging.info("No valid credentials found, starting OAuth flow...")
            if not os.path.exists(credentials_path):
                logging.error(f"'{credentials_path}' not found. Please download it from Google Cloud Console and place it in the project root.")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                # Note: This step requires user interaction in a browser.
                # The AI cannot complete this step. Run the script manually once.
                try:
                    creds = flow.run_local_server(port=0) # This will open a browser tab for authorization
                    logging.info("OAuth flow completed successfully.")
                except ValueError as ve:
                    # Check if it's the scope mismatch error
                    if "Scope has changed" in str(ve):
                        logging.warning(f"Caught scope mismatch error during/after flow: {ve}")
                        logging.info("Attempting to load token file anyway, as it might have been created before the error.")
                        # Try loading from the token file immediately
                        if os.path.exists(token_path):
                            try:
                                creds = Credentials.from_authorized_user_file(token_path, SCOPES)
                                logging.info(f"Successfully loaded credentials from {token_path} despite scope mismatch error during flow.")
                                # Verify essential scopes are present
                                essential_scopes_present = all(scope in creds.scopes for scope in [
                                    "https://www.googleapis.com/auth/gmail.send",
                                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                                    "https://www.googleapis.com/auth/userinfo.email"
                                ])
                                if not essential_scopes_present:
                                     logging.error("Essential scopes missing even after loading token post-error.")
                                     return None
                            except Exception as load_err:
                                 logging.error(f"Failed to load token file {token_path} after scope mismatch error: {load_err}")
                                 return None
                        else:
                             logging.error(f"Scope mismatch error occurred, and token file {token_path} was not found/created.")
                             return None
                    else:
                         # Re-raise other ValueErrors
                         logging.error(f"OAuth flow failed with unexpected ValueError: {ve}")
                         raise ve # Re-raise
                except Exception as e:
                     logging.error(f"Failed to complete OAuth flow: {e}")
                     return None

                # Original check (might be redundant now but keep for safety)
                if creds and not all(scope in creds.scopes for scope in SCOPES):
                     logging.warning("OAuth flow completed, but scopes in token differ slightly from requested scopes (Google might add defaults like openid/email).")
                     # Verify essential scopes are present before proceeding (already done above if mismatch error occurred)
                     essential_scopes_present = all(scope in creds.scopes for scope in [
                         "https://www.googleapis.com/auth/gmail.send",
                         "https://www.googleapis.com/auth/spreadsheets.readonly",
                         "https://www.googleapis.com/auth/userinfo.email"
                     ])
                     if essential_scopes_present:
                         logging.info("Essential scopes are present in the obtained credentials. Proceeding.")
                     else:
                         logging.error("Essential scopes missing from obtained credentials despite successful flow. Cannot proceed.")
                         return None # Stop if essential scopes are missing
                elif creds:
                     logging.info("OAuth flow completed successfully with matching scopes.")
                else:
                     # This case shouldn't happen if run_local_server succeeded without error, but handle defensively
                     logging.error("OAuth flow did not return credentials.")
                     return None
            except Exception as e:
                 # Check if it's the scope mismatch error AFTER the flow likely succeeded
                 if "Scope has changed" in str(e):
                     logging.warning(f"Caught scope mismatch error after flow: {e}")
                     # Check if creds object was actually created before the error was raised
                     if creds and hasattr(creds, 'scopes') and all(scope in creds.scopes for scope in [
                         "https://www.googleapis.com/auth/gmail.send",
                         "https://www.googleapis.com/auth/spreadsheets.readonly",
                         "https://www.googleapis.com/auth/userinfo.email"
                     ]):
                         logging.info("Essential scopes seem present despite mismatch error. Attempting to proceed with obtained credentials.")
                         # Proceed to save the token below
                     else:
                         logging.error("Scope mismatch error occurred, and essential scopes might be missing or creds object is invalid.")
                         return None # Cannot proceed
                 else:
                    # Handle other exceptions during the flow
                    logging.error(f"Failed to complete OAuth flow: {e}")
                    return None
        # Save the credentials for the next run ONLY if creds object is valid
        if creds and hasattr(creds, 'token'):
            # Ensure token_path is defined (it should be from the start of the function)
            token_path = email_config.get('token_path', 'token.json')
            credentials_path = email_config.get('credentials_path', 'credentials.json')
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
            token_path_abs = os.path.join(project_root, token_path)
            try:
                with open(token_path, 'w') as token_file:
                    token_file.write(creds.to_json())
                logging.info(f"Credentials saved to {token_path}.")
            except Exception as e:
                logging.error(f"Failed to save credentials to {token_path}: {e}")

    return creds

def get_contacts_from_sheet(config, credentials):
    """
    Fetches contacts from the Google Sheet, filtering for those who opted in.
    Assumes 'Email' is in column D and 'SendEmail' is in column E.
    """
    contacts = []
    sheet_url = config.get('contacts_sheet_url')
    if not sheet_url:
        logging.warning("Google Sheet URL ('contacts_sheet_url') not found in config.")
        return contacts

    try:
        logging.info(f"Accessing Google Sheet: {sheet_url}")
        gc = gspread.authorize(credentials)
        workbook = gc.open_by_url(sheet_url)
        sheet = workbook.worksheet("MainSheet")
        logging.info("Accessed 'MainSheet' tab.")

        # Get all records from the sheet as a list of dictionaries
        records = sheet.get_all_records()
        
        # Filter records where 'SendEmail' is 'Yes'
        opted_in_records = [
            record for record in records 
            if str(record.get('SendEmail', '')).strip().lower() == 'yes'
        ]

        # Extract email addresses from the filtered records
        contacts = [
            record['Email'].strip() for record in opted_in_records 
            if 'Email' in record and record['Email'] and '@' in record['Email']
        ]
        
        logging.info(f"Found {len(opted_in_records)} users who opted-in. Fetched {len(contacts)} valid contacts.")

    except gspread.exceptions.WorksheetNotFound:
        logging.error("Worksheet 'MainSheet' not found. Please ensure it exists.")
    except gspread.exceptions.APIError as e:
        logging.error(f"Google Sheets API error: {e}. Check URL, permissions, and API status.")
    except Exception as e:
        logging.error(f"Failed to fetch contacts from Google Sheet: {e}", exc_info=True)

    return contacts

import markdown2

def markdown_to_html(text):
    """Converts markdown to HTML using the markdown2 library."""
    if not isinstance(text, str):
        return ""
    return markdown2.markdown(text, extras=["fenced-code-blocks", "tables"])

def create_html_email_body(notification_list):
    """Creates a single, well-formatted HTML email body for a list of notifications."""
    
    styles = """
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            margin: 0;
            padding: 0;
            background-color: #f8f9fa; /* Light gray background */
            color: #343a40; /* Dark gray text */
            line-height: 1.6;
        }
        .main-container {
            max-width: 700px;
            margin: 20px auto;
            padding: 30px;
            background-color: #ffffff; /* White content background */
            border-radius: 12px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.08);
        }
        h1 {
            text-align: center;
            color: #212529; /* Darker heading */
            font-size: 2.2em;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e9ecef; /* Lighter border */
        }
        h2 {
            color: #007bff; /* Primary blue for sections */
            font-size: 1.6em;
            margin-top: 35px;
            margin-bottom: 15px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e9ecef;
        }
        h3 {
            color: #495057; /* Slightly lighter heading */
            font-size: 1.2em;
            margin-top: 25px;
            margin-bottom: 10px;
        }
        .date {
            text-align: center;
            margin-bottom: 30px;
            font-style: italic;
            color: #6c757d; /* Muted date color */
            font-size: 0.95em;
        }
        /* Market Briefing Styles */
        .market-briefing-container {
            background-color: #e0f7fa; /* Light cyan */
            border-left: 5px solid #00bcd4; /* Cyan accent */
            padding: 25px;
            margin-bottom: 30px;
            border-radius: 8px;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            font-weight: 500;
            font-size: 1.1em;
            line-height: 1.8;
        }
        .market-briefing-container h2 {
            margin-top: 0;
            color: #007bff; /* Consistent blue */
            border-bottom: none;
            padding-bottom: 0;
            font-weight: 700;
            font-size: 1.8em;
        }
        .market-briefing-container p {
            line-height: 1.8;
            font-size: 1.1em;
            margin-bottom: 1em; /* Add margin for paragraph spacing */
        }
        .market-briefing-container p:last-child {
            margin-bottom: 0;
        }
        .market-briefing-container p:last-child {
            margin-bottom: 0;
        }
        /* Stock Card Styles */
        .stock-card {
            border: 1px solid #dee2e6; /* Light gray border */
            border-radius: 10px;
            margin-bottom: 30px;
            padding: 25px;
            background-color: #ffffff;
            transition: all 0.3s ease;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
        }
        .stock-card:hover {
            box-shadow: 0 6px 20px rgba(0,0,0,0.12);
            transform: translateY(-3px);
        }
        .stock-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 1px solid #e9ecef;
        }
        .stock-header h3 {
            margin: 0;
            color: #212529;
            font-size: 1.6em;
            font-weight: 600;
        }
        .stock-header .ticker {
            font-weight: bold;
            font-size: 1.8em;
            color: #007bff;
            background-color: #e9f5ff;
            padding: 5px 12px;
            border-radius: 5px;
        }
        .data-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        .data-section {
            padding: 15px;
            border-radius: 8px;
            background-color: #f1f3f5; /* Lighter gray for data sections */
            border: 1px solid #e9ecef;
        }
        .section-title {
            font-weight: 600;
            color: #495057;
            margin-bottom: 10px;
            font-size: 1.15em;
        }
        .analysis-section .section-title {
            margin-top: 20px;
        }
        .analysis-content {
            white-space: pre-wrap;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace; /* Monospace for code/analysis */
            background-color: #fdfdfe;
            border: 1px solid #ced4da;
            padding: 18px;
            border-radius: 8px;
            margin-top: 12px;
            font-size: 0.95em;
            line-height: 1.5;
        }
        .disclaimer {
            margin-top: 50px;
            padding-top: 20px;
            border-top: 1px solid #e9ecef;
            font-size: 0.85em;
            color: #6c757d;
            text-align: center;
        }
        .discord-invite {
            margin-top: 35px;
            padding: 25px;
            border-top: 1px solid #e9ecef;
            text-align: center;
            background-color: #f0f8ff; /* Very light blue */
            border-radius: 10px;
            border: 1px solid #cfe2ff;
        }
        .discord-invite p {
            margin-bottom: 15px;
            font-size: 1.05em;
            color: #343a40;
        }
        .discord-invite p:last-child {
            margin-bottom: 0;
        }
        .discord-invite strong {
            font-size: 1.15em;
            color: #212529;
        }
        .discord-invite a {
            font-size: 1.3em;
            color: #7289da; /* Discord brand color */
            text-decoration: none;
            font-weight: bold;
            transition: color 0.2s ease;
        }
        .discord-invite a:hover {
            color: #5b6eae;
        }
        .discord-invite .small-text {
            font-size: 0.9em;
            color: #7f8c8d;
        }
        .unsubscribe-info {
            margin-top: 20px;
            font-size: 0.8em;
            color: #7f8c8d;
            text-align: center;
        }
    </style>
    """
    
    html_content = f"<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'><title>Trading Report</title>{styles}</head><body><div class='main-container'>"
    
    # Add main title and date
    title = "Daily Trading Report"
    if len(notification_list) == 1 and 'content' in notification_list[0]:
        title = notification_list[0].get('title', title)
    
    html_content += f"<h1>{title}</h1><p class='date'>{datetime.now().strftime('%B %d, %Y')}</p>"

    # Process each notification
    for item in notification_list:
        if 'content' in item: # This is a market briefing
            html_content += f"""
            <div class="market-briefing-container">
                <h2>Market Overview</h2>
                <p>{markdown_to_html(item.get('content', 'N/A'))}</p>
            </div>
            """
        elif 'ticker' in item: # This is a stock alert
            ticker = item.get('ticker', 'N/A')
            company_name = item.get('company_name', 'N/A')
            
            html_content += f"""
            <div class="stock-card">
                <div class="stock-header">
                    <h3>{company_name}</h3>
                    <span class="ticker">{ticker}</span>
                </div>
                <div class="data-grid">
                    <div class="data-section">
                        <div class="section-title">📊 Core Data</div>
                        {markdown_to_html(item.get('core_data_str', 'N/A'))}
                    </div>
                    <div class="data-section">
                        <div class="section-title">📈 Technicals</div>
                        {markdown_to_html(item.get('technicals_str', 'N/A'))}
                    </div>
                </div>
                <div class="analysis-section">
                    <div class="section-title">🤖 AI Insights</div>
                    <div class="analysis-content">{markdown_to_html(item.get('llm_analysis_str', 'N/A'))}</div>
                </div>
            </div>
            """

    # Add disclaimer and close tags
    html_content += """
        <div class="disclaimer">
            <p>This report is for informational purposes only and does not constitute investment advice. Trading stocks involves risk. Always perform your own due diligence.</p>
        </div>
        <div class="discord-invite">
            <p><strong>Want more real-time updates, custom recommendations, and knowledge on how to use these alerts effectively?</strong></p>
            <p><a href="https://discord.com/invite/4KCanDzc3m">Join our Discord Channel!</a></p>
        </div>
        <div class="unsubscribe-info">
            <p>To stop receiving these reports, please reply to this email with "Unsubscribe"</p>
        </div>
    </div></body></html>
    """
    
    return html_content

def create_message(sender, to_list, bcc_list, subject, message_html): # Added bcc_list parameter
    """Creates an EmailMessage object ready for the Gmail API."""
    message = EmailMessage()
    message.set_content("Please view this email in an HTML-compatible client.") # Fallback for non-HTML clients
    message.add_alternative(message_html, subtype='html')
    # Set 'To' to sender (or a fixed address) as recipients are in BCC
    message['To'] = sender
    message['From'] = sender
    message['Subject'] = subject
    if bcc_list: # Add BCC header only if there are contacts
        message['Bcc'] = ", ".join(bcc_list)

    # Encode message to base64url format
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': encoded_message}

def send_gmail(credentials, message_body):
    """Sends an email using the Gmail API."""
    try:
        service = build('gmail', 'v1', credentials=credentials)
        # Use 'me' to refer to the authenticated user's email address
        sent_message = service.users().messages().send(userId='me', body=message_body).execute()
        logging.info(f"Message Id: {sent_message['id']} sent successfully.")
        return True
    except HttpError as error:
        logging.error(f'An HTTP error occurred while sending email: {error}')
        return False
    except Exception as e:
        logging.error(f'An unexpected error occurred while sending email: {e}')
        return False

def send_email_notification(config, notification_list):
    """
    Orchestrates sending a single email for a list of notifications.
    """
    email_config = config.get('email', {})
    if not email_config.get('email_report', False):
        logging.info("Email reporting is disabled in the configuration.")
        return

    if not notification_list:
        logging.info("Notification list is empty. Nothing to email.")
        return

    logging.info("Starting combined email notification process...")
    credentials = get_google_credentials(config)
    if not credentials:
        logging.error("Failed to get Google credentials. Cannot send email.")
        return

    contacts = get_contacts_from_sheet(email_config, credentials)
    if not contacts:
        logging.warning("No contacts found or fetched. Cannot send email.")
        return

    sender_email = "celesthioailabs@gmail.com"
    
    # Determine subject based on content
    # If there's only one item and it's a market briefing
    if len(notification_list) == 1 and 'content' in notification_list[0]:
        subject = notification_list[0].get('title', f"Market Update - {datetime.now().strftime('%Y-%m-%d')}")
    else:
        tickers = [item.get('ticker', 'N/A') for item in notification_list if 'ticker' in item]
        subject = f"Stock Alerts ({len(tickers)}): {', '.join(tickers)}"

    html_content = create_html_email_body(notification_list)

    logging.info(f"Preparing single combined email with BCC to {len(contacts)} contacts.")
    message_body = create_message(sender_email, sender_email, contacts, subject, html_content)
    
    send_gmail(credentials, message_body)

    logging.info("Combined email notification process finished.")


def main():
    """Main function to handle command-line execution for sending notifications."""
    parser = argparse.ArgumentParser(description='Send Trading Report Email via Gmail API.')
    parser.add_argument('--notify-json', default='src/notifications/email_notify.json', help='Path to the email_notify.json file.')
    parser.add_argument('--config', default='config/config.json', help='Path to the configuration file.')
    args = parser.parse_args()

    logging.info(f"--- Running Email Sender for file: {args.notify_json} ---")

    # Load config
    config = {}
    if os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)
    else:
        logging.error(f"Config file not found at {args.config}.")
        return

    # Read notification data from json
    notification_data_list = []
    try:
        with open(args.notify_json, 'r', encoding='utf-8') as f:
            notification_data_list = json.load(f)
        logging.info(f"Successfully read {len(notification_data_list)} notifications from {args.notify_json}")
    except FileNotFoundError:
         logging.error(f"Notify JSON file not found: {args.notify_json}")
         return
    except Exception as e:
         logging.error(f"Error reading notify JSON file {args.notify_json}: {e}")
         return

    if not notification_data_list:
         logging.info("Notification data is empty. Nothing to send.")
         return

    # Send one combined email for all notifications
    send_email_notification(config, notification_data_list)

    logging.info("--- Email Sender Finished ---")


if __name__ == "__main__":
    # This allows the script to be called from the command line to send emails
    # based on the content of notify.json, similar to how discord_notifier.py works.
    main()
