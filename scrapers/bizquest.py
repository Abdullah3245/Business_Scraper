"""
BizQuest scraper — bizquest.com
Uses Playwright to bypass bot detection.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, ScraperError

logger = logging.getLogger(__name__)

BASE_URL  = "https://www.bizquest.com"
MAX_PAGES = 5


class BizQuestScraper(BaseScraper):
    name = "bizquest"

    def fetch(self) -> list[dict]:
        cfg_params = self.source_cfg.get("params", {})
        price_min  = int(cfg_params.get("AskingPriceMin", 5_000_000))
        price_max  = int(cfg_params.get("AskingPriceMax", 100_000_000))

        def url_fn(page_num: int) -> str:
            return (
                f"{BASE_URL}/business-for-sale/"
                f"?AskingPriceMin={price_min}"
                f"&AskingPriceMax={price_max}"
                f"&Page={page_num}"
            )

        pages_html = self.fetch_html_pages(url_fn, max_pages=MAX_PAGES)

        listings = []
        for html in pages_html:
            page_listings = self._parse_page(html)
            listings.extend(page_listings)
            if len(page_listings) < 10:
                break

        if not listings:
            raise ScraperError("bizquest: no listings found — selectors may need updating")

        return listings

    def _parse_page(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        cards = (
            soup.select("div.listing")
            or soup.select("div[class*='listing-item']")
            or soup.select("div[class*='result-item']")
            or soup.select("div[class*='business-listing']")
            or soup.select("li[class*='listing']")
        )

        logger.debug("bizquest: found %d cards on page", len(cards))

        for card in cards:
            try:
                listing = self._parse_card(card)
                if listing:
                    results.append(listing)
            except Exception as exc:
                logger.debug("bizquest: card parse error — %s", exc)

        return results

    def _parse_card(self, card) -> dict | None:
        title_tag = (
            card.select_one("a.listing-title")
            or card.select_one("h3 > a")
            or card.select_one("h2 > a")
            or card.select_one("a[href*='/biz/']")
            or card.select_one("a[href*='/business-for-sale/']")
        )
        if not title_tag:
            return None

        title = title_tag.get_text(strip=True)
        href  = title_tag.get("href", "")
        url   = href if href.startswith("http") else BASE_URL + href

        desc_tag = (
            card.select_one("p.desc")
            or card.select_one("p.description")
            or card.select_one("div.description")
            or card.select_one("div[class*='desc']")
        )
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        loc_tag = (
            card.select_one("span.location")
            or card.select_one("div.location")
            or card.select_one("span[class*='loc']")
            or card.select_one("div[class*='location']")
        )
        if loc_tag:
            location = loc_tag.get_text(strip=True)
        else:
            m = re.search(r"[A-Za-z ]+,\s*[A-Z]{2}", card.get_text())
            location = m.group(0).strip() if m else ""
        state = self.extract_state(location)

        cat_tag = (
            card.select_one("span.category")
            or card.select_one("div.category")
            or card.select_one("[class*='category']")
            or card.select_one("[class*='industry']")
        )
        industry = cat_tag.get_text(strip=True) if cat_tag else ""

        asking_price = ebitda = revenue = None
        for el in card.select("span, div, li, td, p"):
            text  = el.get_text(" ", strip=True)
            lower = text.lower()
            if len(text) > 80:
                continue
            val = self.parse_money(text)
            if val is None or val < 1_000:
                continue
            if "asking" in lower or "price" in lower:
                asking_price = asking_price or val
            elif "cash flow" in lower or "sde" in lower or "ebitda" in lower:
                ebitda = ebitda or val
            elif "revenue" in lower or "gross" in lower or "sales" in lower:
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
            "source":       "BizQuest",
            "url":          url,
        }
