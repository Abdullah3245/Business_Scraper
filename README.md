# Deal Digest

Automated daily email of businesses for sale that match your acquisition criteria.

## Setup

### 1. Install dependencies

```bash
cd mustafa_challenge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed for Acquire.com
```

### 2. Configure Gmail App Password

1. Enable 2-Step Verification on your Gmail account
2. Go to **Google Account → Security → App Passwords**
3. Create a password for "Mail / Other device"
4. Copy the 16-character password

### 3. Edit config.yaml

```yaml
email:
  sender: "deal-digest-sender@gmail.com"   # the Gmail that sends
  app_password: "abcd efgh ijkl mnop"      # paste App Password here
  recipient: "you@youremail.com"           # where you receive it
```

Adjust your filters there too — EBITDA range, state list, excluded industries.

### 4. Test the email pipeline

```bash
python main.py --test-email
```

You should receive one sample listing card in your inbox.

### 5. Dry-run (no email, saves HTML preview)

```bash
python main.py --dry-run
# open data/preview.html in a browser to see what the email would look like
```

### 6. Run once manually

```bash
python main.py
```

### 7. Schedule (runs at 7 AM PT every day, process must stay alive)

```bash
python main.py --schedule
```

For unattended deployment, use a process manager like `pm2` or `systemd`,
or see the **Deployment** section below.

---

## Deployment options

### Option A — Mac launchd (simplest, runs while your Mac is on)

Create `~/Library/LaunchAgents/com.dealdigest.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dealdigest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/.venv/bin/python</string>
    <string>/path/to/mustafa_challenge/main.py</string>
    <string>--schedule</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/dealdigest.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/dealdigest.err</string>
</dict>
</plist>
```

Then: `launchctl load ~/Library/LaunchAgents/com.dealdigest.plist`

### Option B — Railway.app (cloud, always on, free tier)

1. Push this repo to GitHub
2. Create a new project on railway.app → Deploy from GitHub
3. Set start command: `python main.py --schedule`
4. No extra config needed — Railway keeps the process alive

### Option C — Linux cron

```cron
0 7 * * * /path/to/.venv/bin/python /path/to/mustafa_challenge/main.py >> /var/log/dealdigest.log 2>&1
```

---

## Project structure

```
mustafa_challenge/
├── config.yaml          ← all filters and credentials (edit this)
├── main.py              ← entry point
├── requirements.txt
├── core/
│   ├── dedup.py         ← SQLite deduplication
│   ├── filters.py       ← EBITDA / price / franchise / geo filters
│   ├── email_template.py← HTML email renderer
│   └── email_sender.py  ← Gmail SMTP
├── scrapers/
│   ├── base.py          ← shared session, retry, helpers
│   ├── bizbuysell.py    ← BizBuySell
│   ├── bizquest.py      ← BizQuest
│   ├── dealstream.py    ← DealStream
│   └── acquire.py       ← Acquire.com (tries JSON API, falls back to Playwright)
└── data/
    ├── seen_listings.db ← dedup store (auto-created)
    ├── digest.log       ← run log (auto-created)
    └── preview.html     ← last dry-run preview (auto-created)
```

## Scraper notes

| Source | Method | Notes |
|---|---|---|
| BizBuySell | requests + BS4 | Server-rendered, works with browser headers |
| BizQuest | requests + BS4 | Server-rendered |
| DealStream | requests + BS4 | Server-rendered |
| Acquire.com | JSON API → Playwright | SPA; tries internal API first, falls back to headless Chrome |

If a scraper fails one day, it's noted at the top of that day's email and the others continue.

## Tier 2 (future)

Once Tier 1 is stable, add scrapers for:
- Quiet Light (quietlight.com)
- Murphy Business (murphybusiness.com)
- Transworld Business Advisors (tworld.com)
