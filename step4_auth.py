import os
import requests
from dotenv import load_dotenv

load_dotenv()

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_GB")

def get_access_token() -> str:
    url = "https://api.ebay.com/identity/v1/oauth2/token"

    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(
        url,
        data=data,
        auth=(EBAY_CLIENT_ID, EBAY_CLIENT_SECRET),
        headers=headers,
        timeout=30
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

if __name__ == "__main__":
    token = get_access_token()
    print("Access Token (ilk 100 karakter):", token[:100])
