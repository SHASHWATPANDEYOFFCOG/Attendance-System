"""Notifications: in-app rows, live push, and queued email.

`notify()` is the one entry point every feature uses. It writes an in-app notification per
recipient, pushes it to any open browser tab over SSE, and — for events that warrant it —
queues an email. Email is never sent inline: a slow SMTP server must not make "approve leave"
hang, so a background dispatcher drains the queue (see app/scheduler.py).

The caller owns the transaction: `notify()` adds rows and the caller commits them together with
the change that caused them, so a rolled-back approval never emails anybody.
"""
from __future__ import annotations

import json
from typing import Iterable, Optional, Sequence

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.bus import emit
from app.mailer import MailError, send_email
from app.models import Notification, User, utcnow
from occlubio.utils import get_logger

log = get_logger("app.notify")

INAPP = "inapp"
EMAIL = "email"
MAX_EMAIL_ATTEMPTS = 5


def notify(
    db: Session,
    user_ids: Iterable[int],
    kind: str,
    title: str,
    body: str = "",
    link: Optional[str] = None,
    email: bool = False,
    payload: Optional[dict] = None,
    email_to: Optional[Sequence[str]] = None,
    inapp: bool = True,
    sensitive: bool = False,
) -> int:
    """Queue a notification for each user. Returns how many in-app rows were added.

    `sensitive` (OTP codes, reset links): email only, and the body/link are wiped from the
    database the moment the message is handed to the mail server.
    """
    if sensitive:
        inapp = False
    ids = sorted({int(u) for u in user_ids if u is not None})
    data = json.dumps(payload or {}, default=str)
    n = 0
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    for uid in ids:
        u = users.get(uid)
        if u is None or u.deleted_at is not None:
            continue
        if inapp:
            db.add(Notification(user_id=uid, type=kind, payload=data, channel=INAPP,
                                title=title[:200], body=body, link=link))
            n += 1
            # Pushed to open tabs only once the transaction commits (see _flush_pushes); the
            # row is the durable copy if no tab is open.
            db.info.setdefault("pending_pushes", []).append(
                (uid, {"type": kind, "title": title, "body": body, "link": link}))
        if email and u.email:
            db.add(Notification(user_id=uid, type=kind, payload=json.dumps(
                {"to": u.email, "sensitive": sensitive, **(payload or {})}, default=str),
                channel=EMAIL, title=title[:200], body=body, link=link))
    for extra in email_to or ():
        if extra and ids:
            # e.g. a guardian's address: attach to the first recipient's row set for auditing.
            db.add(Notification(user_id=ids[0], type=kind, payload=json.dumps(
                {"to": extra, **(payload or {})}, default=str), channel=EMAIL,
                title=title[:200], body=body, link=link))
    return n


@event.listens_for(Session, "after_commit")
def _flush_pushes(session: Session) -> None:
    for uid, data in session.info.pop("pending_pushes", []):
        emit("notification", data, user_id=uid)


@event.listens_for(Session, "after_rollback")
def _drop_pushes(session: Session) -> None:
    session.info.pop("pending_pushes", None)


def _email_text(n: Notification, base_url: str, org: str) -> str:
    lines = [n.body or n.title or ""]
    if n.link:
        lines += ["", f"Open: {base_url.rstrip('/')}{n.link}"]
    lines += ["", f"— {org}", "This is an automated message from the attendance system."]
    return "\n".join(lines)


def dispatch_emails(db: Session, base_url: str, org: str, limit: int = 50) -> dict:
    """Send queued emails. Safe to call repeatedly; each row is attempted at most 5 times."""
    rows = list(db.scalars(
        select(Notification)
        .where(Notification.channel == EMAIL, Notification.sent_at.is_(None),
               Notification.attempts < MAX_EMAIL_ATTEMPTS)
        .order_by(Notification.created_at)
        .limit(limit)
    ))
    sent = failed = 0
    for n in rows:
        try:
            meta = json.loads(n.payload or "{}")
        except ValueError:
            meta = {}
        to = meta.get("to")
        n.attempts = (n.attempts or 0) + 1
        try:
            if not to:
                raise MailError("no recipient address")
            send_email(to, n.title or "Notification", _email_text(n, base_url, org), org=org)
            n.sent_at = utcnow()
            n.error = None
            if meta.get("sensitive"):
                n.body, n.link = "[delivered; content removed]", None
            sent += 1
        except MailError as exc:
            n.error = str(exc)[:300]
            failed += 1
            log.warning("email %d to %s failed (attempt %d): %s", n.id, to, n.attempts, exc)
        db.commit()
    return {"sent": sent, "failed": failed}
