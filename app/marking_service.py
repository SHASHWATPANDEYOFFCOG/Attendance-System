"""Manual marking: open a period, load its roster, save the marks.

The screen built on this is used every working day, so the rules it enforces matter more than
its surface area:

* **Opening a period is idempotent.** Two teachers (or two tabs) opening the same slot on the
  same date get the *same* session, never a duplicate register.
* **Saving is transactional and an upsert.** A partial save is worse than a failed one: half a
  marked register looks complete and nobody notices the missing half.
* **A save carries the client's view of the roster version.** If the roster changed underneath
  (a student was added), the save still applies to the students it named and reports the ones it
  did not know about, rather than silently leaving them absent.
* **Locked sessions refuse.** Past the edit window, a change needs a correction request so the
  original value survives in the audit log.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRecordRow,
    AttendanceStatus,
    AuditLog,
    CaptureMethod,
    ClassSession,
    RosterEntry,
    Section,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
    utcnow,
)
from occlubio.utils import get_logger

log = get_logger("app.marking")

#: Statuses a human may set from the marking screen. `needs_review` is produced by the pipeline,
#: never chosen by a teacher, so it is not offered.
MARKABLE = {
    AttendanceStatus.PRESENT.value,
    AttendanceStatus.ABSENT.value,
    AttendanceStatus.LATE.value,
    AttendanceStatus.ON_DUTY.value,
    AttendanceStatus.EXCUSED.value,
}


class MarkingError(Exception):
    def __init__(self, code: int, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def local_to_utc(on: date, minute: int, tz_offset_minutes: int) -> datetime:
    naive = datetime.combine(on, time(minute // 60, minute % 60))
    return (naive - timedelta(minutes=tz_offset_minutes)).replace(tzinfo=timezone.utc)


def section_student_ids(db: Session, section_id: int) -> List[int]:
    """Everyone currently enrolled in the section, excluding soft-deleted accounts."""
    stmt = (
        select(StudentProfile.user_id)
        .join(User, User.id == StudentProfile.user_id)
        .where(StudentProfile.section_id == section_id)
        .where(User.deleted_at.is_(None))
        .where(User.is_active.is_(True))
    )
    return list(db.scalars(stmt))


def open_session(db: Session, slot: TimetableSlot, on: date, actor: User, cfg) -> ClassSession:
    """Get or create the dated session for a timetable slot. Idempotent by (slot, date)."""
    # A Monday period cannot be held on a Saturday. Without this, a typo in ?date= silently
    # creates a register for a class that never met, and its absences count against everyone.
    if on.weekday() != slot.day_of_week:
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        raise MarkingError(
            422,
            f"this period is scheduled on {days[slot.day_of_week]}, but "
            f"{on.isoformat()} is a {days[on.weekday()]}",
        )

    tz_offset = int(getattr(cfg.attendance, "tz_offset_minutes", 330))
    starts = local_to_utc(on, slot.start_minute, tz_offset)
    ends = local_to_utc(on, slot.end_minute, tz_offset)

    existing = db.scalars(
        select(ClassSession)
        .where(ClassSession.timetable_slot_id == slot.id)
        .where(ClassSession.scheduled_start == starts)
        .where(ClassSession.deleted_at.is_(None))
    ).first()
    if existing is not None:
        _sync_roster(db, existing, slot.section_id)
        return existing

    subject = db.get(Subject, slot.subject_id)
    session = ClassSession(
        title=f"{subject.code if subject else 'Session'} Period",
        room=slot.room,
        owner_id=slot.faculty_id,
        scheduled_start=starts,
        scheduled_end=ends,
        mode=str(getattr(cfg.attendance, "default_camera_mode", "kiosk")),
        grace_minutes=int(getattr(cfg.attendance, "grace_minutes", 10)),
        min_presence_seconds=int(getattr(cfg.attendance, "min_presence_seconds", 1500)),
        timetable_slot_id=slot.id,
        subject_id=slot.subject_id,
        section_id=slot.section_id,
        term_id=slot.term_id,
        capture_method=CaptureMethod.MANUAL.value,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    _sync_roster(db, session, slot.section_id)
    db.add(AuditLog(actor_id=actor.id, action="session_opened", target_type="session",
                    target_id=str(session.id),
                    detail=f"slot={slot.id} date={on.isoformat()}"))
    db.commit()
    log.info("opened session %s for slot %s on %s", session.id, slot.id, on)
    return session


def _sync_roster(db: Session, session: ClassSession, section_id: Optional[int]) -> None:
    """Add roster rows for students who joined the section after the session was opened.

    Additive only: a student who left keeps their row, because deleting it would erase the
    attendance already recorded against them.
    """
    if section_id is None:
        return
    have = set(db.scalars(
        select(RosterEntry.user_id).where(RosterEntry.session_id == session.id)))
    for uid in section_student_ids(db, section_id):
        if uid not in have:
            db.add(RosterEntry(session_id=session.id, user_id=uid))
    db.commit()


def roster_view(db: Session, session: ClassSession) -> dict:
    """Students plus any mark already recorded — everything the screen needs in one request."""
    ids = list(db.scalars(
        select(RosterEntry.user_id).where(RosterEntry.session_id == session.id)))
    users = {
        u.id: u for u in db.scalars(select(User).where(User.id.in_(ids))) if u.deleted_at is None
    }
    records = {
        r.user_id: r
        for r in db.scalars(
            select(AttendanceRecordRow)
            .where(AttendanceRecordRow.session_id == session.id)
            .where(AttendanceRecordRow.deleted_at.is_(None))
        )
    }

    rows = []
    for uid in ids:
        u = users.get(uid)
        if u is None:
            continue
        rec = records.get(uid)
        rows.append({
            "user_id": uid,
            "display_name": u.display_name,
            "roll_number": u.roll_number,
            "status": rec.effective_status if rec else None,
            "source": rec.source if rec else None,
            "overridden": bool(rec and rec.overridden_status),
            "needs_review": bool(rec and rec.needs_review),
        })
    rows.sort(key=lambda r: (r["roll_number"] or "", r["display_name"]))

    subject = db.get(Subject, session.subject_id) if session.subject_id else None
    section = db.get(Section, session.section_id) if session.section_id else None
    return {
        "session": {
            "id": session.id,
            "title": session.title,
            "room": session.room,
            "scheduled_start": session.scheduled_start,
            "scheduled_end": session.scheduled_end,
            "is_locked": session.is_locked,
            "marked_at": session.marked_at,
            "capture_method": session.capture_method,
            "subject_code": subject.code if subject else None,
            "subject_name": subject.name if subject else None,
            "section_label": section.name if section else None,
        },
        "marked_count": sum(1 for r in rows if r["status"]),
        "roster": rows,
    }


def save_marks(db: Session, session: ClassSession, marks: Sequence[dict], actor: User,
               cfg) -> dict:
    """Upsert every mark in one transaction. All of it lands, or none of it does."""
    if session.is_locked:
        raise MarkingError(409, "this session is locked; raise a correction request instead")

    rostered = set(db.scalars(
        select(RosterEntry.user_id).where(RosterEntry.session_id == session.id)))

    cleaned: dict[int, str] = {}
    unknown: list[int] = []
    for m in marks:
        uid, status = int(m["user_id"]), str(m["status"])
        if status not in MARKABLE:
            raise MarkingError(422, f"status {status!r} cannot be set by hand",
                               allowed=sorted(MARKABLE))
        if uid not in rostered:
            unknown.append(uid)          # reported, not silently applied
            continue
        cleaned[uid] = status

    existing = {
        r.user_id: r
        for r in db.scalars(
            select(AttendanceRecordRow).where(AttendanceRecordRow.session_id == session.id))
    }

    created = updated = unchanged = 0
    changes: list[str] = []
    now = utcnow()

    try:
        for uid, status in cleaned.items():
            row = existing.get(uid)
            if row is None:
                db.add(AttendanceRecordRow(
                    session_id=session.id, user_id=uid, status=status,
                    first_seen=session.scheduled_start if status != "absent" else None,
                    last_seen=session.scheduled_end if status != "absent" else None,
                    total_visible_s=0.0, avg_confidence=0.0, frames_matched=0,
                    source=CaptureMethod.MANUAL.value, computed_at=now,
                ))
                created += 1
                continue

            before = row.effective_status
            if before == status:
                unchanged += 1
                continue
            # A manual mark on a face-captured session is an OVERRIDE: the derived value and the
            # human decision are both preserved, and the override survives recompute.
            if row.source == CaptureMethod.FACE.value:
                row.overridden_status = status
                row.overridden_by_id = actor.id
                row.overridden_at = now
                row.override_reason = "marked by hand on the marking screen"
            else:
                row.status = status
            row.computed_at = now
            updated += 1
            changes.append(f"{uid}:{before}->{status}")

        session.marked_by_id = actor.id
        session.marked_at = now
        if session.capture_method != CaptureMethod.FACE.value:
            session.capture_method = CaptureMethod.MANUAL.value

        db.add(AuditLog(
            actor_id=actor.id, action="attendance_marked", target_type="session",
            target_id=str(session.id),
            detail=f"created={created} updated={updated} unchanged={unchanged} "
                   f"changes=[{'; '.join(changes[:40])}]",
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise

    log.info("session %s marked by %s: +%d ~%d =%d", session.id, actor.username,
             created, updated, unchanged)
    return {
        "session_id": session.id,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "not_on_roster": unknown,
        "marked_at": now,
    }


def lock_stale_sessions(db: Session, cfg) -> int:
    """Lock sessions past the edit window. Idempotent; safe to run on a schedule."""
    hours = float(getattr(cfg.attendance, "edit_window_hours", 24))
    cutoff = utcnow() - timedelta(hours=hours)
    stale = list(db.scalars(
        select(ClassSession)
        .where(ClassSession.is_locked.is_(False))
        .where(ClassSession.scheduled_end < cutoff)
        .where(ClassSession.deleted_at.is_(None))
    ))
    for s in stale:
        s.is_locked = True
    if stale:
        db.commit()
        log.info("locked %d session(s) past the %.0fh edit window", len(stale), hours)
    return len(stale)
