import re
import json
from difflib import SequenceMatcher

# Common spelling variants -> one canonical form
ABBREV = {
    "street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd",
    "drive": "dr", "lane": "ln", "place": "pl", "court": "ct",
    "pike": "pike", "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}


def norm_street(street):
    """'1125 Logan Boulevard' -> '1125 logan blvd'"""
    words = re.sub(r"[^a-z0-9 ]", " ", street.lower()).split()
    return " ".join(ABBREV.get(w, w) for w in words)


def norm_name(name):
    """Drop punctuation and filler words so names compare fairly."""
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in {"the", "of", "at", "and"})


def name_similarity(a, b):
    return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()


def find_matches(loc, accounts):
    """Return CRM accounts that look like this website location."""
    matches = []
    loc_street = norm_street(loc["street"])
    for acc in accounts:
        if not acc["parent_id"] and "(Parent Account)" in acc["name"]:
            continue  # skip corporate parent accounts
        same_zip = acc["billing_zip"][:5] == loc["zip"]
        same_street = norm_street(acc["billing_street"]) == loc_street
        sim = name_similarity(loc["name"], acc["name"])

        if same_zip and same_street:
            matches.append((acc, "address", sim))
        elif same_zip and sim >= 0.75:
            matches.append((acc, "name+zip", sim))
    return matches


if __name__ == "__main__":
    locations = json.load(open("website_locations.json"))
    accounts = json.load(open("crm_accounts.json"))

    matched_ids = set()
    for loc in locations:
        matches = find_matches(loc, accounts)
        print(f"\n{loc['name']}  ({loc['city']}, {loc['state']})")
        if not matches:
            print("   -> NO CRM MATCH")
        for acc, how, sim in matches:
            matched_ids.add(acc["account_id"])
            print(f"   -> [{how:8} sim={sim:.2f}] {acc['account_id']} | {acc['name']} | "
                  f"parent: {acc['parent_name'] or '(none)'} | {acc['status']} | "
                  f"rev={acc['lifetime_revenue']} ar={acc['outstanding_ar']}")

    # Bellhaven-parented accounts that no website location claimed
    bh_parent = "0015QAPLGS3FVYEEEM"
    orphans = [a for a in accounts if a["parent_id"] == bh_parent and a["account_id"] not in matched_ids]
    print(f"\n=== Under Bellhaven in CRM but NOT on website: {len(orphans)} ===")
    for a in orphans:
        print(f"   {a['account_id']} | {a['name']} | {a['billing_street']}, {a['billing_city']} "
              f"{a['billing_zip']} | {a['status']}")