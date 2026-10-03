"""Outgoing email over SMTP.

Configuration comes only from the environment (never the database), so credentials are not
readable through the admin UI:

    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM ("Attendance <noreply@college.edu>"), SMTP_SECURITY (starttls | ssl | none)

Without SMTP_HOST the message is written to `var/outbox/*.eml` instead and the system-status
panel says mail is not being delivered. That is a development convenience, not a silent
failure: nothing claims an email was sent when it was not.
"""
from __future__ import annotations

import os
import smtplib
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path
from typing import Optional

from occlubio.utils import get_logger

log = get_logger("app.mailer")


def outbox_dir() -> Path:
    return Path(os.environ.get("ATTENDANCE_OUTBOX", "var/outbox"))


def smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def delivery_mode() -> str:
    return "smtp" if smtp_configured() else "outbox"


class MailError(RuntimeError):
    pass


def build_message(to: str, subject: str, text: str, html: Optional[str] = None,
                  org: str = "Attendance Register") -> EmailMessage:
    msg = EmailMessage()
    sender = os.environ.get("SMTP_FROM") or formataddr((org, "noreply@localhost"))
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="attendance.local")
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def send_email(to: str, subject: str, text: str, html: Optional[str] = None,
               org: str = "Attendance Register") -> str:
    """Send one message. Returns "smtp" or the outbox path. Raises MailError on SMTP failure."""
    if not to or "@" not in to:
        raise MailError(f"invalid recipient {to!r}")
    msg = build_message(to, subject, text, html, org)

    if not smtp_configured():
        folder = outbox_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S-%f}-{uuid.uuid4().hex[:6]}.eml"
        path.write_bytes(bytes(msg))
        log.info("SMTP not configured; wrote email to %s (to=%s, subject=%r)", path, to, subject)
        return str(path)

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    security = os.environ.get("SMTP_SECURITY", "starttls").lower()
    try:
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20,
                                                   context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if user:
                server.login(user, password or "")
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"{type(exc).__name__}: {exc}") from exc
    return "smtp"
