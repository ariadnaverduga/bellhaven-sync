"""Daily job: scrape website -> pull CRM -> build proposals -> queue new ones.

It never writes to the CRM. Writes only happen when a reviewer approves in the app.
"""
import json
import crm
import store
from scraper import scrape
from matcher import build_proposals


def run():
    print("1/4 Scraping website...")
    locations = scrape()
    with open("website_locations.json", "w") as f:
        json.dump(locations, f, indent=2)
    print(f"    {len(locations)} locations")

    print("2/4 Pulling CRM...")
    accounts, contacts = crm.get_accounts(), crm.get_contacts()
    print(f"    {len(accounts)} accounts, {len(contacts)} contacts")

    print("3/4 Matching...")
    proposals = build_proposals(locations, accounts, contacts)
    print(f"    {len(proposals)} proposals generated")

    print("4/4 Syncing review queue...")
    counts = store.sync(proposals)
    print(f"    {counts}")


if __name__ == "__main__":
    run()