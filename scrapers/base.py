"""
Base scraper class.

All scrapers use Playwright (headless Chromium) to bypass bot detection.
Playwright is shared via a module-level browser instance to avoid spawning
a new process for each scraper.
"""

from __future__ import annotations

import logging
import random
import re
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
]


class ScraperError(Exception):
    pass


class BaseScraper(ABC):
    """
    Subclass must implement fetch() and return a list of listing dicts.

    Listing schema (all optional except url):
    {
        "title":        str,
        "description":  str,
        "location":     str,
        "state":        str,
        "country":      str,
        "industry":     str,
        "revenue":      float | None,
        "ebitda":       float | None,
        "asking_price": float | None,
        "source":       str,
        "url":          str,
    }
    """

    name: str = "base"

    def __init__(self, cfg: dict):
        self.cfg        = cfg
        self.source_cfg = cfg.get("sources", {}).get(self.name, {})

    # ── Playwright helper ─────────────────────────────────────────────────

    def fetch_html(self, url: str, wait: int = 3000, scroll: bool = False) -> str:
        """
        Render a URL with headless Chromium and return the full page HTML.
        wait  — ms to wait after page load for JS to settle
        scroll — scroll to bottom to trigger lazy-load / infinite scroll
        """
        from playwright.sync_api import sync_playwright

        ua = random.choice(_USER_AGENTS)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()

            # Block heavy assets to speed up scraping
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webp}",
                       lambda r: r.abort())

            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(wait)

            if scroll:
                for _ in range(3):
                    page.keyboard.press("End")
                    page.wait_for_timeout(1500)

            html = page.content()
            browser.close()

        return html

    def fetch_html_pages(self, url_fn, max_pages: int = 5, wait: int = 3000) -> list[str]:
        """
        Fetch multiple pages using a URL factory: url_fn(page_number) -> url.
        Returns list of HTML strings, stops early on empty results.
        """
        from playwright.sync_api import sync_playwright

        ua = random.choice(_USER_AGENTS)
        pages_html = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=ua,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,mp4,webp}",
                       lambda r: r.abort())

            for page_num in range(1, max_pages + 1):
                url = url_fn(page_num)
                logger.info("%s: fetching page %d → %s", self.name, page_num, url)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(wait)
                    html = page.content()
                    pages_html.append(html)
                    time.sleep(random.uniform(1.5, 3.0))
                except Exception as e:
                    logger.warning("%s: page %d failed — %s", self.name, page_num, e)
                    break

            browser.close()

        return pages_html

    # ── Abstract ──────────────────────────────────────────────────────────

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Return a list of raw listing dicts (unfiltered)."""

    # ── Public entry point ────────────────────────────────────────────────

    def run(self) -> tuple[list[dict], str | None]:
        if not self.source_cfg.get("enabled", True):
            logger.info("%s: disabled in config, skipping", self.name)
            return [], None
        try:
            logger.info("%s: starting scrape…", self.name)
            listings = self.fetch()
            logger.info("%s: found %d raw listings", self.name, len(listings))
            return listings, None
        except ScraperError as e:
            logger.error("%s: %s", self.name, e)
            return [], str(e)
        except Exception as e:
            logger.exception("%s: unexpected error", self.name)
            return [], f"{self.name}: unexpected error — {e}"

    # ── Shared parsing helpers ────────────────────────────────────────────

    @staticmethod
    def parse_money(text: str | None) -> float | None:
        if not text:
            return None
        s = re.sub(r"[^\d\.KMBkmb]", "", str(text).strip())
        if not s:
            return None
        mult = 1
        if s.upper().endswith("M"):
            mult = 1_000_000; s = s[:-1]
        elif s.upper().endswith("K"):
            mult = 1_000; s = s[:-1]
        elif s.upper().endswith("B"):
            mult = 1_000_000_000; s = s[:-1]
        try:
            return float(s) * mult
        except ValueError:
            return None

    @staticmethod
    def extract_state(location: str | None) -> str:
        if not location:
            return ""
        m = re.search(r"\b([A-Z]{2})\b", location.upper())
        return m.group(1) if m else ""
