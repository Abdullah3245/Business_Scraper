"""
Renders the daily digest as a clean HTML email.
"""

from __future__ import annotations
from datetime import date


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_money(value) -> str:
    if value is None:
        return "Not listed"
    try:
        v = float(value)
        if v >= 1_000_000:
            return f"${v / 1_000_000:.2f}M"
        if v >= 1_000:
            return f"${v / 1_000:.0f}K"
        return f"${v:,.0f}"
    except (TypeError, ValueError):
        return str(value) if value else "Not listed"


def _esc(s) -> str:
    """Minimal HTML escaping."""
    if not s:
        return "Not listed"
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _field_row(label: str, value: str) -> str:
    return f"""
        <tr>
          <td style="padding:3px 12px 3px 0;color:#6b7280;font-size:13px;white-space:nowrap;vertical-align:top;">{label}</td>
          <td style="padding:3px 0;font-size:13px;color:#111827;vertical-align:top;">{value}</td>
        </tr>"""


def _listing_card(listing: dict, idx: int) -> str:
    title       = _esc(listing.get("title") or "Untitled Listing")
    description = _esc(listing.get("description") or "No description available.")
    location    = _esc(listing.get("location") or listing.get("state") or "")
    industry    = _esc(listing.get("industry") or "")
    revenue     = _fmt_money(listing.get("revenue"))
    ebitda      = _fmt_money(listing.get("ebitda"))
    price       = _fmt_money(listing.get("asking_price"))
    source      = _esc(listing.get("source") or "")
    url         = listing.get("url") or "#"

    rows = "".join([
        _field_row("Location",    location or "Not listed"),
        _field_row("Industry",    industry or "Not listed"),
        _field_row("TTM Revenue", revenue),
        _field_row("EBITDA",      ebitda),
        _field_row("Asking Price",price),
        _field_row("Source",      source or "Not listed"),
    ])

    return f"""
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;
                padding:20px 24px;margin-bottom:16px;font-family:sans-serif;">
      <!-- Title -->
      <div style="font-size:17px;font-weight:700;color:#111827;margin-bottom:6px;">
        {idx}. {title}
      </div>
      <!-- Description -->
      <div style="font-size:14px;color:#374151;margin-bottom:14px;line-height:1.5;">
        {description}
      </div>
      <!-- Fields -->
      <table style="border-collapse:collapse;width:100%;">
        {rows}
      </table>
      <!-- CTA -->
      <div style="margin-top:14px;">
        <a href="{url}" style="display:inline-block;background:#1d4ed8;color:#ffffff;
           text-decoration:none;padding:7px 16px;border-radius:6px;font-size:13px;font-weight:600;">
          View Listing →
        </a>
      </div>
    </div>"""


def _error_banner(failed_sources: list[str]) -> str:
    if not failed_sources:
        return ""
    items = "".join(f"<li>{_esc(s)}</li>" for s in failed_sources)
    return f"""
    <div style="background:#fef2f2;border:1px solid #fca5a5;border-radius:8px;
                padding:12px 16px;margin-bottom:20px;font-family:sans-serif;">
      <strong style="color:#991b1b;">⚠ Scraper failures today:</strong>
      <ul style="margin:6px 0 0 0;padding-left:20px;color:#7f1d1d;font-size:13px;">
        {items}
      </ul>
    </div>"""


# ── Public API ────────────────────────────────────────────────────────────────

def render_email(
    listings: list[dict],
    total_scraped: int,
    failed_sources: list[str],
    run_date: date | None = None,
) -> tuple[str, str]:
    """
    Returns (subject_line, html_body).

    listings       — filtered, deduplicated listings to show
    total_scraped  — raw count before filtering
    failed_sources — list of source names whose scrapers errored
    """
    run_date = run_date or date.today()
    date_str = run_date.strftime("%B %-d, %Y")
    count    = len(listings)

    subject = f"Deal Digest — {date_str} — {count} new listing{'s' if count != 1 else ''}"

    if not listings:
        no_results = """
        <div style="text-align:center;padding:40px 0;color:#6b7280;font-family:sans-serif;">
          No listings matched your criteria today.
        </div>"""
        cards = no_results
    else:
        cards = "\n".join(_listing_card(l, i + 1) for i, l in enumerate(listings))

    error_html = _error_banner(failed_sources)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{_esc(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;">
  <div style="max-width:680px;margin:0 auto;padding:32px 16px;">

    <!-- Header -->
    <div style="background:#1d4ed8;border-radius:10px;padding:24px 28px;margin-bottom:24px;">
      <div style="color:#bfdbfe;font-size:12px;font-weight:600;letter-spacing:.08em;
                  text-transform:uppercase;margin-bottom:4px;">Daily Digest</div>
      <div style="color:#ffffff;font-size:24px;font-weight:800;margin-bottom:8px;">
        Deal Flow — {date_str}
      </div>
      <div style="color:#93c5fd;font-size:14px;">
        {total_scraped} listings scraped &nbsp;·&nbsp;
        <strong style="color:#ffffff;">{count}</strong> matched your criteria
        {(' &nbsp;·&nbsp; <span style="color:#fca5a5;">' + str(len(failed_sources)) + ' scraper failure' + ('s' if len(failed_sources) != 1 else '') + '</span>') if failed_sources else ''}
      </div>
    </div>

    <!-- Error banners -->
    {error_html}

    <!-- Listing cards -->
    {cards}

    <!-- Footer -->
    <div style="text-align:center;padding:24px 0 8px;color:#9ca3af;font-size:12px;
                font-family:sans-serif;">
      Filters: EBITDA $2M–$10M · US only · No franchises<br>
      Adjust filters in <code>config.yaml</code> · Unsubscribe: just turn off the script.
    </div>

  </div>
</body>
</html>"""

    return subject, html
