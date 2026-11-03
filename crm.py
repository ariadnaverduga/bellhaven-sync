"""Thin client for the Bellhaven CRM sandbox API."""
import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("BH_API")
HEADERS = {"Authorization": f"Bearer {os.getenv('BH_TOKEN')}"}


def _request(method, path, retries=4, **kwargs):
    """HTTP call with retries on network errors and 5xx responses."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.request(method, f"{API}{path}", headers=HEADERS, timeout=30, **kwargs)
            if resp.status_code >= 500 and attempt < retries:
                raise requests.HTTPError(f"server error {resp.status_code}")
            if not resp.ok:
                raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text}")
            return resp.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def _fetch_all(path):
    """Page through a list endpoint until an empty page comes back."""
    items, page = [], 1
    while True:
        body = _request("GET", path, params={"page": page, "page_size": 50})
        batch = body.get("data", [])
        if not batch:
            return items
        items.extend(batch)
        page += 1


def get_accounts():
    return _fetch_all("/accounts")


def get_contacts():
    return _fetch_all("/contacts")


def get_account(account_id):
    return _request("GET", f"/accounts/{account_id}")


def update_account(account_id, fields):
    return _request("PATCH", f"/accounts/{account_id}", json=fields)


def create_account(fields):
    return _request("POST", "/accounts", json=fields)


def update_contact(contact_id, fields):
    return _request("PATCH", f"/contacts/{contact_id}", json=fields)


if __name__ == "__main__":
    # Quick check: how contacts look and how they link to accounts
    contacts = get_contacts()
    print("Total contacts:", len(contacts))
    print("Contact fields:", list(contacts[0].keys()))
    print("Example:", contacts[0])