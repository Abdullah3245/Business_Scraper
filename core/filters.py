"""
Filter engine.

Applies the criteria from config.yaml to a raw listing dict and returns
True if the listing should be included in the email digest.

Expected listing schema (all fields optional except url):
{
    "title":        str,
    "description":  str,
    "location":     str,   # "City, ST" or just "ST"
    "state":        str,   # 2-letter state code
    "country":      str,   # "US" etc.
    "industry":     str,
    "revenue":      float | None,
    "ebitda":       float | None,
    "asking_price": float | None,
    "source":       str,
    "url":          str,
}
"""

from __future__ import annotations
import re
from typing import Any


def _parse_money(value: Any) -> float | None:
    """Convert '$1,250,000' or 1250000 or '1.25M' → float, or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().upper().replace(",", "").replace("$", "").replace(" ", "")
    if not s or s in ("N/A", "NOT LISTED", "-", ""):
        return None
    multiplier = 1
    if s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 1_000_000_000
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _contains_franchise_keyword(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    for kw in keywords:
        if kw.lower() in text_lower:
            return True
    return False


def passes_filters(listing: dict, cfg: dict) -> tuple[bool, str]:
    """
    Returns (True, "") if the listing passes all filters,
    or (False, reason) if it fails.
    """
    f = cfg.get("filters", {})

    # ── 1. Franchise check ────────────────────────────────────────────────
    franchise_kws = f.get("franchise_keywords", [])
    combined_text = f"{listing.get('title', '')} {listing.get('description', '')}"
    if _contains_franchise_keyword(combined_text, franchise_kws):
        return False, "franchise keyword detected"

    # ── 2. Geography ──────────────────────────────────────────────────────
    country = listing.get("country", "US")
    if country and country.upper() != f.get("country", "US").upper():
        return False, f"country={country}"

    allowed_states = [s.upper() for s in f.get("states", [])]
    if allowed_states:
        listing_state = (listing.get("state") or "").upper()
        if listing_state not in allowed_states:
            return False, f"state={listing_state} not in allowed list"

    # ── 3. Industry blocklist ─────────────────────────────────────────────
    industries_exclude = [i.lower() for i in f.get("industries_exclude", [])]
    if industries_exclude:
        listing_industry = (listing.get("industry") or "").lower()
        for excl in industries_exclude:
            if excl in listing_industry:
                return False, f"industry '{listing_industry}' excluded"

    # ── 4. Financial filters ──────────────────────────────────────────────
    ebitda        = _parse_money(listing.get("ebitda"))
    asking_price  = _parse_money(listing.get("asking_price"))

    ebitda_min  = f.get("ebitda_min", 2_000_000)
    ebitda_max  = f.get("ebitda_max", 10_000_000)
    price_min   = f.get("price_min",  5_000_000)
    price_max   = f.get("price_max",  100_000_000)

    if ebitda is not None:
        # Primary signal: EBITDA is listed
        if ebitda < ebitda_min:
            return False, f"EBITDA ${ebitda:,.0f} below min ${ebitda_min:,.0f}"
        if ebitda > ebitda_max:
            return False, f"EBITDA ${ebitda:,.0f} above max ${ebitda_max:,.0f}"
    elif asking_price is not None:
        # Fallback: use asking price as proxy
        if asking_price < price_min:
            return False, f"Price ${asking_price:,.0f} below proxy min ${price_min:,.0f}"
        if asking_price > price_max:
            return False, f"Price ${asking_price:,.0f} above proxy max ${price_max:,.0f}"
    else:
        # No financial data at all — exclude (can't evaluate)
        return False, "no EBITDA or asking price available"

    return True, ""


def apply_filters(listings: list[dict], cfg: dict) -> tuple[list[dict], list[dict]]:
    """
    Split listings into (passed, rejected).
    Adds a '_filter_reason' key to rejected listings for debugging.
    """
    passed, rejected = [], []
    for listing in listings:
        ok, reason = passes_filters(listing, cfg)
        if ok:
            passed.append(listing)
        else:
            listing["_filter_reason"] = reason
            rejected.append(listing)
    return passed, rejected
