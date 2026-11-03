"""Match Bellhaven website locations to CRM accounts and build proposed changes.

Nothing in this file writes to the CRM. It only returns proposals for a human
reviewer to approve or reject.
"""
import re
import json
from datetime import date
from difflib import SequenceMatcher

# Street-word variants -> one canonical form, so "Logan Boulevard" == "Logan Blvd"
ABBREV = {
    "street": "st", "avenue": "ave", "av": "ave", "boulevard": "blvd", "road": "rd",
    "drive": "dr", "lane": "ln", "place": "pl", "court": "ct", "circle": "cir",
    "parkway": "pkwy", "highway": "hwy", "square": "sq", "terrace": "ter",
    "pk": "pike", "pke": "pike",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northwest": "nw", "northeast": "ne", "southwest": "sw", "southeast": "se",
}

# Website care labels -> CRM care_type values
CARE_MAP = {
    "Assisted Living": "Assisted Living",
    "Memory Support": "Memory Care",
    "Short-Term Rehabilitation & Nursing": "Skilled Nursing",
}

# Operators whose communities folded into Bellhaven (per the website's About page).
# Only used to break ties when several CRM records describe the same building.
PREDECESSOR_RANK = {"Harborview Care Group": 2, "Cedar Trail Communities": 1}


# ---------- normalization helpers ----------

def norm_street(s):
    words = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return " ".join(ABBREV.get(w, w) for w in words)


def norm_name(s):
    words = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return " ".join(w for w in words if w not in {"the", "of", "at", "and"})


def name_sim(a, b):
    return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()


def zip5(z):
    return (z or "")[:5]


def is_parent_account(a):
    return not a["parent_id"] and "(Parent Account)" in a["name"]


def has_billing_history(a):
    """SOP trigger: revenue history AND outstanding AR greater than zero."""
    return a["lifetime_revenue"] > 0 and a["outstanding_ar"] > 0


def is_retired(a):
    """Already resolved earlier as a duplicate or a CHOW predecessor."""
    return bool(a["duplicate_of_account"] or a["chow_current_account"])


def stamp(acc, text):
    """Append a dated line to the account's existing note (never overwrite it)."""
    line = f"[bellhaven-sync {date.today().isoformat()}] {text}"
    return f"{acc['note']}\n{line}" if acc.get("note") else line


def money(x):
    return f"${x:,.0f}"


# ---------- matching ----------

def match_type(loc, acc):
    """Return how a CRM account matches a website location, or None."""
    same_street = norm_street(acc["billing_street"]) == norm_street(loc["street"])
    same_zip = zip5(acc["billing_zip"]) == loc["zip"]
    same_city = (acc["billing_city"].strip().lower() == loc["city"].lower()
                 and acc["billing_state"] == loc["state"])
    sim = name_sim(loc["name"], acc["name"])

    if same_street and same_zip:
        return "same street + zip"
    if same_street and same_city:
        return "same street + city (zip differs)"
    if same_zip and sim >= 0.75:
        return f"similar name ({sim:.2f}) + same zip"
    if same_city and sim >= 0.9:
        return f"similar name ({sim:.2f}) + same city"
    return None


def parent_preference(acc, bh_id):
    if acc["parent_id"] == bh_id:
        return 3
    parent = acc["parent_name"] or ""
    return max((r for k, r in PREDECESSOR_RANK.items() if k in parent), default=0)


def rank_candidates(cands, loc, contacts_by_acct, bh_id):
    """Best surviving record first.

    Tie-break order: billing history > parent lineage > has the website's
    administrator as a contact > number of contacts > Active > identical street text.
    """
    admin = (loc.get("administrator") or "").strip().lower()

    def key(acc):
        cs = [c for c in contacts_by_acct.get(acc["account_id"], []) if c["is_active"]]
        return (
            acc["lifetime_revenue"] > 0 or acc["outstanding_ar"] > 0,
            parent_preference(acc, bh_id),
            any(c["name"].strip().lower() == admin for c in cs),
            len(cs),
            acc["status"] == "Active",
            acc["billing_street"].strip().lower() == loc["street"].strip().lower(),
        )

    ordered = sorted(cands, key=lambda a: a["account_id"])  # deterministic last tie-break
    return sorted(ordered, key=key, reverse=True)


# ---------- proposal builders ----------

def loc_line(loc):
    return (f"Website: {loc['name']} | {loc['street']}, {loc['city']}, {loc['state']} {loc['zip']} | "
            f"{', '.join(loc['care_offerings'])} | admin: {loc.get('administrator') or 'n/a'} | "
            f"found on {loc['found_on']} ({loc['url']})")


def acc_line(a):
    return (f"CRM {a['account_id']}: {a['name']} | {a['billing_street']}, {a['billing_city']}, "
            f"{a['billing_state']} {a['billing_zip']} | parent: {a['parent_name'] or '(none)'} | "
            f"{a['status']} | revenue {money(a['lifetime_revenue'])}, AR {money(a['outstanding_ar'])}")


def make(kind, key, title, account_id, diff, actions, evidence):
    return {"key": key, "kind": kind, "title": title, "account_id": account_id,
            "diff": diff, "actions": actions, "evidence": evidence}


def new_account_fields(loc, bh_id, note):
    care = [CARE_MAP.get(c, c) for c in loc["care_offerings"]]
    return {
        "name": loc["name"], "parent_id": bh_id,
        "billing_street": loc["street"], "billing_city": loc["city"],
        "billing_state": loc["state"], "billing_zip": loc["zip"],
        "care_type": care[0] if care else "", "phone": loc.get("phone", ""),
        "status": "Active", "note": note,
    }


def create_proposal(loc, bh_id, bh_name):
    note = f"[bellhaven-sync {date.today().isoformat()}] Created from Bellhaven website ({loc['url']})"
    fields = new_account_fields(loc, bh_id, note)
    diff = [{"field": f, "current": "", "proposed": bh_name if f == "parent_id" else v}
            for f, v in fields.items() if f != "note"]
    return make("Create account", f"create:{loc['slug']}", f"Create: {loc['name']}", None, diff,
                [{"op": "create_account", "fields": fields}],
                [loc_line(loc), "No CRM account found at this address or with a similar name nearby."])


def update_proposal(acc, loc, bh_id, bh_name, how):
    target = {
        "name": loc["name"], "billing_street": loc["street"], "billing_city": loc["city"],
        "billing_state": loc["state"], "billing_zip": loc["zip"],
        "parent_id": bh_id, "status": "Active",
    }
    unchanged = {
        "name": acc["name"] == loc["name"],
        "billing_street": norm_street(acc["billing_street"]) == norm_street(loc["street"]),
        "billing_city": acc["billing_city"].strip().lower() == loc["city"].lower(),
        "billing_state": acc["billing_state"] == loc["state"],
        "billing_zip": zip5(acc["billing_zip"]) == loc["zip"],
        "parent_id": acc["parent_id"] == bh_id,
        "status": acc["status"] == "Active",
    }
    fields = {f: v for f, v in target.items() if not unchanged[f]}
    if not fields:
        return None  # confident match, nothing to change

    diff = [{"field": f,
             "current": (acc["parent_name"] or "(none)") if f == "parent_id" else acc[f],
             "proposed": bh_name if f == "parent_id" else v} for f, v in fields.items()]
    key = f"update:{acc['account_id']}:{json.dumps(fields, sort_keys=True)}"
    reparent = "parent_id" in fields

    evidence = [loc_line(loc), acc_line(acc), f"Matched by: {how}"]
    if reparent:
        evidence.append(f"SOP check: revenue {money(acc['lifetime_revenue'])}, AR "
                        f"{money(acc['outstanding_ar'])} -> not both > 0, so re-parent directly.")
    fields["note"] = stamp(acc, "Updated to match Bellhaven website: " + ", ".join(fields))

    kind = "Re-parent" if reparent else "Fix fields"
    return make(kind, key, f"{kind}: {acc['name']}", acc["account_id"], diff,
                [{"op": "update_account", "account_id": acc["account_id"], "fields": fields}], evidence)


def chow_create_proposal(old, loc, bh_id, bh_name):
    note = (f"[bellhaven-sync {date.today().isoformat()}] Created by CHOW from {old['account_id']} "
            f"({old['name']}); old account kept for billing.")
    fields = new_account_fields(loc, bh_id, note)
    diff = [{"field": f"NEW account: {f}", "current": "", "proposed": bh_name if f == "parent_id" else v}
            for f, v in fields.items() if f != "note"]
    diff.append({"field": f"OLD {old['account_id']}: chow_current_account",
                 "current": old["chow_current_account"] or "", "proposed": "(new account id)"})
    evidence = [loc_line(loc), acc_line(old),
                f"SOP: revenue {money(old['lifetime_revenue'])} AND AR {money(old['outstanding_ar'])} "
                "-> do NOT re-parent. Create a new account under Bellhaven and point the old one to it."]
    return make("CHOW (create new)", f"chow-create:{old['account_id']}:{loc['slug']}",
                f"CHOW: {old['name']} -> new Bellhaven account", old["account_id"], diff,
                [{"op": "create_account", "fields": fields, "save_as": "new_id"},
                 {"op": "update_account", "account_id": old["account_id"],
                  "fields": {"chow_current_account": "$new_id"}}],
                evidence)


def chow_pointer_proposal(old, current, evidence_lines):
    diff = [{"field": "chow_current_account", "current": old["chow_current_account"] or "",
             "proposed": f"{current['account_id']} ({current['name']})"}]
    evidence = evidence_lines + [acc_line(old), acc_line(current),
        f"SOP: revenue {money(old['lifetime_revenue'])} AND AR {money(old['outstanding_ar'])} "
        "-> leave the old account as is; an account under the correct parent already exists, so link to it."]
    return make("CHOW (link existing)", f"chow:{old['account_id']}:{current['account_id']}",
                f"CHOW: {old['name']} -> {current['name']}", old["account_id"], diff,
                [{"op": "update_account", "account_id": old["account_id"],
                  "fields": {"chow_current_account": current["account_id"]}}],
                evidence)


def duplicate_proposals(loser, survivor, contacts_by_acct, why):
    fields = {"duplicate_of_account": survivor["account_id"], "status": "Inactive"}
    diff = [{"field": "duplicate_of_account", "current": loser["duplicate_of_account"] or "",
             "proposed": f"{survivor['account_id']} ({survivor['name']})"},
            {"field": "status", "current": loser["status"], "proposed": "Inactive"}]
    fields["note"] = stamp(loser, f"Duplicate of {survivor['account_id']} ({survivor['name']}): {why}")
    props = [make("Mark duplicate", f"dup:{loser['account_id']}:{survivor['account_id']}",
                  f"Duplicate: {loser['name']} -> {survivor['name']}", loser["account_id"], diff,
                  [{"op": "update_account", "account_id": loser["account_id"], "fields": fields}],
                  [acc_line(loser), acc_line(survivor), f"Why: {why}"])]

    # Re-home active contacts so no relationship data is stranded on the inactive copy
    for c in contacts_by_acct.get(loser["account_id"], []):
        if not c["is_active"]:
            continue
        props.append(make(
            "Move contact", f"move-contact:{c['contact_id']}:{survivor['account_id']}",
            f"Move contact {c['name']} -> {survivor['name']}", loser["account_id"],
            [{"field": "contact account_id", "current": f"{loser['account_id']} ({loser['name']})",
              "proposed": f"{survivor['account_id']} ({survivor['name']})"}],
            [{"op": "update_contact", "contact_id": c["contact_id"],
              "fields": {"account_id": survivor["account_id"]}}],
            [f"Contact: {c['name']} ({c['title']}) {c['email']} {c['phone']}",
             f"Its account {loser['account_id']} is being marked as a duplicate of {survivor['account_id']}."]))
    return props


def review_proposal(acc):
    fields = {"status": "Needs Review",
              "note": stamp(acc, "No longer listed on the Bellhaven website and no other CRM account "
                                 "at this address. Confirm closure or sale with sales.")}
    return make("Needs review", f"review:{acc['account_id']}", f"Not on website: {acc['name']}",
                acc["account_id"], [{"field": "status", "current": acc["status"], "proposed": "Needs Review"}],
                [{"op": "update_account", "account_id": acc["account_id"], "fields": fields}],
                [acc_line(acc), "Under Bellhaven in the CRM, but not on any website page (directory or homepage).",
                 "No other CRM account shares this address, so there is no evidence of a new owner."])


# ---------- main entry point ----------

def build_proposals(locations, accounts, contacts):
    bh = next(a for a in accounts if is_parent_account(a) and "Bellhaven" in a["name"])
    bh_id, bh_name = bh["account_id"], bh["name"]

    contacts_by_acct = {}
    for c in contacts:
        contacts_by_acct.setdefault(c["account_id"], []).append(c)

    pool = [a for a in accounts if not is_parent_account(a) and not is_retired(a)]
    proposals, claimed = [], set()

    # 1) Every website location -> its CRM record(s)
    for loc in locations:
        cands = [(a, how) for a in pool if (how := match_type(loc, a))]
        if not cands:
            proposals.append(create_proposal(loc, bh_id, bh_name))
            continue

        how_by_id = {a["account_id"]: h for a, h in cands}
        ranked = rank_candidates([a for a, _ in cands], loc, contacts_by_acct, bh_id)
        claimed.update(a["account_id"] for a in ranked)
        top = ranked[0]
        keep = {top["account_id"]}

        if top["parent_id"] != bh_id and has_billing_history(top):
            # SOP: billing team needs the old account preserved
            existing_bh = next((a for a in ranked if a["parent_id"] == bh_id), None)
            if existing_bh:
                proposals.append(chow_pointer_proposal(top, existing_bh, [loc_line(loc)]))
                survivor = existing_bh
            else:
                proposals.append(chow_create_proposal(top, loc, bh_id, bh_name))
                survivor = None  # the new account does not exist yet
        else:
            survivor = top

        if survivor:
            keep.add(survivor["account_id"])
            upd = update_proposal(survivor, loc, bh_id, bh_name, how_by_id[survivor["account_id"]])
            if upd:
                others = [a for a in ranked if a["account_id"] not in keep]
                if others:
                    upd["evidence"].append(
                        f"Chosen as survivor over {len(others)} other record(s) at this address: "
                        + "; ".join(f"{a['name']} (parent: {a['parent_name'] or 'none'})" for a in others))
                proposals.append(upd)

        anchor = survivor or top
        for other in ranked:
            if other["account_id"] in keep:
                continue
            why = f"same facility as website location '{loc['name']}' ({how_by_id[other['account_id']]})"
            proposals.extend(duplicate_proposals(other, anchor, contacts_by_acct, why))

    # 2) Bellhaven accounts that no website location claimed
    for a in pool:
        if a["parent_id"] != bh_id or a["account_id"] in claimed:
            continue
        if a["status"] in ("Inactive", "Needs Review"):
            continue  # already off or already flagged
        same_addr = [o for o in pool
                     if o["account_id"] != a["account_id"] and o["parent_id"] != bh_id
                     and norm_street(o["billing_street"]) == norm_street(a["billing_street"])
                     and zip5(o["billing_zip"]) == zip5(a["billing_zip"])]
        if same_addr:
            new_home = same_addr[0]
            line = (f"Not on the Bellhaven website, and {new_home['account_id']} ({new_home['name']}, "
                    f"parent: {new_home['parent_name'] or '(none)'}) is at the same address -> facility changed owner.")
            if has_billing_history(a):
                proposals.append(chow_pointer_proposal(a, new_home, [line]))
            else:
                proposals.extend(duplicate_proposals(a, new_home, contacts_by_acct, line))
        else:
            proposals.append(review_proposal(a))

    return proposals


if __name__ == "__main__":
    import crm

    locations = json.load(open("website_locations.json"))
    proposals = build_proposals(locations, crm.get_accounts(), crm.get_contacts())

    print(f"{len(proposals)} proposals\n")
    for p in proposals:
        print(f"[{p['kind']}] {p['title']}")
        for d in p["diff"]:
            print(f"     {d['field']}: '{d['current']}' -> '{d['proposed']}'")