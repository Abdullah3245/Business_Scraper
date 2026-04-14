"""
Acquire.com scraper — acquire.com/marketplace

Acquire.com is a React SPA. The public marketplace page loads listing data
via an internal JSON API that is called when the page renders.

Strategy:
  1. Try the undocumented JSON API endpoint (reverse-engineered from browser
     network tab — /api/listings or similar).
  2. If that returns 401/403 (requires auth), use Playwright to render the
     page as a real browser and scrape the DOM.

NOTE: Acquire.com requires a free account to see full details.
      Set email/password in config.yaml → sources.acquire.username / .password
      and they will be used to log in via Playwright.
"""

from __future__ import annotations

import logging
import os

from scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

BASE_URL        = "https://acquire.com"
MARKETPLACE_URL = f"{BASE_URL}/marketplace"
LOGIN_URL       = f"{BASE_URL}/login"

# Known JSON API endpoints (may change; update if acquire.com changes their API)
API_ENDPOINTS = [
    f"{BASE_URL}/api/listings",
    f"{BASE_URL}/api/v1/listings",
    f"{BASE_URL}/api/v2/listings",
]


class AcquireScraper(BaseScraper):
    name = "acquire"

    def fetch(self) -> list[dict]:
        # ── Try JSON API first (no auth needed for public listings) ──────
        listings = self._try_json_api()
        if listings is not None:
            return listings

        # ── Fall back to Playwright ───────────────────────────────────────
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ScraperError(
                "acquire: Playwright not installed. "
                "Run: pip install playwright && playwright install chromium"
            )

        return self._scrape_with_playwright()

    # ── JSON API attempt ──────────────────────────────────────────────────

    def _try_json_api(self) -> list[dict] | None:
        """
        Try known API endpoints. Returns None if all fail (caller falls back
        to Playwright). Returns [] if the endpoint works but has no results.
        """
        import json

        filters = self.cfg.get("filters", {})
        price_min = int(filters.get("price_min", 5_000_000))
        price_max = int(filters.get("price_max", 100_000_000))

        for endpoint in API_ENDPOINTS:
            try:
                params = {
                    "asking_price_min": price_min,
                    "asking_price_max": price_max,
                    "status":           "for_sale",
                    "per_page":         100,
                }
                resp = self.get(endpoint, params=params)
                data = resp.json()
                listings = self._parse_json(data)
                logger.info("acquire: JSON API succeeded at %s, %d listings", endpoint, len(listings))
                return listings
            except Exception as exc:
                logger.debug("acquire: JSON API failed at %s — %s", endpoint, exc)

        return None   # all endpoints failed

    def _parse_json(self, data) -> list[dict]:
        # Acquire may return { listings: [...] } or just [...]
        if isinstance(data, list):
            raw_list = data
        elif isinstance(data, dict):
            raw_list = (
                data.get("listings")
                or data.get("data")
                or data.get("results")
                or []
            )
        else:
            return []

        results = []
        for item in raw_list:
            try:
                listing = self._normalise_json_item(item)
                if listing:
                    results.append(listing)
            except Exception as exc:
                logger.debug("acquire: JSON item parse error — %s", exc)

        return results

    def _normalise_json_item(self, item: dict) -> dict | None:
        slug  = item.get("slug") or item.get("id") or ""
        url   = item.get("url") or (f"{MARKETPLACE_URL}/{slug}" if slug else "")
        if not url:
            return None

        title       = item.get("name") or item.get("title") or "Untitled"
        description = item.get("description") or item.get("tagline") or ""
        location    = item.get("location") or item.get("country") or "US"
        industry    = item.get("category") or item.get("industry") or ""

        asking_price = self.parse_money(str(item.get("asking_price", "") or ""))
        ebitda       = self.parse_money(str(item.get("ebitda", "") or item.get("profit", "") or ""))
        revenue      = self.parse_money(str(item.get("revenue", "") or item.get("arr", "") or ""))

        return {
            "title":        title,
            "description":  str(description)[:400],
            "location":     location,
            "state":        self.extract_state(location),
            "country":      "US",
            "industry":     industry,
            "revenue":      revenue,
            "ebitda":       ebitda,
            "asking_price": asking_price,
            "source":       "Acquire.com",
            "url":          url,
        }

    # ── Playwright fallback ───────────────────────────────────────────────

    def _scrape_with_playwright(self) -> list[dict]:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup

        username = self.source_cfg.get("username", "")
        password = self.source_cfg.get("password", "")

        listings = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx     = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = ctx.new_page()

            # Log in if credentials provided
            if username and password:
                logger.info("acquire: logging in as %s", username)
                page.goto(LOGIN_URL, wait_until="networkidle")
                page.fill("input[type='email'], input[name='email']", username)
                page.fill("input[type='password'], input[name='password']", password)
                page.click("button[type='submit']")
                page.wait_for_load_state("networkidle")

            logger.info("acquire: navigating to marketplace")
            page.goto(MARKETPLACE_URL, wait_until="networkidle")
            page.wait_for_timeout(3000)   # let JS hydrate

            # Scroll to load more (infinite scroll)
            for _ in range(3):
                page.keyboard.press("End")
                page.wait_for_timeout(1500)

            html = page.content()
            browser.close()

        soup  = BeautifulSoup(html, "lxml")
        cards = soup.select(
            "div[class*='listing'], div[class*='card'], article[class*='listing']"
        )

        for card in cards:
            try:
                title_tag = card.select_one("h2, h3, h4, [class*='title'], [class*='name']")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)

                link_tag = card.select_one("a[href]")
                href     = link_tag["href"] if link_tag else ""
                url      = href if href.startswith("http") else BASE_URL + href

                desc_tag    = card.select_one("p, [class*='desc'], [class*='tagline']")
                description = desc_tag.get_text(strip=True) if desc_tag else ""

                asking_price = ebitda = revenue = None
                for el in card.select("span, div"):
                    text  = el.get_text(" ", strip=True)
                    lower = text.lower()
                    val   = self.parse_money(text)
                    if val is None:
                        continue
                    if "ask" in lower or "price" in lower:
                        asking_price = val
                    elif "profit" in lower or "ebitda" in lower:
                        ebitda = val
                    elif "revenue" in lower or "arr" in lower or "mrr" in lower:
                        revenue = val

                if not url:
                    continue

                listings.append({
                    "title":        title,
                    "description":  description[:400],
                    "location":     "US",
                    "state":        "",
                    "country":      "US",
                    "industry":     "",
                    "revenue":      revenue,
                    "ebitda":       ebitda,
                    "asking_price": asking_price,
                    "source":       "Acquire.com",
                    "url":          url,
                })
            except Exception as exc:
                logger.debug("acquire: playwright card parse error — %s", exc)

        logger.info("acquire: playwright found %d listings", len(listings))
        return listings
