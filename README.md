# Bellhaven → CRM Sync

Keeps CRM parent/child links accurate for Bellhaven Senior Living. A daily pipeline scrapes the operator's website, compares it with the CRM, and queues proposed fixes. A human approves or rejects each one in a local review app, and only approved changes are written back through the CRM API.

## How it works

```
scraper.py ──► matcher.py ──► store.py (decisions.db) ──► app.py ──► apply.py ──► CRM API
 website         proposals       review queue            approve        write + verify
```

| File | Role |
|---|---|
| `scraper.py` | Crawls every directory page **and the homepage** (new communities can be announced there before reaching the directory). Visits each profile for full address, care offerings, administrator, phone. Retries on network errors. |
| `crm.py` | Thin API client with pagination and retries. |
| `matcher.py` | Matching rules and proposal builder. Never writes to the CRM. |
| `store.py` | SQLite queue. Every proposal has a deterministic key, so decided items are never re-proposed. |
| `pipeline.py` | Daily entry point: scrape → pull CRM → match → sync queue. |
| `app.py` | Streamlit review app: diff, evidence, approve/reject with a reason, history. |
| `apply.py` | Executes approved actions, re-reads the account to verify every field, and resumes safely after a partial failure. |

## Matching approach

**Address is the primary key, not name.** Names change with rebrands and acquisitions; buildings don't.

1. Normalize streets (`Boulevard`→`blvd`, `West`→`w`, `Pk`→`pike`, …).
2. A CRM account matches a website location if it has:
   - same street + zip, or
   - same street + city (catches zip typos, e.g. 45626 vs 45662), or
   - a very similar name in the same zip/city.
3. The whole CRM is searched, not just accounts under Bellhaven, because Bellhaven facilities were found under Harborview, Cedar Trail, with no parent, and duplicated.
4. When several records share a building, one survivor is chosen by a fixed tie-break: billing history → parent lineage (Bellhaven > Harborview > Cedar Trail, per the website's About page) → has the website's administrator as a contact → number of contacts → Active → identical street text. The others become duplicates (`duplicate_of_account` + Inactive), and their active contacts are moved to the survivor.

## Outcomes handled

| Case | Action |
|---|---|
| Confident match, nothing differs | No proposal |
| Outdated name / address / zip | Field update |
| Wrong parent, **not** (revenue > 0 AND AR > 0) | Re-parent directly |
| Wrong parent, revenue > 0 AND AR > 0 | **CHOW** per SOP: old account untouched except `chow_current_account` → new account under Bellhaven |
| Duplicate records for one building | Mark losers as duplicates, move contacts |
| On website, not in CRM | Create account under Bellhaven |
| Under Bellhaven, not on website, another operator's account at the same address | Treated as sold: CHOW link if billing history, otherwise duplicate |
| Under Bellhaven, not on website, no evidence of a new owner | `Needs Review` + note (absence from a website is not proof of a sale) |

Every write appends a dated `[bellhaven-sync]` line to the account's `note` (never overwrites it), except on CHOW predecessor accounts, which the SOP says to leave as they are.

## Idempotency

Each proposal key encodes the exact change (for example `update:<id>:{"name": ...}` or `dup:<loser>:<survivor>`). On every run:
- approved or rejected keys are never re-queued;
- pending items are refreshed with current evidence;
- pending items the matcher no longer produces are marked `superseded`.

After a change is applied, the CRM itself no longer differs, so the proposal is no longer generated either. Verified: after reviewing, a re-run yields `new: 0, still_pending: 0` (the one rejected item is detected but not re-proposed).

## Running it

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add your token
python3 pipeline.py         # build/refresh the review queue
streamlit run app.py        # review at http://localhost:8501
```

`.env` (not committed):
```
BH_TOKEN=your_token_here
BH_API=https://analyst-assessment-production.up.railway.app/api/v1
```

## Schedule

`.github/workflows/daily-sync.yml` runs the pipeline daily at 11:00 UTC, with the token stored as the `BH_TOKEN` GitHub secret. `decisions.db` is committed on purpose: it is the queue and the audit trail, and the scheduled job needs it to know what was already decided. A plain cron equivalent:

```
0 6 * * * cd /path/to/bellhaven-sync && ./venv/bin/python pipeline.py >> sync.log 2>&1
```

## Review results (this run)

30 proposals: **29 approved, 1 rejected.**

| Type | Count |
|---|---|
| Field fixes (renames, zip typo) | 8 |
| Re-parents (Kettering, Lima, Zanesville, Findlay) | 4 |
| CHOW, new account created (Tiffin, Marietta) | 2 |
| CHOW, linked to existing buyer account (Sandusky → Millstone) | 1 |
| New accounts (Batavia, Union Square, Carlisle, Amberly Manor) | 4 |
| Duplicates retired | 7 |
| Contacts moved | 1 |
| Needs Review (Alliance, Coldwater) | 2 |
| **Rejected**: Ashtabula billing street `PO Box 517` → physical address | 1 |

Notable judgment calls:
- **Ashtabula rejected.** `billing_street` holds a PO Box; a PO Box is often intentional for invoicing, so I left it for the billing team rather than overwrite it with the physical address.
- **Amberly Manor created, not matched.** An "Amberly Manor" already exists in the CRM, but in Colorado Springs, CO under Juniper Point. Bellhaven's is in Hudson, OH. A name-only match would have re-parented the wrong facility.
- **Sandusky.** It is no longer on the website, and a Millstone account sits at the same address, so it was most likely sold. Because it has revenue and AR, it was linked via `chow_current_account` instead of being deactivated or re-parented.
- **Kettering.** Three records (Harborview, Cedar Trail, independent) shared one building. The Harborview record survived because Harborview was fully acquired by Bellhaven in 2025.

## What I'd build next

- Slack digest of new proposals each morning, with a link to the review app.
- Confidence scores on matches, with auto-approval for trivial cases (e.g. identical-address renames), keeping humans on parent changes, CHOW and creates.
- Map care offerings (the website lists several; the CRM holds one `care_type`) and compare phone numbers.
- Move `decisions.db` to a shared database so several reviewers can work the queue.
- Generalize the scraper config so other operators can be added without code changes.