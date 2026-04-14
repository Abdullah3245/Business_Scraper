"""
Sends the HTML digest via Gmail SMTP using an App Password.

Setup:
  1. Enable 2-Step Verification on the Gmail account.
  2. Go to Google Account → Security → App Passwords.
  3. Create a password for "Mail" / "Other device".
  4. Paste the 16-char password into config.yaml → email.app_password.
"""

from __future__ import annotations

import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_digest(
    subject: str,
    html_body: str,
    cfg: dict,
) -> None:
    """
    Send the HTML email.

    cfg must contain:
        email.sender       — the Gmail address used to send
        email.app_password — Gmail App Password
        email.recipient    — destination address
    """
    email_cfg = cfg.get("email", {})
    sender     = email_cfg["sender"]
    password   = email_cfg["app_password"]
    recipient  = email_cfg["recipient"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Deal Digest <{sender}>"
    msg["To"]      = recipient

    # Plain-text fallback (brief)
    plain = (
        f"{subject}\n\n"
        "Open this email in an HTML-capable client to view the full digest.\n"
    )
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    logger.info("Connecting to Gmail SMTP…")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, recipient, msg.as_string())
    logger.info("Email sent → %s", recipient)
