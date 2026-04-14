"""
Deduplication store backed by SQLite.

A listing is considered "seen" if its URL has been sent before AND its key
financial fields (asking_price, ebitda) haven't changed.  If the price
changes we treat it as a new lead worth surfacing again.
"""

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "seen_listings.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_listings (
            url         TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            first_seen  TEXT NOT NULL,
            last_seen   TEXT NOT NULL,
            send_count  INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.commit()
    return conn


def _fingerprint(listing: dict) -> str:
    """Hash the fields that, if changed, make a listing worth re-sending."""
    key = json.dumps({
        "asking_price": listing.get("asking_price"),
        "ebitda":       listing.get("ebitda"),
        "revenue":      listing.get("revenue"),
    }, sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def is_new(listing: dict) -> bool:
    """Return True if this listing should be included in today's email."""
    url = listing.get("url", "")
    if not url:
        return True

    fp = _fingerprint(listing)
    conn = _connect()
    row = conn.execute("SELECT fingerprint FROM seen_listings WHERE url = ?", (url,)).fetchone()
    conn.close()

    if row is None:
        return True                   # never seen before
    return row["fingerprint"] != fp   # price/EBITDA changed → surface again


def mark_sent(listing: dict) -> None:
    """Record that this listing was included in today's email."""
    url = listing.get("url", "")
    if not url:
        return

    fp  = _fingerprint(listing)
    now = datetime.utcnow().isoformat()
    conn = _connect()
    conn.execute("""
        INSERT INTO seen_listings (url, fingerprint, first_seen, last_seen, send_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(url) DO UPDATE SET
            fingerprint = excluded.fingerprint,
            last_seen   = excluded.last_seen,
            send_count  = send_count + 1
    """, (url, fp, now, now))
    conn.commit()
    conn.close()


def mark_all_sent(listings: list[dict]) -> None:
    for listing in listings:
        mark_sent(listing)


def stats() -> dict:
    conn = _connect()
    total = conn.execute("SELECT COUNT(*) FROM seen_listings").fetchone()[0]
    conn.close()
    return {"total_seen_ever": total}
