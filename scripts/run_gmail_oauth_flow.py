import os
import sys
import json
import logging
from google_auth_oauthlib.flow import InstalledAppFlow

logging.basicConfig(level=logging.INFO, format='%(asctime)s - GMAIL_OAUTH - %(levelname)s - %(message)s')

# --- Add project root to sys.path ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# --- End of path addition ---

def run_oauth_flow():
    # Load config file
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../config/config.json'))
    if not os.path.exists(config_path):
        logging.error(f"Config file not found at {config_path}")
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = json.load(f)

    email_config = config.get('email', {})
    credentials_path = email_config.get('credentials_path', 'credentials.json')
    token_path = email_config.get('token_path', 'token.json')

    if not os.path.exists(credentials_path):
        logging.error(f"Credentials file '{credentials_path}' not found. Please download it from Google Cloud Console and place it in the project root.")
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/gmail.send"
    ]

    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save the credentials for the next run
    with open(token_path, 'w') as token_file:
        token_file.write(creds.to_json())
    logging.info(f"OAuth flow completed successfully. Credentials saved to {token_path}.")

if __name__ == "__main__":
    run_oauth_flow()
