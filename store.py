"""SQLite store for proposals and reviewer decisions.

A proposal's key encodes what it would change. Once a key has been approved
or rejected it is never proposed again, which makes daily re-runs safe.
"""
import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = "decisions.db"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            key         TEXT PRIMARY KEY,
            kind        TEXT,
            title       TEXT,
            account_id  TEXT,
            payload     TEXT,     -- full proposal as JSON (diff, actions, evidence)
            status      TEXT,     -- pending | approved | rejected | failed | superseded
            first_seen  TEXT,
            last_seen   TEXT,
            decided_at  TEXT,
            result      TEXT      -- API response or error message
        )""")
    return conn


def sync(proposals):
    """Insert new proposals, refresh pending ones, retire pending ones that vanished.

    Returns counts for logging.
    """
    conn = connect()
    now = _now()
    current_keys = {p["key"] for p in proposals}
    counts = {"new": 0, "still_pending": 0, "already_decided": 0, "superseded": 0}

    for p in proposals:
        row = conn.execute("SELECT status FROM proposals WHERE key = ?", (p["key"],)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO proposals (key, kind, title, account_id, payload, status, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (p["key"], p["kind"], p["title"], p["account_id"], json.dumps(p), now, now))
            counts["new"] += 1
        elif row["status"] in ("pending", "failed"):
            # Refresh evidence with today's data, keep it in the queue
            conn.execute("UPDATE proposals SET payload = ?, last_seen = ? WHERE key = ?",
                         (json.dumps(p), now, p["key"]))
            counts["still_pending"] += 1
        else:
            counts["already_decided"] += 1  # approved/rejected: never re-propose

    # Pending items the matcher no longer produces are out of date
    for row in conn.execute("SELECT key FROM proposals WHERE status = 'pending'").fetchall():
        if row["key"] not in current_keys:
            conn.execute("UPDATE proposals SET status = 'superseded', decided_at = ? WHERE key = ?",
                         (now, row["key"]))
            counts["superseded"] += 1

    conn.commit()
    conn.close()
    return counts


def list_proposals(statuses):
    conn = connect()
    marks = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM proposals WHERE status IN ({marks}) ORDER BY kind, title", statuses).fetchall()
    conn.close()
    return [dict(r) | {"payload": json.loads(r["payload"])} for r in rows]


def decide(key, status, result=""):
    conn = connect()
    conn.execute("UPDATE proposals SET status = ?, decided_at = ?, result = ? WHERE key = ?",
                 (status, _now(), result, key))
    conn.commit()
    conn.close()