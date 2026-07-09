"""
Outbound email — currently just magic sign-in links.

Config comes from the environment so the repo stays secret-free:
  ZOLPO_SMTP_HOST / ZOLPO_SMTP_PORT / ZOLPO_SMTP_USER / ZOLPO_SMTP_PASS
  ZOLPO_SMTP_FROM  – sender address (defaults to the SMTP user)
  ZOLPO_BASE_URL   – public origin used inside links (default local dev)

Without ZOLPO_SMTP_HOST nothing is sent: send_magic_link returns False and
the API logs the link instead (dev mode; the link is also surfaced to
localhost clients only).
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = os.environ.get("ZOLPO_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("ZOLPO_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ZOLPO_SMTP_USER", "")
SMTP_PASS = os.environ.get("ZOLPO_SMTP_PASS", "")
SMTP_FROM = os.environ.get("ZOLPO_SMTP_FROM", SMTP_USER or "zolpo@localhost")
BASE_URL = os.environ.get("ZOLPO_BASE_URL", "http://127.0.0.1:8020").rstrip("/")


def configured() -> bool:
    return bool(SMTP_HOST)


def send_magic_link(email: str, url: str) -> bool:
    """Mail a one-time sign-in link. False when SMTP isn't configured."""
    if not configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = "ZolPo — קישור כניסה / Your sign-in link"
    msg["From"] = SMTP_FROM
    msg["To"] = email
    msg.set_content(
        "Sign in to ZolPo (the link works once, for 15 minutes):\n\n"
        f"{url}\n\n"
        "If you didn't request this, just ignore the email.\n\n"
        f"כניסה ל-ZolPo (הקישור חד-פעמי, תקף ל-15 דקות):\n{url}\n"
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
        smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASS)
        smtp.send_message(msg)
    return True
