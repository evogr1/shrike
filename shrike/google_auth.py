"""Service-account credentials and API clients. Imports Google libraries lazily."""

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly", "https://www.googleapis.com/auth/drive"]


def credentials(secrets, scopes=SCOPES):
    from google.oauth2 import service_account

    return service_account.Credentials.from_service_account_file(secrets.service_account_file, scopes=scopes)


def service_account_email(secrets):
    import json

    try:
        with open(secrets.service_account_file) as f:
            return json.load(f).get("client_email", "the service account")
    except Exception:
        return "the service account"


def searchconsole(creds):
    from googleapiclient.discovery import build

    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def drive(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)
