import os
import json
import requests
from dotenv import load_dotenv

# Load config from .env
load_dotenv()
TOKEN = os.getenv("BH_TOKEN")
API = os.getenv("BH_API")

# Search CRM accounts matching "bell"
response = requests.get(
    f"{API}/accounts",
    params={"q": "bell"},
    headers={"Authorization": f"Bearer {TOKEN}"},
)

print("Status code:", response.status_code)
print(json.dumps(response.json(), indent=2)[:3000])