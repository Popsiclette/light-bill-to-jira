from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", ["https://www.googleapis.com/auth/gmail.readonly"]
)
credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
print(credentials.refresh_token)
