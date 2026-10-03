"""Session lifecycle and the one write path every automatic mark goes through.

    scheduled --start--> active --close--> closed

* **start** (scheduler at the timetable start time, or a teacher manually): roster synced,
  a fresh secret for the rotating classroom code.
* **mark** (`record_mark`): CCTV, mobile selfie and QR all land here. One row per student per
  session is guaranteed by the `uq_record_session_user` constraint, so a double-tap, two tabs or
  a CCTV match racing a selfie can never produce two records — the loser gets "already marked".
* **close** (scheduler at the end time, or a teacher): every rostered, approved student without a
  record becomes ABSENT, or ON LEAVE when an approved leave covers the lecture. Below-minimum
  alerts are evaluated for the class.

Present / late / too-late is decided by `window_status` from the admin's time windows, in one
place, so CCTV and a selfie taken at the same minute can never disagree.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, List, Optional, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import settings_service
from app.audit import audit
from app.bus import emit
from app.clock import tz_of, zone
from app.models import (
    AttendanceRecordRow,
    AttendanceStatus,
    CaptureMethod,
    ClassSession,
    LeaveRequest,
    LeaveStatus,
    RosterEntry,
    SessionState,
    StudentProfile,
    StudentStatus,
    Subject,
    User,
    utcnow,
)
from app.notify import notify
from app.session_code import new_secret
from occlubio.utils import get_logger

log = get_logger("app.sessions")


class SessionError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------ helpers

def session_local_date(session: ClassSession, cfg) -> date:
    return session.scheduled_start.astimezone(zone(tz_of(cfg))).date()


def local_dt(on: date, minute: int, cfg) -> datetime:
    """A local wall-clock time on a date, as an aware UTC instant (DST-correct via zoneinfo)."""
    naive = datetime.combine(on, time(minute // 60, minute % 60))
    return naive.replace(tzinfo=zone(tz_of(cfg))).astimezone(timezone.utc)


def subject_label(db: Session, session: ClassSession) -> str:
    subj = db.get(Subject, session.subject_id) if session.subject_id else None
    return subj.code if subj else session.title


def approved_roster(db: Session, session: ClassSession) -> List[int]:
    """Rostered students who may be marked: approved, active, not deleted.

    Staff or legacy accounts on a hand-built roster have no profile and are kept, as before.
    """
    ids = list(db.scalars(select(RosterEntry.user_id).where(RosterEntry.session_id == session.id)))
    if not ids:
        return []
    blocked = set(db.scalars(select(StudentProfile.user_id).where(
        StudentProfile.user_id.in_(ids), StudentProfile.status != StudentStatus.APPROVED.value)))
    gone = set(db.scalars(select(User.id).where(User.id.in_(ids), or_(
        User.deleted_at.is_not(None), User.is_active.is_(False)))))
    return [i for i in ids if i not in blocked and i not in gone]


def window_status(session: ClassSession, at: datetime, db: Session, cfg) -> Optional[str]:
    """present | late | None (outside the window). Measured from the scheduled start."""
    s = settings_service.all_settings(db, cfg)
    if at > session.scheduled_end:
        return None
    minutes = (at - session.scheduled_start).total_seconds() / 60.0
    if minutes <= float(s["present_window_min"]):
        return AttendanceStatus.PRESENT.value
    if minutes <= float(s["late_window_min"]):
        return AttendanceStatus.LATE.value
    return None


# ---------------------------------------------------------------- lifecycle

def sync_roster(db: Session, session: ClassSession) -> None:
    if session.section_id is None:
        return
    from app.marking_service import _sync_roster

    _sync_roster(db, session, session.section_id)


def start_session(db: Session, session: ClassSession, cfg, actor: Optional[User] = None) -> ClassSession:
    if session.deleted_at is not None:
        raise SessionError(404, "session not found")
    if session.state == SessionState.CLOSED.value:
        raise SessionError(409, "This session has already closed.")
    if session.state == SessionState.ACTIVE.value:
        return session
    if utcnow() > session.scheduled_end:
        raise SessionError(409, "This lecture's time is over; it can no longer be started.")
    sync_roster(db, session)
    session.state = SessionState.ACTIVE.value
    session.started_at = utcnow()
    session.started_by_id = actor.id if actor else None
    session.code_secret = session.code_secret or new_secret()
    audit(db, actor, "session_started", target_type="session", target_id=session.id,
          detail={"auto": actor is None})
    db.commit()
    emit("session_state", {"state": "active", "session_id": session.id}, session_id=session.id)
    log.info("session %d started (%s)", session.id, "auto" if actor is None else actor.username)
    return session


def covering_leave(db: Session, user_id: int, session: ClassSession, cfg) -> Optional[LeaveRequest]:
    on = session_local_date(session, cfg)
    for leave in db.scalars(select(LeaveRequest).where(
            LeaveRequest.requester_id == user_id,
            LeaveRequest.status == LeaveStatus.APPROVED.value,
            LeaveRequest.from_date <= on, LeaveRequest.to_date >= on)):
        if leave.session_ids:
            try:
                if session.id in set(json.loads(leave.session_ids)):
                    return leave
            except ValueError:
                continue
        else:
            return leave
    return None


def close_session(db: Session, session: ClassSession, cfg, actor: Optional[User] = None) -> dict:
    """Close and fill. Idempotent: closing a closed session changes nothing."""
    if session.state == SessionState.CLOSED.value:
        return {"session_id": session.id, "already_closed": True}
    if session.capture_method == CaptureMethod.FACE.value:
        from app.attendance_service import recompute_session

        recompute_session(db, session, cfg, actor)          # derived rows first, marks preserved
    sync_roster(db, session)

    roster = approved_roster(db, session)
    have = set(db.scalars(select(AttendanceRecordRow.user_id).where(
        AttendanceRecordRow.session_id == session.id)))
    now = utcnow()
    absent: List[int] = []
    on_leave: List[int] = []
    for uid in roster:
        if uid in have:
            continue
        leave = covering_leave(db, uid, session, cfg)
        status = AttendanceStatus.ON_LEAVE.value if leave else AttendanceStatus.ABSENT.value
        db.add(AttendanceRecordRow(
            session_id=session.id, user_id=uid, status=status, source=CaptureMethod.SYSTEM.value,
            leave_request_id=leave.id if leave else None, computed_at=now, marked_at=now,
            evidence="not marked when the session closed" if not leave
            else f"covered by approved leave #{leave.id}"))
        (on_leave if leave else absent).append(uid)

    session.state = SessionState.CLOSED.value
    session.closed_at = now
    audit(db, actor, "session_closed", target_type="session", target_id=session.id,
          detail={"auto": actor is None, "absent": len(absent), "on_leave": len(on_leave),
                  "roster": len(roster)})
    label = subject_label(db, session)
    day = session_local_date(session, cfg).isoformat()
    if absent:
        notify(db, absent, "attendance_absent", f"Marked absent: {label}",
               f"You were not marked present in {label} on {day}. If this is wrong, raise an "
               f"attendance correction issue or apply for leave.", link="/student/history")
    db.commit()
    emit("session_state", {"state": "closed", "session_id": session.id,
                           "absent": len(absent), "on_leave": len(on_leave)},
         session_id=session.id)
    check_minimum(db, roster, cfg)
    log.info("session %d closed: %d absent, %d on leave", session.id, len(absent), len(on_leave))
    return {"session_id": session.id, "absent": len(absent), "on_leave": len(on_leave)}


# ------------------------------------------------------------------- marking

def record_mark(db: Session, session: ClassSession, user: User, method: str, cfg, *,
                status: str, confidence: Optional[float] = None,
                marked_by: Optional[User] = None, evidence: Optional[str] = None,
                notify_student: bool = True) -> Tuple[AttendanceRecordRow, bool]:
    """Insert the student's record. Returns (row, created). Never updates an existing row."""
    existing = db.scalars(select(AttendanceRecordRow).where(
        AttendanceRecordRow.session_id == session.id,
        AttendanceRecordRow.user_id == user.id)).first()
    if existing is not None:
        return existing, False
    now = utcnow()
    row = AttendanceRecordRow(
        session_id=session.id, user_id=user.id, status=status, source=method,
        first_seen=now, last_seen=now, computed_at=now, marked_at=now,
        marked_by_id=marked_by.id if marked_by else None, confidence=confidence,
        avg_confidence=confidence or 0.0, evidence=evidence)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Lost a race with another request for the same student and session.
        db.rollback()
        existing = db.scalars(select(AttendanceRecordRow).where(
            AttendanceRecordRow.session_id == session.id,
            AttendanceRecordRow.user_id == user.id)).first()
        return existing, False
    label = subject_label(db, session)
    if notify_student:
        notify(db, [user.id], "attendance_marked", f"Attendance marked: {status.replace('_', ' ')}",
               f"{label}: marked {status.replace('_', ' ')} via {method}.", link="/student/history")
    db.commit()
    emit("record_updated", {"user_id": user.id, "status": status, "method": method,
                            "display_name": user.display_name, "roll_number": user.roll_number,
                            "confidence": confidence},
         session_id=session.id)
    return row, True


# --------------------------------------------------------------------- leave

def apply_leave(db: Session, leave: LeaveRequest, cfg, actor: Optional[User]) -> int:
    """Rewrite already-recorded sessions covered by a newly approved leave to ON LEAVE.

    Absent / needs-review rows change; a student who actually attended keeps Present.
    """
    ids = None
    if leave.session_ids:
        try:
            ids = set(json.loads(leave.session_ids))
        except ValueError:
            ids = None
    start = local_dt(leave.from_date, 0, cfg) - timedelta(hours=1)
    end = local_dt(leave.to_date, 24 * 60 - 1, cfg) + timedelta(hours=1)
    stmt = (select(AttendanceRecordRow, ClassSession)
            .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
            .where(AttendanceRecordRow.user_id == leave.requester_id,
                   ClassSession.scheduled_start >= start, ClassSession.scheduled_start <= end,
                   ClassSession.deleted_at.is_(None)))
    changed = 0
    for row, sess in db.execute(stmt).all():
        if ids is not None and sess.id not in ids:
            continue
        on = session_local_date(sess, cfg)
        if not (leave.from_date <= on <= leave.to_date):
            continue
        eff = row.effective_status
        if eff not in (AttendanceStatus.ABSENT.value, AttendanceStatus.NEEDS_REVIEW.value):
            continue
        if row.source == CaptureMethod.FACE.value:
            # Derived rows are rebuilt by recompute; record the decision as an override.
            row.overridden_status = AttendanceStatus.ON_LEAVE.value
            row.override_reason = f"approved leave #{leave.id}"
            row.overridden_by_id = actor.id if actor else None
            row.overridden_at = utcnow()
        else:
            row.status = AttendanceStatus.ON_LEAVE.value
        row.leave_request_id = leave.id
        row.needs_review = False
        changed += 1
        emit("record_updated", {"user_id": row.user_id, "status": "on_leave", "method": "leave"},
             session_id=sess.id)
    if changed:
        audit(db, actor, "leave_applied", target_type="leave_request", target_id=leave.id,
              detail={"records_changed": changed})
    return changed


# ---------------------------------------------------------------- thresholds

def overall_pct(db: Session, user_id: int) -> Tuple[int, int]:
    from app.analytics_service import subject_breakdown

    subjects = subject_breakdown(db, user_id)
    counted = sum(s["counted"] for s in subjects)
    present = sum(s["present"] for s in subjects)
    # Ad-hoc sessions with no subject still count toward the overall figure.
    from sqlalchemy import case

    from app.models import COUNTS_PRESENT, EXCLUDED_FROM_TOTAL

    eff = func.coalesce(AttendanceRecordRow.overridden_status, AttendanceRecordRow.status)
    row = db.execute(
        select(func.sum(case((eff.in_(tuple(EXCLUDED_FROM_TOTAL)), 0), else_=1)),
               func.sum(case((eff.in_(tuple(COUNTS_PRESENT)), 1), else_=0)))
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .where(AttendanceRecordRow.user_id == user_id, AttendanceRecordRow.deleted_at.is_(None),
               ClassSession.deleted_at.is_(None), ClassSession.subject_id.is_(None))).first()
    if row and row[0]:
        counted += int(row[0] or 0)
        present += int(row[1] or 0)
    return present, counted


def check_minimum(db: Session, user_ids: Iterable[int], cfg) -> int:
    """Tell students (and guardians) once when they fall below the minimum; re-arm on recovery."""
    from app.analytics_service import _classes_needed

    threshold = float(settings_service.get(db, cfg, "min_attendance_pct"))
    alerted = 0
    for uid in set(user_ids):
        prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == uid)).first()
        if prof is None:
            continue
        present, counted = overall_pct(db, uid)
        if counted < 3:
            continue                      # too few classes for a percentage to mean anything
        pct = 100.0 * present / counted
        if pct < threshold and not prof.below_min_notified:
            need = _classes_needed(present, counted, threshold)
            msg = (f"Your attendance is {pct:.1f}%, below the required {threshold:g}%. Attend "
                   f"the next {need} class(es) in a row to get back to {threshold:g}%.")
            notify(db, [uid], "below_minimum", "Attendance below the minimum", msg,
                   link="/student", email=True,
                   email_to=[prof.guardian_email] if prof.guardian_email else None)
            prof.below_min_notified = True
            alerted += 1
        elif pct >= threshold and prof.below_min_notified:
            prof.below_min_notified = False
    db.commit()
    return alerted


# ------------------------------------------------------------------ scheduler

def tick(db: Session, cfg, now: Optional[datetime] = None) -> dict:
    """Open + start today's timetabled lectures at their start time; close finished ones."""
    from app.marking_service import MarkingError, open_session
    from app.models import AcademicTerm, Section, TimetableSlot
    from app.routes.academic import is_holiday

    now = now or utcnow()
    started = closed = 0
    s = settings_service.all_settings(db, cfg)

    if s["auto_sessions"]:
        today = now.astimezone(zone(tz_of(cfg))).date()
        term = db.scalars(select(AcademicTerm).where(AcademicTerm.is_active.is_(True))).first()
        if term is not None and term.start_date <= today <= term.end_date:
            slots = db.scalars(select(TimetableSlot).where(
                TimetableSlot.term_id == term.id, TimetableSlot.day_of_week == today.weekday()))
            for slot in slots:
                start = local_dt(today, slot.start_minute, cfg)
                end = local_dt(today, slot.end_minute, cfg)
                if not (start <= now < end):
                    continue
                sec = db.get(Section, slot.section_id)
                dept = sec.program.department_id if sec and sec.program else None
                if is_holiday(db, today, dept):
                    continue
                teacher = db.get(User, slot.faculty_id)
                try:
                    sess = open_session(db, slot, today, teacher, cfg)
                except MarkingError:
                    continue
                if sess.state == SessionState.SCHEDULED.value:
                    try:
                        start_session(db, sess, cfg, None)
                        started += 1
                    except SessionError:
                        pass

    due = db.scalars(select(ClassSession).where(
        ClassSession.state.in_([SessionState.SCHEDULED.value, SessionState.ACTIVE.value]),
        ClassSession.scheduled_end <= now, ClassSession.deleted_at.is_(None)))
    for sess in list(due):
        close_session(db, sess, cfg, None)
        closed += 1
    return {"started": started, "closed": closed}
