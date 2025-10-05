    # Define the consent URL
from pickle import GET
import webbrowser
import requests
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
import os
from base64 import b64encode
from urllib.parse import urlparse, parse_qs

load_dotenv()

#PRODUCTION_TOKEN = os.environ.get("PRODUCTION_TOKEN")
CLIENT_ID = os.environ .get("EBAY_CLIENT_ID")
CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET")
REDIRECT_URI = "birkan_chalashk-birkanch-listin-hjzkzipt"
SCOPES = (
    "https://api.ebay.com/oauth/api_scope "
    "https://api.ebay.com/oauth/api_scope/sell.inventory"
)

# Set the target endpoint for the consent request in production
consent_endpoint_production = "https://auth.ebay.com/oauth2/authorize"
token_endpoint = "https://api.ebay.com/identity/v1/oauth2/token"    

consent_url = (
    f"{consent_endpoint_production}?"
    f"client_id={CLIENT_ID}&"
    f"redirect_uri={REDIRECT_URI}&"
    f"response_type=code&"
    f"scope={SCOPES}"
)

# Open the consent URL in the default web browser
webbrowser.open(consent_url)
print("Opening the browser. Please grant consent in the browser.")
returned_url = input("Enter the authorization code URL: ")

# Parse the URL to extract the authorization code
parsed_url = urlparse(returned_url)
query_params = parse_qs(parsed_url.query)
authorization_code = query_params.get('code', [])[0]

# Make the authorization code grant request to obtain the token
payload = {
    "grant_type": "authorization_code",
    "code": authorization_code,
    "redirect_uri": REDIRECT_URI
}

# Encode the client credentials for the Authorization header
credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
encoded_credentials = b64encode(credentials.encode()).decode()

# Set the headers for the token request
token_headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": f"Basic {encoded_credentials}"
}

# Make the POST request to the token endpoint
response = requests.post(token_endpoint, headers=token_headers, data=payload)

# Check the response
if response.status_code == 200:
    # Parse and print the response JSON
    response_json = response.json()
    print("Response containing the User access token:")
    print(response_json)
else:
    print(f"Error: {response.status_code}, {response.text}")

#############################################################
# Save the access token and refresh token to a file
access_token = response_json.get('access_token')
refresh_token = response_json.get('refresh_token')
with open("ebay_token.txt", "w") as file:
    file.write(f"Access Token: {access_token}\n")
    file.write(f"Refresh Token: {refresh_token}\n")