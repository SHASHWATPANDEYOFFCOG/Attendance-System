"""Weekly attendance summary email (opt-in in Settings).

Sent once per week on Monday morning (local time) to every approved student, and to their
guardian when a guardian email is on file. Idempotent: the last sent week is recorded in the
settings table, so a restart or a second scheduler tick in the same window sends nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_service
from app.clock import tz_of, zone
from app.models import Setting, StudentProfile, User, utcnow
from app.notify import notify
from occlubio.utils import get_logger

log = get_logger("app.digest")

_KEY = "weekly_summary_last_week"


def _week_key(now_local: datetime) -> str:
    y, w, _ = now_local.isocalendar()
    return f"{y}-W{w:02d}"


def run(db: Session, cfg, now: Optional[datetime] = None, force: bool = False) -> int:
    s = settings_service.all_settings(db, cfg)
    if not s["weekly_summary_enabled"] and not force:
        return 0
    local = (now or utcnow()).astimezone(zone(tz_of(cfg)))
    if not force and not (local.weekday() == 0 and 8 <= local.hour < 12):
        return 0
    key = _week_key(local)
    row = db.scalars(select(Setting).where(Setting.key == _KEY)).first()
    if row is not None and row.value == key and not force:
        return 0

    from app.session_service import overall_pct
    from app.analytics_service import _classes_needed

    threshold = float(s["min_attendance_pct"])
    sent = 0
    students = db.execute(
        select(User, StudentProfile).join(StudentProfile, StudentProfile.user_id == User.id)
        .where(StudentProfile.status == "approved", User.deleted_at.is_(None),
               User.is_active.is_(True))).all()
    for user, prof in students:
        present, counted = overall_pct(db, user.id)
        if counted == 0:
            continue
        pct = 100.0 * present / counted
        need = _classes_needed(present, counted, threshold)
        line = (f"Attendance so far: {pct:.1f}% ({present} of {counted} classes). "
                + (f"You are below the {threshold:g}% minimum: attend the next {need} class(es) "
                   f"in a row to recover." if pct < threshold else
                   f"You are above the {threshold:g}% minimum."))
        notify(db, [user.id], "weekly_summary", "Your weekly attendance summary", line,
               link="/student", email=True,
               email_to=[prof.guardian_email] if prof.guardian_email else None, inapp=False)
        sent += 1
    if row is None:
        db.add(Setting(key=_KEY, value=key))
    else:
        row.value = key
    db.commit()
    log.info("weekly summary queued for %d student(s) (%s)", sent, key)
    return sent
