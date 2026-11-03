import json
from collections import Counter

with open("crm_accounts.json") as f:
    accounts = json.load(f)

# Parent companies = accounts with no parent of their own
parents = [a for a in accounts if not a["parent_id"]]
print(f"Parent accounts ({len(parents)}):")
for p in parents:
    print(f"  {p['account_id']}  {p['name']}")

# How many facilities hang under each parent
print("\nFacilities per parent:")
by_parent = Counter(a["parent_name"] for a in accounts if a["parent_id"])
for name, count in by_parent.most_common():
    print(f"  {count:3}  {name}")

# Status breakdown
print("\nStatus:", dict(Counter(a["status"] for a in accounts)))

# Accounts that have both revenue and outstanding AR (SOP-sensitive)
sop = [a for a in accounts if a["lifetime_revenue"] > 0 and a["outstanding_ar"] > 0]
print(f"\nAccounts with revenue AND outstanding AR: {len(sop)}")