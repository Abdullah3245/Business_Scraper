#!/usr/bin/env python3
"""
Deal Digest — main orchestrator.

Usage:
    python main.py                  # run once immediately
    python main.py --schedule       # run on a daily schedule (7 AM PT)
    python main.py --dry-run        # scrape + filter but don't send email
    python main.py --test-email     # send a test email with dummy data
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import pytz
import schedule
import time
import yaml

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).parent / "data" / "digest.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# ── Local imports ──────────────────────────────────────────────────────────────

from core.dedup          import is_new, mark_all_sent
from core.filters        import apply_filters
from core.email_template import render_email
from core.email_sender   import send_digest

from scrapers.bizbuysell import BizBuySellScraper
from scrapers.bizquest   import BizQuestScraper
from scrapers.dealstream import DealStreamScraper
from scrapers.acquire    import AcquireScraper


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg_path = Path(__file__).parent / "config.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── Core run logic ─────────────────────────────────────────────────────────────

def run_digest(cfg: dict, dry_run: bool = False) -> None:
    logger.info("=" * 60)
    logger.info("Deal Digest starting — %s", datetime.now().isoformat())

    # Ensure data dir exists
    Path(__file__).parent.joinpath("data").mkdir(exist_ok=True)

    scrapers = [
        BizBuySellScraper(cfg),
        BizQuestScraper(cfg),
        DealStreamScraper(cfg),
        AcquireScraper(cfg),
    ]

    all_raw      : list[dict] = []
    failed_sources: list[str] = []

    # ── 1. Scrape ──────────────────────────────────────────────────────────
    for scraper in scrapers:
        listings, error = scraper.run()
        if error:
            failed_sources.append(f"{scraper.name}: {error}")
        all_raw.extend(listings)

    logger.info("Total raw listings: %d", len(all_raw))

    # ── 2. Filter ──────────────────────────────────────────────────────────
    passed, rejected = apply_filters(all_raw, cfg)
    logger.info("After filters: %d passed, %d rejected", len(passed), len(rejected))

    # ── 3. Deduplicate ─────────────────────────────────────────────────────
    new_listings = [l for l in passed if is_new(l)]
    logger.info("After dedup: %d new listings", len(new_listings))

    # ── 4. Render email ────────────────────────────────────────────────────
    subject, html = render_email(
        listings      = new_listings,
        total_scraped = len(all_raw),
        failed_sources= failed_sources,
        run_date      = date.today(),
    )

    # ── 5. Send (or dry-run) ───────────────────────────────────────────────
    if dry_run:
        preview_path = Path(__file__).parent / "data" / "preview.html"
        preview_path.write_text(html, encoding="utf-8")
        logger.info("DRY RUN — email not sent. Preview saved to %s", preview_path)
        logger.info("Subject would be: %s", subject)
    else:
        send_digest(subject, html, cfg)
        mark_all_sent(new_listings)
        logger.info("Digest sent and %d listings marked as seen.", len(new_listings))

    logger.info("Done.")


def run_test_email(cfg: dict) -> None:
    """Send a test email with one dummy listing to verify Gmail is wired up."""
    dummy = [{
        "title":        "Sample HVAC Services Company — Pacific Northwest",
        "description":  "Established commercial HVAC contractor with 15 employees "
                        "and strong recurring maintenance contracts. Owner retiring.",
        "location":     "Portland, OR",
        "state":        "OR",
        "country":      "US",
        "industry":     "HVAC / Construction Services",
        "revenue":      8_500_000,
        "ebitda":       2_800_000,
        "asking_price": 12_500_000,
        "source":       "Test",
        "url":          "https://example.com/listing/12345",
    }]
    subject, html = render_email(
        listings       = dummy,
        total_scraped  = 1,
        failed_sources = [],
        run_date       = date.today(),
    )
    subject = "[TEST] " + subject
    send_digest(subject, html, cfg)
    logger.info("Test email sent.")


# ── Scheduler ──────────────────────────────────────────────────────────────────

def schedule_daily(cfg: dict) -> None:
    send_hour   = cfg.get("email", {}).get("send_hour",   7)
    send_minute = cfg.get("email", {}).get("send_minute", 0)
    tz_name     = cfg.get("email", {}).get("timezone", "US/Pacific")
    tz          = pytz.timezone(tz_name)

    send_time = f"{send_hour:02d}:{send_minute:02d}"
    logger.info("Scheduler armed: daily at %s %s", send_time, tz_name)

    def _job():
        # Confirm we're actually in the right timezone window
        now_local = datetime.now(tz)
        logger.info("Scheduler fired at %s %s", now_local.strftime("%H:%M"), tz_name)
        run_digest(cfg)

    schedule.every().day.at(send_time).do(_job)

    while True:
        schedule.run_pending()
        time.sleep(30)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Deal Digest — daily business listings email")
    parser.add_argument("--schedule",   action="store_true", help="Run on a daily cron-like schedule")
    parser.add_argument("--dry-run",    action="store_true", help="Scrape and filter but don't send email")
    parser.add_argument("--test-email", action="store_true", help="Send a test email to verify Gmail config")
    args = parser.parse_args()

    cfg = load_config()

    if args.test_email:
        run_test_email(cfg)
    elif args.schedule:
        schedule_daily(cfg)
    else:
        run_digest(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
