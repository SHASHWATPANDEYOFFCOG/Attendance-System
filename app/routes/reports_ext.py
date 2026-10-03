"""Summary reports: daily, monthly, subject-wise, student-wise, defaulters — plus class-wise
numbers for the dashboard.

Every report:
  * is scoped like the rest of the authority portal (teacher: their classes; HOD: their branch;
    admin: everything) — in the SQL, never by filtering afterwards;
  * takes a date range (local calendar days) and optional branch / class / subject filters;
  * renders as JSON for the screen, or as CSV / Excel / PDF with the college name, the report
    title, the generation date and the filters — built from the very same rows, so the export
    can never disagree with the table on screen.

Percentages use the one shared rule: present + late + on-duty count as attended; on-leave and
excused are removed from the denominator.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app import settings_service
from app.analytics_service import _classes_needed
from app.audit import audit
from app.auth import department_scope, is_faculty, require_staff
from app.clock import tz_of, zone
from app.db import get_db
from app.models import (
    AttendanceRecordRow,
    COUNTS_PRESENT,
    ClassSession,
    Department,
    EXCLUDED_FROM_TOTAL,
    Program,
    Section,
    StudentProfile,
    Subject,
    User,
    utcnow,
)
from app.routes.academic import section_label
from app.runtime import cfg
from app.scope import can_manage_student, taught_section_ids
from app.session_service import local_dt
from app.tabular_export import export

router = APIRouter(prefix="/api", tags=["reports"])

_eff = func.coalesce(AttendanceRecordRow.overridden_status, AttendanceRecordRow.status)
_counted = func.sum(case((_eff.in_(tuple(EXCLUDED_FROM_TOTAL)), 0), else_=1))
_present = func.sum(case((_eff.in_(tuple(COUNTS_PRESENT)), 1), else_=0))


def _n(status: str):
    return func.sum(case((_eff == status, 1), else_=0))


def _pct(p, c) -> Optional[float]:
    return round(100.0 * (p or 0) / c, 1) if c else None


class Scope:
    def __init__(self, db: Session, actor: User, department_id: Optional[int]):
        own = department_scope(actor)
        if own is not None and department_id not in (None, own):
            raise HTTPException(403, "you may only report on your own branch")
        self.department_id = own if own is not None else department_id
        self.sections = taught_section_ids(db, actor) if is_faculty(actor) else None
        self.actor = actor


def _base(scope: Scope, date_from: Optional[date], date_to: Optional[date],
          section_id: Optional[int], subject_id: Optional[int]):
    stmt = (select().select_from(AttendanceRecordRow)
            .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
            .join(User, User.id == AttendanceRecordRow.user_id)
            .outerjoin(Subject, Subject.id == ClassSession.subject_id)
            .where(AttendanceRecordRow.deleted_at.is_(None), ClassSession.deleted_at.is_(None),
                   User.deleted_at.is_(None)))
    if scope.sections is not None:
        stmt = stmt.where(ClassSession.section_id.in_(list(scope.sections) or [-1]))
    if scope.department_id is not None:
        stmt = stmt.where(Subject.department_id == scope.department_id)
    if date_from:
        stmt = stmt.where(ClassSession.scheduled_start >= local_dt(date_from, 0, cfg))
    if date_to:
        stmt = stmt.where(ClassSession.scheduled_start < local_dt(date_to + timedelta(days=1), 0, cfg))
    if section_id:
        stmt = stmt.where(ClassSession.section_id == section_id)
    if subject_id:
        stmt = stmt.where(ClassSession.subject_id == subject_id)
    return stmt


def _respond(db: Session, actor: User, fmt: Optional[str], title: str, meta: List[str],
             columns, rows: List[dict], slug: str):
    if not fmt:
        return {"title": title, "meta": meta, "columns": [{"key": k, "label": l} for k, l in columns],
                "rows": rows}
    org = str(settings_service.get(db, cfg, "org_name"))
    try:
        body, media, ext = export(fmt, org=org, title=title, meta=meta, columns=columns, rows=rows,
                                  tz=tz_of(cfg))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit(db, actor, "report_exported", target_type="report", detail={"report": slug, "format": fmt,
                                                                      "rows": len(rows)})
    db.commit()
    name = f"{slug}-{utcnow().astimezone(zone(tz_of(cfg))):%Y%m%d-%H%M}.{ext}"   # local time
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _describe(db: Session, date_from, date_to, department_id, section_id, subject_id) -> str:
    parts = [f"{date_from or 'start'} to {date_to or 'today'}"]
    if department_id:
        d = db.get(Department, department_id)
        parts.append(f"branch {d.code if d else department_id}")
    if section_id:
        s = db.get(Section, section_id)
        parts.append(f"class {section_label(s) if s else section_id}")
    if subject_id:
        s = db.get(Subject, subject_id)
        parts.append(f"subject {s.code if s else subject_id}")
    return "Filters: " + ", ".join(parts)


def _default_range(date_from: Optional[date], date_to: Optional[date]):
    from app.clock import local_today

    today = local_today(tz_of(cfg))
    return date_from or (today - timedelta(days=30)), date_to or today


# ------------------------------------------------------------------ daily

DAILY_COLUMNS = [("date", "Date"), ("lectures", "Lectures"), ("marked", "Records"),
                 ("present", "Present"), ("late", "Late"), ("absent", "Absent"),
                 ("on_leave", "On leave"), ("pct", "Attendance %")]


@router.get("/reports/daily")
def daily_report(date_from: Optional[date] = None, date_to: Optional[date] = None,
                 department_id: Optional[int] = None, section_id: Optional[int] = None,
                 subject_id: Optional[int] = None, format: Optional[str] = None,
                 db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    scope = Scope(db, actor, department_id)
    date_from, date_to = _default_range(date_from, date_to)
    tz = zone(tz_of(cfg))
    stmt = _base(scope, date_from, date_to, section_id, subject_id).add_columns(
        ClassSession.id, ClassSession.scheduled_start, _eff.label("st"))
    per: dict = {}
    for sid, start, st in db.execute(stmt).all():
        d = start.astimezone(tz).date().isoformat()
        e = per.setdefault(d, {"date": d, "sessions": set(), "marked": 0, "present": 0, "late": 0,
                               "absent": 0, "on_leave": 0, "counted": 0, "attended": 0})
        e["sessions"].add(sid)
        e["marked"] += 1
        if st in e:
            e[st] += 1
        if st not in EXCLUDED_FROM_TOTAL:
            e["counted"] += 1
        if st in COUNTS_PRESENT:
            e["attended"] += 1
    rows = []
    for d in sorted(per, reverse=True):
        e = per[d]
        rows.append({"date": d, "lectures": len(e["sessions"]), "marked": e["marked"],
                     "present": e["present"], "late": e["late"], "absent": e["absent"],
                     "on_leave": e["on_leave"], "pct": _pct(e["attended"], e["counted"])})
    meta = [_describe(db, date_from, date_to, scope.department_id, section_id, subject_id)]
    return _respond(db, actor, format, "Daily attendance report", meta, DAILY_COLUMNS, rows, "daily")


# ---------------------------------------------------------------- monthly

MONTHLY_COLUMNS = [("roll_number", "Roll"), ("student", "Student"), ("section", "Class"),
                   ("lectures", "Lectures"), ("present", "Present"), ("late", "Late"),
                   ("absent", "Absent"), ("on_leave", "On leave"), ("pct", "Attendance %")]


@router.get("/reports/monthly")
def monthly_report(month: Optional[str] = None, department_id: Optional[int] = None,
                   section_id: Optional[int] = None, subject_id: Optional[int] = None,
                   format: Optional[str] = None, db: Session = Depends(get_db),
                   actor: User = Depends(require_staff)):
    from app.clock import local_today

    scope = Scope(db, actor, department_id)
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            first = date(y, m, 1)
        except ValueError:
            raise HTTPException(422, "month must be YYYY-MM")
    else:
        t = local_today(tz_of(cfg))
        first = date(t.year, t.month, 1)
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    stmt = (_base(scope, first, nxt - timedelta(days=1), section_id, subject_id)
            .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
            .add_columns(User.id, User.display_name, func.coalesce(StudentProfile.roll_number,
                                                                    User.roll_number),
                         StudentProfile.section_id, func.count(), _counted, _present,
                         _n("late"), _n("absent"), _n("on_leave"))
            .group_by(User.id, User.display_name, StudentProfile.roll_number, User.roll_number,
                      StudentProfile.section_id))
    sections = {s.id: s for s in db.scalars(select(Section))}
    rows = []
    for uid, name, roll, sec, total, counted, present, late, absent, leave in db.execute(stmt).all():
        rows.append({"student_id": uid, "roll_number": roll, "student": name,
                     "section": section_label(sections[sec]) if sec in sections else None,
                     "lectures": int(total), "present": int(present or 0) - int(late or 0),
                     "late": int(late or 0), "absent": int(absent or 0),
                     "on_leave": int(leave or 0), "pct": _pct(present, counted)})
    rows.sort(key=lambda r: (r["section"] or "", r["roll_number"] or ""))
    meta = [f"Month: {first:%B %Y}",
            _describe(db, first, nxt - timedelta(days=1), scope.department_id, section_id, subject_id)]
    return _respond(db, actor, format, f"Monthly attendance — {first:%B %Y}", meta,
                    MONTHLY_COLUMNS, rows, f"monthly-{first:%Y-%m}")


# ----------------------------------------------------------- subject-wise

SUBJECT_COLUMNS = [("subject", "Subject"), ("section", "Class"), ("lectures", "Lectures"),
                   ("records", "Records"), ("attended", "Attended"), ("pct", "Attendance %"),
                   ("below", "Students below minimum")]


@router.get("/reports/subject-wise")
def subject_report(date_from: Optional[date] = None, date_to: Optional[date] = None,
                   department_id: Optional[int] = None, section_id: Optional[int] = None,
                   format: Optional[str] = None, db: Session = Depends(get_db),
                   actor: User = Depends(require_staff)):
    scope = Scope(db, actor, department_id)
    date_from, date_to = _default_range(date_from, date_to)
    threshold = float(settings_service.get(db, cfg, "min_attendance_pct"))
    base = _base(scope, date_from, date_to, section_id, None)
    stmt = base.add_columns(Subject.id, Subject.code, Subject.name, ClassSession.section_id,
                            func.count(func.distinct(ClassSession.id)), func.count(),
                            _counted, _present) \
        .group_by(Subject.id, Subject.code, Subject.name, ClassSession.section_id)
    per_student = base.add_columns(Subject.id, ClassSession.section_id, User.id, _counted,
                                   _present).group_by(Subject.id, ClassSession.section_id, User.id)
    below: dict = {}
    for subj, sec, _uid, c, p in db.execute(per_student).all():
        if c and 100.0 * (p or 0) / c < threshold:
            below[(subj, sec)] = below.get((subj, sec), 0) + 1
    sections = {s.id: s for s in db.scalars(select(Section))}
    rows = []
    for sid, code, name, sec, lectures, records, counted, present in db.execute(stmt).all():
        rows.append({"subject_id": sid, "subject": f"{code} {name}" if code else "(no subject)",
                     "section": section_label(sections[sec]) if sec in sections else None,
                     "lectures": int(lectures), "records": int(records),
                     "attended": int(present or 0), "pct": _pct(present, counted),
                     "below": below.get((sid, sec), 0)})
    rows.sort(key=lambda r: (r["subject"], r["section"] or ""))
    meta = [_describe(db, date_from, date_to, scope.department_id, section_id, None),
            f"Minimum: {threshold:g}%"]
    return _respond(db, actor, format, "Subject-wise attendance", meta, SUBJECT_COLUMNS, rows,
                    "subject-wise")


# ----------------------------------------------------------- student-wise

STUDENT_COLUMNS = [("subject", "Subject"), ("lectures", "Lectures"), ("present", "Present"),
                   ("late", "Late"), ("absent", "Absent"), ("on_leave", "On leave"),
                   ("pct", "Attendance %"), ("needed", "Classes needed")]


@router.get("/reports/student-wise/{student_id}")
def student_report(student_id: int, date_from: Optional[date] = None,
                   date_to: Optional[date] = None, format: Optional[str] = None,
                   db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    if not can_manage_student(db, actor, student_id):
        raise HTTPException(403, "this student is not in a class you are responsible for")
    user = db.get(User, student_id)
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    threshold = float(settings_service.get(db, cfg, "min_attendance_pct"))
    scope = Scope(db, actor, None)
    scope.sections = None                      # this student is in scope; show all their subjects
    scope.department_id = None
    stmt = (_base(scope, date_from, date_to, None, None)
            .where(AttendanceRecordRow.user_id == student_id)
            .add_columns(Subject.code, Subject.name, func.count(), _counted, _present,
                         _n("late"), _n("absent"), _n("on_leave"))
            .group_by(Subject.code, Subject.name))
    rows = []
    tot_c = tot_p = 0
    for code, name, total, counted, present, late, absent, leave in db.execute(stmt).all():
        c, p = int(counted or 0), int(present or 0)
        tot_c += c
        tot_p += p
        rows.append({"subject": f"{code} {name}" if code else "(no subject)", "lectures": int(total),
                     "present": p - int(late or 0), "late": int(late or 0),
                     "absent": int(absent or 0), "on_leave": int(leave or 0),
                     "pct": _pct(p, c), "needed": _classes_needed(p, c, threshold) if c else 0})
    rows.sort(key=lambda r: r["subject"])
    rows.append({"subject": "OVERALL", "lectures": sum(r["lectures"] for r in rows),
                 "present": sum(r["present"] for r in rows), "late": sum(r["late"] for r in rows),
                 "absent": sum(r["absent"] for r in rows), "on_leave": sum(r["on_leave"] for r in rows),
                 "pct": _pct(tot_p, tot_c), "needed": _classes_needed(tot_p, tot_c, threshold) if tot_c else 0})
    meta = [f"Student: {user.display_name} ({(prof.roll_number if prof else None) or user.roll_number or ''})",
            f"Class: {section_label(prof.section) if prof and prof.section else '-'}",
            f"Period: {date_from or 'start'} to {date_to or 'today'} · minimum {threshold:g}%"]
    return _respond(db, actor, format, "Student attendance report", meta, STUDENT_COLUMNS, rows,
                    f"student-{(prof.roll_number if prof else None) or student_id}")


# -------------------------------------------------------------- defaulters

DEFAULTER_COLUMNS = [("roll_number", "Roll"), ("student", "Student"), ("section", "Class"),
                     ("lectures", "Lectures counted"), ("attended", "Attended"),
                     ("pct", "Attendance %"), ("needed", "Classes needed"),
                     ("guardian_phone", "Guardian phone")]


@router.get("/reports/defaulter-list")
def defaulter_report(threshold: Optional[float] = None, date_from: Optional[date] = None,
                     date_to: Optional[date] = None, department_id: Optional[int] = None,
                     section_id: Optional[int] = None, format: Optional[str] = None,
                     db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    scope = Scope(db, actor, department_id)
    t = float(threshold if threshold is not None else settings_service.get(db, cfg, "min_attendance_pct"))
    stmt = (_base(scope, date_from, date_to, section_id, None)
            .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
            .add_columns(User.id, User.display_name,
                         func.coalesce(StudentProfile.roll_number, User.roll_number),
                         StudentProfile.section_id, StudentProfile.guardian_phone,
                         _counted, _present)
            .group_by(User.id, User.display_name, StudentProfile.roll_number, User.roll_number,
                      StudentProfile.section_id, StudentProfile.guardian_phone))
    sections = {s.id: s for s in db.scalars(select(Section))}
    rows = []
    for uid, name, roll, sec, gphone, counted, present in db.execute(stmt).all():
        c, p = int(counted or 0), int(present or 0)
        if not c or 100.0 * p / c >= t:
            continue
        rows.append({"student_id": uid, "roll_number": roll, "student": name,
                     "section": section_label(sections[sec]) if sec in sections else None,
                     "lectures": c, "attended": p, "pct": _pct(p, c),
                     "needed": _classes_needed(p, c, t), "guardian_phone": gphone})
    rows.sort(key=lambda r: (r["pct"] if r["pct"] is not None else 0))
    meta = [f"Students below {t:g}%",
            _describe(db, date_from, date_to, scope.department_id, section_id, None)]
    return _respond(db, actor, format, "Defaulter list", meta, DEFAULTER_COLUMNS, rows, "defaulters")


# ------------------------------------------------------------- dashboard

@router.get("/analytics/classes")
def class_wise(days: int = 30, db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Attendance % per class group over the last `days`, for the dashboard."""
    from app.clock import local_today

    scope = Scope(db, actor, None)
    today = local_today(tz_of(cfg))
    stmt = (_base(scope, today - timedelta(days=days), today, None, None)
            .add_columns(ClassSession.section_id, _counted, _present,
                         func.count(func.distinct(ClassSession.id)))
            .group_by(ClassSession.section_id))
    sections = {s.id: s for s in db.scalars(select(Section))}
    threshold = float(settings_service.get(db, cfg, "min_attendance_pct"))
    rows = [{"section_id": sec, "label": section_label(sections[sec]) if sec in sections else "ad hoc",
             "pct": _pct(p, c), "lectures": int(n)}
            for sec, c, p, n in db.execute(stmt).all() if c]
    rows.sort(key=lambda r: r["pct"] if r["pct"] is not None else 101)
    return {"days": days, "threshold_pct": threshold, "classes": rows}
