"""
setup_google_auth.py -- One-time Google OAuth setup.
Run this locally to generate token.json before deploying to Modal.

Usage: python execution/setup_google_auth.py
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]

def setup():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    token_path = os.path.join(base_dir, "token.json")
    creds_path = os.path.join(base_dir, "credentials.json")

    if not os.path.exists(creds_path):
        print(f"ERROR: credentials.json not found at {creds_path}")
        print("Download it from Google Cloud Console > APIs & Services > Credentials > OAuth 2.0 Client IDs")
        return

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print(f"token.json saved to {token_path}")
    else:
        print("Credentials already valid. token.json is up to date.")

if __name__ == "__main__":
    setup()
