"""
gauth.py -- Shared Google OAuth credential loader.
Works locally (reads token.json/credentials.json from project root)
and in Modal (reads from GOOGLE_TOKEN_JSON / GOOGLE_CREDENTIALS_JSON env vars).
"""

import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_creds():
    """Return valid Google credentials. Modal-aware: reads from env vars if present."""
    token_json_env = os.environ.get("GOOGLE_TOKEN_JSON")
    creds_json_env = os.environ.get("GOOGLE_CREDENTIALS_JSON")

    if token_json_env and creds_json_env:
        # Running in Modal -- write env var contents to /tmp
        token_path = "/tmp/token.json"
        creds_path = "/tmp/credentials.json"
        with open(token_path, "w") as f:
            f.write(token_json_env)
        with open(creds_path, "w") as f:
            f.write(creds_json_env)
    else:
        # Running locally
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        token_path = os.path.join(base_dir, "token.json")
        creds_path = os.path.join(base_dir, "credentials.json")

    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Interactive OAuth -- only works locally, not in Modal
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds