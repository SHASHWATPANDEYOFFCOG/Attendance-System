"""Live sessions (authority side) and the student's own day: active lecture, QR marking,
today's timetable, and attendance history with PDF export."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import settings_service
from app.analytics_service import todays_periods
from app.audit import audit
from app.auth import (
    assert_owns_session,
    current_user,
    department_scope,
    is_admin,
    is_faculty,
    is_student,
    is_super_admin,
    require_staff,
)
from app.clock import local_today, tz_of, zone
from app.db import get_db
from app.marking_service import MarkingError, open_session
from app.models import (
    AttendanceRecordRow,
    CaptureMethod,
    ClassSession,
    RosterEntry,
    ReviewItem,
    Section,
    SessionState,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
    utcnow,
)
from app.ratelimit import client_ip, enforce
from app.routes.academic import active_term, is_holiday, section_label
from app.runtime import cfg, public_base_url
from app.selfmark import (
    SelfMarkError,
    check_code,
    check_geofence,
    log_attempt,
    precheck,
    remaining_attempts,
)
from app.session_code import current as current_code
from app.session_service import (
    SessionError,
    approved_roster,
    close_session,
    local_dt,
    record_mark,
    session_local_date,
    start_session,
)
from app.tabular_export import export

router = APIRouter(prefix="/api", tags=["sessions"])


def _session(db: Session, session_id: int) -> ClassSession:
    s = db.get(ClassSession, session_id)
    if s is None or s.deleted_at is not None:
        raise HTTPException(404, "session not found")
    return s


def _counts(db: Session, session: ClassSession) -> dict:
    roster = approved_roster(db, session)
    rows = list(db.scalars(select(AttendanceRecordRow).where(
        AttendanceRecordRow.session_id == session.id, AttendanceRecordRow.deleted_at.is_(None))))
    c = {"roster": len(roster), "present": 0, "late": 0, "absent": 0, "on_leave": 0,
         "excused": 0, "other": 0}
    marked = set()
    for r in rows:
        if r.user_id not in roster:
            continue
        marked.add(r.user_id)
        st = r.effective_status
        if st in c and st != "roster":
            c[st] += 1
        elif st == "on_duty":
            c["present"] += 1
        else:
            c["other"] += 1
    c["unmarked"] = len([u for u in roster if u not in marked])
    return c


def _session_card(db: Session, s: ClassSession) -> dict:
    subj = db.get(Subject, s.subject_id) if s.subject_id else None
    sec = db.get(Section, s.section_id) if s.section_id else None
    return {
        "id": s.id, "title": s.title, "state": s.state, "room": s.room,
        "subject_code": subj.code if subj else None, "subject_name": subj.name if subj else None,
        "section_id": s.section_id, "section_label": section_label(sec) if sec else None,
        "scheduled_start": s.scheduled_start, "scheduled_end": s.scheduled_end,
        "started_at": s.started_at, "closed_at": s.closed_at, "slot_id": s.timetable_slot_id,
        "is_locked": s.is_locked, "counts": _counts(db, s),
        "review_pending": db.scalar(select(func.count()).select_from(ReviewItem).where(
            ReviewItem.session_id == s.id, ReviewItem.status == "pending")) or 0,
    }


# ---------------------------------------------------------------- authority

@router.get("/sessions/live")
def live_sessions(on: Optional[str] = None, db: Session = Depends(get_db),
                  actor: User = Depends(require_staff)):
    """Today's lectures for this teacher (HOD: branch; admin: all), opened or not, with live counts."""
    tz = tz_of(cfg)
    day = date.fromisoformat(on) if on else local_today(tz)
    periods = todays_periods(db, actor, on=day, department_id=department_scope(actor), tz=tz)
    out = []
    seen_sessions = set()
    for p in periods:
        sess = db.get(ClassSession, p["session_id"]) if p.get("session_id") else None
        slot = db.get(TimetableSlot, p["slot_id"])
        sec = db.get(Section, slot.section_id) if slot else None
        holiday = is_holiday(db, day, sec.program.department_id if sec and sec.program else None)
        item = {
            "slot_id": p["slot_id"], "subject_code": p["subject_code"],
            "subject_name": p["subject_name"], "room": p["room"],
            "start_time": p["start_time"], "end_time": p["end_time"],
            "section_label": section_label(sec) if sec else p["section_label"],
            "holiday": holiday,
            "starts_at": local_dt(day, slot.start_minute, cfg) if slot else None,
            "ends_at": local_dt(day, slot.end_minute, cfg) if slot else None,
            "session": _session_card(db, sess) if sess else None,
        }
        if sess:
            seen_sessions.add(sess.id)
        out.append(item)
    # Ad-hoc sessions held today that are not timetable periods.
    start = local_dt(day, 0, cfg)
    end = start + timedelta(days=1)
    from app.api import scope_sessions

    for s in db.scalars(scope_sessions(select(ClassSession).where(
            ClassSession.scheduled_start >= start, ClassSession.scheduled_start < end,
            ClassSession.deleted_at.is_(None)), actor, db)):
        if s.id in seen_sessions:
            continue
        out.append({"slot_id": None, "subject_code": None, "subject_name": s.title,
                    "room": s.room, "start_time": s.scheduled_start.astimezone(zone(tz)).strftime("%H:%M"),
                    "end_time": s.scheduled_end.astimezone(zone(tz)).strftime("%H:%M"),
                    "section_label": None, "holiday": None, "starts_at": s.scheduled_start,
                    "ends_at": s.scheduled_end, "session": _session_card(db, s)})
    out.sort(key=lambda x: x["start_time"])
    return {"date": day.isoformat(), "now": utcnow(), "periods": out}


class OpenIn(BaseModel):
    slot_id: int
    date: Optional[str] = None
    start: bool = True


@router.post("/sessions/open")
def open_and_start(body: OpenIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_staff)):
    """Open a timetable period's session (idempotent) and, by default, start it now."""
    slot = db.get(TimetableSlot, body.slot_id)
    if slot is None:
        raise HTTPException(404, "timetable period not found")
    if not is_super_admin(actor):
        if is_admin(actor):
            subj = db.get(Subject, slot.subject_id)
            if subj is None or subj.department_id != actor.department_id:
                raise HTTPException(403, "this period belongs to another branch")
        elif slot.faculty_id != actor.id:
            raise HTTPException(403, "you do not teach this period")
    on = date.fromisoformat(body.date) if body.date else local_today(tz_of(cfg))
    try:
        sess = open_session(db, slot, on, actor, cfg)
    except MarkingError as exc:
        raise HTTPException(exc.code, exc.message)
    if body.start and sess.state == SessionState.SCHEDULED.value:
        try:
            start_session(db, sess, cfg, actor)
        except SessionError as exc:
            raise HTTPException(exc.code, exc.message)
    return _session_card(db, sess)


@router.post("/sessions/{session_id}/start")
def start(session_id: int, db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    s = _session(db, session_id)
    assert_owns_session(actor, s)
    try:
        start_session(db, s, cfg, actor)
    except SessionError as exc:
        raise HTTPException(exc.code, exc.message)
    return _session_card(db, s)


@router.post("/sessions/{session_id}/stop")
def stop(session_id: int, db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    s = _session(db, session_id)
    assert_owns_session(actor, s)
    if s.state == SessionState.CLOSED.value:
        raise HTTPException(409, "This session is already closed.")
    result = close_session(db, s, cfg, actor)
    return {**_session_card(db, s), "closed": result}


@router.get("/sessions/{session_id}/live")
def session_live(session_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require_staff)):
    s = _session(db, session_id)
    assert_owns_session(actor, s)
    roster = approved_roster(db, s)
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(roster or [-1])))}
    recs = {r.user_id: r for r in db.scalars(select(AttendanceRecordRow).where(
        AttendanceRecordRow.session_id == s.id))}
    rows = []
    for uid in roster:
        u = users.get(uid)
        if u is None:
            continue
        r = recs.get(uid)
        rows.append({
            "user_id": uid, "display_name": u.display_name, "roll_number": u.roll_number,
            "record_id": r.id if r else None,
            "status": r.effective_status if r else None,
            "method": r.source if r else None, "marked_at": r.marked_at if r else None,
            "confidence": round(r.confidence, 3) if r and r.confidence is not None else None,
            "overridden": bool(r and r.overridden_status),
            "needs_review": bool(r and r.needs_review),
        })
    rows.sort(key=lambda x: (x["roll_number"] or "", x["display_name"]))
    s_all = settings_service.all_settings(db, cfg)
    return {**_session_card(db, s), "roster": rows,
            "windows": {"present_min": s_all["present_window_min"],
                        "late_min": s_all["late_window_min"]}}


@router.get("/sessions/{session_id}/code")
def session_code(session_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require_staff)):
    """The rotating code for the classroom screen. Staff only; students never see the secret."""
    s = _session(db, session_id)
    assert_owns_session(actor, s)
    if s.state != SessionState.ACTIVE.value or not s.code_secret:
        raise HTTPException(409, "Start the session to show its attendance code.")
    rotation = int(settings_service.get(db, cfg, "session_code_rotation_s"))
    code, remaining = current_code(s.code_secret, rotation)
    return {"code": code, "expires_in": remaining, "rotation_s": rotation,
            "qr_url": f"{public_base_url()}/student/scan?s={s.id}&c={code}"}


# ------------------------------------------------------------------ student

def _student_profile(db: Session, user: User) -> Optional[StudentProfile]:
    return db.scalars(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()


@router.get("/me/sessions/active")
def my_active_sessions(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """Lectures the student can mark right now (or has just marked), with what each needs."""
    if not is_student(actor):
        return {"sessions": [], "approved": False}
    prof = _student_profile(db, actor)
    approved = prof is not None and prof.status == "approved"
    s_all = settings_service.all_settings(db, cfg)
    rows = db.scalars(select(ClassSession).join(RosterEntry, RosterEntry.session_id == ClassSession.id)
                      .where(RosterEntry.user_id == actor.id,
                             ClassSession.state == SessionState.ACTIVE.value,
                             ClassSession.deleted_at.is_(None)))
    out = []
    from app.session_service import window_status

    for s in rows:
        rec = db.scalars(select(AttendanceRecordRow).where(
            AttendanceRecordRow.session_id == s.id,
            AttendanceRecordRow.user_id == actor.id)).first()
        subj = db.get(Subject, s.subject_id) if s.subject_id else None
        status_now = window_status(s, utcnow(), db, cfg)
        out.append({
            "id": s.id, "subject_code": subj.code if subj else None,
            "subject_name": subj.name if subj else s.title, "room": s.room,
            "scheduled_start": s.scheduled_start, "scheduled_end": s.scheduled_end,
            "marked": rec is not None,
            "status": rec.effective_status if rec else None,
            "method": rec.source if rec else None,
            "would_be": status_now,
            "window_open": status_now is not None,
            "attempts_left": remaining_attempts(db, s, actor, cfg),
        })
    return {
        "approved": approved,
        "sessions": out,
        "requires_code": bool(s_all["require_session_code"]),
        "geofence": bool(s_all["geofence_enabled"]),
        "face_ready": actor.has_biometrics and actor.consent_given,
        "windows": {"present_min": s_all["present_window_min"],
                    "late_min": s_all["late_window_min"]},
    }


class QrIn(BaseModel):
    session_id: int
    code: str = Field(min_length=4, max_length=12)
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy: Optional[float] = None


@router.post("/attendance/qr")
def qr_mark(body: QrIn, request: Request, db: Session = Depends(get_db),
            actor: User = Depends(current_user)):
    """Mark yourself present by scanning the rotating classroom QR (no face data involved)."""
    enforce(request, "attendance", key=str(actor.id))
    s = db.get(ClassSession, body.session_id)
    ip = client_ip(request)
    try:
        status = precheck(db, s, actor, cfg)
        geo = check_geofence(db, s, cfg, body.lat, body.lng, body.accuracy)
        if not geo.ok:
            raise SelfMarkError(403, geo.reason, kind="geofence")
        check_code(db, s, cfg, body.code, required=True)
    except SelfMarkError as exc:
        if s is not None and exc.counts:
            log_attempt(db, s.id, actor.id, CaptureMethod.QR.value, False, exc.message, ip=ip)
        left = remaining_attempts(db, s, actor, cfg) if s is not None else None
        raise HTTPException(exc.code, detail={"message": exc.message, "kind": exc.kind,
                                              "attempts_left": left})
    row, created = record_mark(db, s, actor, CaptureMethod.QR.value, cfg, status=status,
                               evidence=f"QR code; {geo.reason}"
                                        + (f" ({geo.distance_m:.0f} m)" if geo.distance_m is not None else ""))
    if not created:
        raise HTTPException(409, detail={"message": f"You are already marked "
                                                    f"{row.effective_status.replace('_', ' ')}.",
                                         "kind": "already_marked"})
    log_attempt(db, s.id, actor.id, CaptureMethod.QR.value, True, f"marked {status}", ip=ip,
                distance_m=geo.distance_m)
    return {"status": status, "session_id": s.id, "method": "qr",
            "message": f"Marked {status} for this lecture."}


@router.get("/me/timetable/today")
def my_today(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """The student's lectures today, each with its live state and their own status."""
    prof = _student_profile(db, actor)
    tz = tz_of(cfg)
    today = local_today(tz)
    if prof is None or prof.section_id is None:
        return {"date": today.isoformat(), "periods": [], "holiday": None}
    sec = db.get(Section, prof.section_id)
    holiday = is_holiday(db, today, sec.program.department_id if sec and sec.program else None)
    term = active_term(db)
    stmt = select(TimetableSlot).where(TimetableSlot.section_id == prof.section_id,
                                       TimetableSlot.day_of_week == today.weekday())
    if term is not None:
        stmt = stmt.where(TimetableSlot.term_id == term.id)
    out = []
    for slot in db.scalars(stmt.order_by(TimetableSlot.start_minute)):
        start = local_dt(today, slot.start_minute, cfg)
        sess = db.scalars(select(ClassSession).where(
            ClassSession.timetable_slot_id == slot.id, ClassSession.scheduled_start == start,
            ClassSession.deleted_at.is_(None))).first()
        rec = None
        if sess:
            rec = db.scalars(select(AttendanceRecordRow).where(
                AttendanceRecordRow.session_id == sess.id,
                AttendanceRecordRow.user_id == actor.id)).first()
        subj = db.get(Subject, slot.subject_id)
        teacher = db.get(User, slot.faculty_id)
        now = utcnow()
        phase = ("upcoming" if now < start else
                 "ongoing" if now < local_dt(today, slot.end_minute, cfg) else "over")
        out.append({
            "slot_id": slot.id, "session_id": sess.id if sess else None,
            "subject_code": subj.code if subj else None, "subject_name": subj.name if subj else None,
            "teacher": teacher.display_name if teacher else None, "room": slot.room,
            "start_time": slot.start_time, "end_time": slot.end_time, "phase": phase,
            "session_state": sess.state if sess else None,
            "status": rec.effective_status if rec else None,
            "method": rec.source if rec else None,
        })
    return {"date": today.isoformat(), "holiday": holiday, "periods": out}


HISTORY_COLUMNS = [("date", "Date"), ("time", "Time"), ("subject", "Subject"),
                   ("status", "Status"), ("method", "Marked by"), ("note", "Note")]


@router.get("/me/history")
def my_history(subject_id: Optional[int] = None, month: Optional[str] = None,
               status: Optional[str] = None, format: Optional[str] = None,
               page: int = 1, page_size: int = 50, user_id: Optional[int] = None,
               db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """Own history (students), a linked child's (parents) or any student in scope (staff)."""
    target = actor
    if user_id is not None and user_id != actor.id:
        from app.scope import can_read_student

        if not can_read_student(db, actor, user_id):
            raise HTTPException(403, "you may only view your own attendance")
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, "student not found")
    tz = tz_of(cfg)
    eff = func.coalesce(AttendanceRecordRow.overridden_status, AttendanceRecordRow.status)
    stmt = (select(AttendanceRecordRow, ClassSession, Subject)
            .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
            .outerjoin(Subject, Subject.id == ClassSession.subject_id)
            .where(AttendanceRecordRow.user_id == target.id,
                   AttendanceRecordRow.deleted_at.is_(None), ClassSession.deleted_at.is_(None)))
    if subject_id:
        stmt = stmt.where(ClassSession.subject_id == subject_id)
    if status:
        stmt = stmt.where(eff == status)
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            first = date(y, m, 1)
            nxt = date(y + (m == 12), m % 12 + 1, 1)
        except ValueError:
            raise HTTPException(422, "month must be YYYY-MM")
        stmt = stmt.where(ClassSession.scheduled_start >= local_dt(first, 0, cfg),
                          ClassSession.scheduled_start < local_dt(nxt, 0, cfg))
    stmt = stmt.order_by(ClassSession.scheduled_start.desc())

    def as_row(r, s, subj):
        local = s.scheduled_start.astimezone(zone(tz))
        note = r.override_reason if r.overridden_status else (
            "approved leave" if r.leave_request_id else "")
        return {"record_id": r.id, "session_id": s.id, "date": local.date().isoformat(),
                "time": local.strftime("%H:%M"),
                "subject": f"{subj.code} {subj.name}" if subj else s.title,
                "subject_id": subj.id if subj else None, "status": r.effective_status,
                "method": {"face": "camera", "cctv": "camera", "mobile": "selfie",
                           "qr": "QR code", "manual": "teacher", "system": "automatic",
                           "import": "import"}.get(r.source, r.source),
                "note": note or ""}

    if format:
        rows = [as_row(*t) for t in db.execute(stmt.limit(5000)).all()]
        prof = _student_profile(db, target)
        meta = [f"Student: {target.display_name}"
                + (f" ({prof.roll_number or target.roll_number})" if prof else ""),
                f"Filters: subject={subject_id or 'all'} month={month or 'all'} "
                f"status={status or 'all'}", f"{len(rows)} lecture(s)"]
        try:
            body, media, ext = export(format, org=str(settings_service.get(db, cfg, "org_name")),
                                      title="Attendance history", meta=meta,
                                      columns=HISTORY_COLUMNS, rows=rows, tz=tz)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        name = f"attendance-{(target.roll_number or target.username)}-{utcnow():%Y%m%d}.{ext}"
        return Response(body, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    page_size = max(10, min(200, page_size))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = [as_row(*t) for t in db.execute(stmt.offset((max(1, page) - 1) * page_size)
                                           .limit(page_size)).all()]
    subjects = [{"id": i, "label": f"{c} {n}"} for i, c, n in db.execute(
        select(Subject.id, Subject.code, Subject.name)
        .join(ClassSession, ClassSession.subject_id == Subject.id)
        .join(AttendanceRecordRow, AttendanceRecordRow.session_id == ClassSession.id)
        .where(AttendanceRecordRow.user_id == target.id).distinct().order_by(Subject.code)).all()]
    return {"rows": rows, "subjects": subjects,
            "meta": {"page": max(1, page), "page_size": page_size, "total": total,
                     "pages": (total + page_size - 1) // page_size}}
