"""
BizBuySell scraper — bizbuysell.com
Uses Playwright to bypass bot detection (site blocks plain HTTP requests).
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bizbuysell.com"
MAX_PAGES = 5


class BizBuySellScraper(BaseScraper):
    name = "bizbuysell"

    def fetch(self) -> list[dict]:
        cfg_params = self.source_cfg.get("params", {})
        price_from = int(cfg_params.get("asking_price_from", 5_000_000))
        price_to   = int(cfg_params.get("asking_price_to",  100_000_000))

        def url_fn(page_num: int) -> str:
            return (
                f"{BASE_URL}/businesses-for-sale/"
                f"?asking_price_from={price_from}"
                f"&asking_price_to={price_to}"
                f"&page={page_num}"
            )

        pages_html = self.fetch_html_pages(url_fn, max_pages=MAX_PAGES)

        listings = []
        for html in pages_html:
            page_listings = self._parse_page(html)
            listings.extend(page_listings)
            if len(page_listings) < 10:
                break

        if not listings:
            raise ScraperError("bizbuysell: no listings found — selectors may need updating")

        return listings

    def _parse_page(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        # BizBuySell listing cards
        cards = (
            soup.select("article.result")
            or soup.select("div.result")
            or soup.select("div[class*='listing-result']")
            or soup.select("div[class*='listing_result']")
            or soup.select("li[class*='listing']")
        )

        logger.debug("bizbuysell: found %d cards on page", len(cards))

        for card in cards:
            try:
                listing = self._parse_card(card)
                if listing:
                    results.append(listing)
            except Exception as exc:
                logger.debug("bizbuysell: card parse error — %s", exc)

        return results

    def _parse_card(self, card) -> dict | None:
        # Title + URL
        title_tag = (
            card.select_one("a.listing-title")
            or card.select_one("h3 > a")
            or card.select_one("h2 > a")
            or card.select_one("a[href*='/Business-Opportunity/']")
            or card.select_one("a[href*='/business-for-sale/']")
        )
        if not title_tag:
            return None

        title = title_tag.get_text(strip=True)
        href  = title_tag.get("href", "")
        url   = href if href.startswith("http") else BASE_URL + href

        # Description
        desc_tag = (
            card.select_one("p.description")
            or card.select_one("div.description")
            or card.select_one("p[class*='desc']")
            or card.select_one("div[class*='desc']")
        )
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # Location
        loc_tag = (
            card.select_one("span.location")
            or card.select_one("div.location")
            or card.select_one("[class*='location']")
        )
        location = loc_tag.get_text(strip=True) if loc_tag else ""
        if not location:
            m = re.search(r"[A-Za-z ]+,\s*[A-Z]{2}", card.get_text())
            location = m.group(0).strip() if m else ""
        state = self.extract_state(location)

        # Industry
        cat_tag = (
            card.select_one("span.category")
            or card.select_one("div.category")
            or card.select_one("[class*='category']")
            or card.select_one("[class*='industry']")
        )
        industry = cat_tag.get_text(strip=True) if cat_tag else ""

        # Financials — scan every text-bearing element
        asking_price = ebitda = revenue = None
        for el in card.select("span, div, li, td, p"):
            text  = el.get_text(" ", strip=True)
            lower = text.lower()
            # Only parse leaf-ish nodes (short text)
            if len(text) > 80:
                continue
            val = self.parse_money(text)
            if val is None or val < 1_000:
                continue
            if "asking" in lower or ("price" in lower and "low" not in lower):
                asking_price = asking_price or val
            elif "cash flow" in lower or "ebitda" in lower or "sde" in lower:
                ebitda = ebitda or val
            elif "revenue" in lower or "gross" in lower or "sales" in lower:
                revenue = revenue or val

        # Also check data-attributes
        asking_price = asking_price or self.parse_money(
            card.get("data-price") or card.get("data-asking-price")
        )
        ebitda = ebitda or self.parse_money(
            card.get("data-cash-flow") or card.get("data-ebitda")
        )

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
            "source":       "BizBuySell",
            "url":          url,
        }
