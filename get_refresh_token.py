"""
Run this ONCE, locally, in your existing "bills system" folder (where
token.json already exists from running drive_auth.py earlier).
Usage: python get_refresh_token.py

Prints the three values to paste into Vercel's Environment Variables.
Nothing here gets sent anywhere — it just reads the file on your disk.
"""
import json
from pathlib import Path

token_path = Path("token.json")
if not token_path.exists():
    print("token.json not found in this folder. Run drive_auth.py first (in the original")
    print("bills system project), then copy token.json next to this script and rerun.")
    raise SystemExit(1)

data = json.loads(token_path.read_text())

missing = [k for k in ("refresh_token", "client_id", "client_secret") if not data.get(k)]
if missing:
    print(f"token.json is missing: {', '.join(missing)}")
    print("Delete token.json and rerun drive_auth.py to get a fresh one with all fields.")
    raise SystemExit(1)

print("Paste these into Vercel -> Project Settings -> Environment Variables:\n")
print(f"GOOGLE_OAUTH_REFRESH_TOKEN = {data['refresh_token']}")
print(f"GOOGLE_OAUTH_CLIENT_ID     = {data['client_id']}")
print(f"GOOGLE_OAUTH_CLIENT_SECRET = {data['client_secret']}")
