"""
DealStream scraper — dealstream.com
Uses Playwright. Tries multiple known URL patterns for their search page.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

BASE_URL  = "https://dealstream.com"
MAX_PAGES = 5

# DealStream has changed their URL structure over time — try all known patterns
SEARCH_URL_CANDIDATES = [
    f"{BASE_URL}/businesses-for-sale/",
    f"{BASE_URL}/",
    f"{BASE_URL}/buy/",
    f"{BASE_URL}/listings/",
    f"{BASE_URL}/search/",
]


class DealStreamScraper(BaseScraper):
    name = "dealstream"

    def fetch(self) -> list[dict]:
        # First, find which URL pattern works
        search_url = self._find_working_url()
        if not search_url:
            raise ScraperError("dealstream: could not find a working search URL")

        logger.info("dealstream: using search URL %s", search_url)

        def url_fn(page_num: int) -> str:
            sep = "&" if "?" in search_url else "?"
            return f"{search_url}{sep}country=US&page={page_num}"

        pages_html = self.fetch_html_pages(url_fn, max_pages=MAX_PAGES)

        listings = []
        for html in pages_html:
            page_listings = self._parse_page(html)
            listings.extend(page_listings)
            if len(page_listings) < 5:
                break

        return listings

    def _find_working_url(self) -> str | None:
        """Try candidate URLs until one returns a page with listing cards."""
        for candidate in SEARCH_URL_CANDIDATES:
            try:
                logger.info("dealstream: probing %s", candidate)
                html = self.fetch_html(candidate, wait=3000)
                soup = BeautifulSoup(html, "lxml")
                cards = self._find_cards(soup)
                if cards:
                    return candidate
                # Even if no cards, if the page loaded without error it may just
                # need query params — return it anyway
                if soup.select("main, #main, .container") and "404" not in soup.title.string if soup.title else True:
                    return candidate
            except Exception as exc:
                logger.debug("dealstream: probe failed for %s — %s", candidate, exc)

        return None

    def _find_cards(self, soup) -> list:
        return (
            soup.select("div.deal-item")
            or soup.select("div.listing-item")
            or soup.select("div[class*='deal-card']")
            or soup.select("div[class*='listing-card']")
            or soup.select("tr.deal-row")
            or soup.select("div[class*='deal']")
            or soup.select("article")
        )

    def _parse_page(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        cards = self._find_cards(soup)
        logger.debug("dealstream: found %d cards on page", len(cards))

        for card in cards:
            try:
                listing = self._parse_card(card)
                if listing:
                    results.append(listing)
            except Exception as exc:
                logger.debug("dealstream: card parse error — %s", exc)

        return results

    def _parse_card(self, card) -> dict | None:
        title_tag = (
            card.select_one("a.deal-title")
            or card.select_one("h3 > a")
            or card.select_one("h4 > a")
            or card.select_one("a[class*='title']")
            or card.select_one("a[href*='/deal/']")
            or card.select_one("a[href*='/listing/']")
            or card.select_one("a")
        )
        if not title_tag:
            return None

        title = title_tag.get_text(strip=True)
        if not title or len(title) < 4:
            return None

        href = title_tag.get("href", "")
        url  = href if href.startswith("http") else BASE_URL + href

        desc_tag = (
            card.select_one("p")
            or card.select_one("div.description")
            or card.select_one("div[class*='summary']")
            or card.select_one("div[class*='desc']")
        )
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Skip non-US listings
        full_text = card.get_text()
        if any(x in full_text for x in ["Canada", "United Kingdom", "Australia", "Germany"]):
            return None

        loc_tag = (
            card.select_one("span.location")
            or card.select_one("div.location")
            or card.select_one("[class*='location']")
        )
        if loc_tag:
            location = loc_tag.get_text(strip=True)
        else:
            m = re.search(r"[A-Za-z ]+,\s*[A-Z]{2}", full_text)
            location = m.group(0).strip() if m else ""
        state = self.extract_state(location)

        cat_tag = (
            card.select_one("[class*='industry']")
            or card.select_one("[class*='category']")
            or card.select_one("[class*='sector']")
        )
        industry = cat_tag.get_text(strip=True) if cat_tag else ""

        asking_price = ebitda = revenue = None
        for el in card.select("span, div, td, li, p"):
            text  = el.get_text(" ", strip=True)
            lower = text.lower()
            if len(text) > 80:
                continue
            val = self.parse_money(text)
            if val is None or val < 1_000:
                continue
            if "asking" in lower or "price" in lower:
                asking_price = asking_price or val
            elif "ebitda" in lower or "cash flow" in lower or "sde" in lower:
                ebitda = ebitda or val
            elif "revenue" in lower or "sales" in lower or "gross" in lower:
                revenue = revenue or val

        return {
            "title":        title,
            "description":  description[:400],
            "location":     location,
            "state":        state,
            "country":      "US",
            "industry":     industry,
            "revenue":      revenue,
            "ebitda":       ebitda,
            "asking_price": asking_price,
            "source":       "DealStream",
            "url":          url,
        }
