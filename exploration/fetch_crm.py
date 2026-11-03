import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BH_TOKEN")
API = os.getenv("BH_API")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def fetch_all_accounts():
    """Page through GET /accounts until an empty page comes back."""
    accounts = []
    page = 1
    while True:
        resp = requests.get(
            f"{API}/accounts",
            params={"page": page, "page_size": 50},
            headers=HEADERS,
        )
        resp.raise_for_status()  # stop with an error if the request failed
        body = resp.json()

        if page == 1:
            # Show what else the API returns besides "data" (e.g. totals)
            print("Response keys:", list(body.keys()))

        batch = body.get("data", [])
        if not batch:
            break
        accounts.extend(batch)
        page += 1
    return accounts


if __name__ == "__main__":
    accounts = fetch_all_accounts()
    print("Total accounts downloaded:", len(accounts))

    # Save a local snapshot so we can explore it
    with open("crm_accounts.json", "w") as f:
        json.dump(accounts, f, indent=2)
    print("Saved to crm_accounts.json")