"""Aggregations behind the dashboards and reports.

Everything here is computed **in SQL against a scoped query**, never by pulling rows into Python
and filtering. A defaulter report over 22,350 records must not become 22,350 objects, and a
scoping bug must not be able to hide behind a Python-side filter that ran too late.

The percentage rule lives in one place: `COUNTS_PRESENT` (numerator) and `EXCLUDED_FROM_TOTAL`
(rows that leave the denominator entirely, i.e. approved leave). Conflating those two is the
classic attendance-percentage bug.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import Integer, Select, case, cast, func, select
from sqlalchemy.orm import Session

from app.clock import local_today
from app.models import (
    COUNTS_PRESENT,
    EXCLUDED_FROM_TOTAL,
    AcademicTerm,
    AttendanceRecordRow,
    AttendanceStatus,
    ClassSession,
    Department,
    FacultyAssignment,
    Holiday,
    Program,
    Section,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
    utcnow,
)

# Rows that count toward the numerator / are removed from the denominator, as SQL literals.
_PRESENT = tuple(sorted(COUNTS_PRESENT))
_EXCLUDED = tuple(sorted(EXCLUDED_FROM_TOTAL))


def _counted() -> "case":
    """1 when the row belongs in the denominator, else 0.

    Uses the EFFECTIVE status, like the numerator: a teacher excusing an absence must take it
    out of the denominator too, or the student is still penalised for it.
    """
    effective = func.coalesce(AttendanceRecordRow.overridden_status, AttendanceRecordRow.status)
    return case((effective.in_(_EXCLUDED), 0), else_=1)


def _present() -> "case":
    """1 when the row counts as attended. An override outranks the derived status."""
    effective = func.coalesce(AttendanceRecordRow.overridden_status, AttendanceRecordRow.status)
    return case((effective.in_(_PRESENT), 1), else_=0)


def _effective():
    return func.coalesce(AttendanceRecordRow.overridden_status, AttendanceRecordRow.status)


def _live_records() -> Select:
    """Base query: non-deleted records joined to their session."""
    return (
        select(AttendanceRecordRow)
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
    )


def _apply_department(stmt: Select, department_id: Optional[int]) -> Select:
    if department_id is None:
        return stmt
    return stmt.join(Subject, Subject.id == ClassSession.subject_id) \
               .where(Subject.department_id == department_id)


# ------------------------------------------------------------------- defaulters

def defaulters(db: Session, *, threshold: float = 75.0, department_id: Optional[int] = None,
               section_id: Optional[int] = None, since: Optional[date] = None,
               limit: int = 500) -> List[dict]:
    """Students below `threshold` percent. The single most-used report; one query.

    Ordered worst-first, because the point of the report is who to act on.
    """
    counted = func.sum(_counted()).label("counted")
    present = func.sum(_present()).label("present")

    stmt = (
        select(
            AttendanceRecordRow.user_id,
            User.display_name,
            User.roll_number,
            counted,
            present,
        )
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .join(User, User.id == AttendanceRecordRow.user_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
        .where(User.deleted_at.is_(None))
        .group_by(AttendanceRecordRow.user_id, User.display_name, User.roll_number)
    )
    stmt = _apply_department(stmt, department_id)
    if section_id is not None:
        stmt = stmt.where(ClassSession.section_id == section_id)
    if since is not None:
        stmt = stmt.where(ClassSession.scheduled_start >= _as_utc(since))

    rows = db.execute(stmt).all()
    out = []
    for uid, name, roll, n_counted, n_present in rows:
        if not n_counted:
            continue
        pct = 100.0 * (n_present or 0) / n_counted
        if pct < threshold:
            out.append({
                "user_id": uid, "display_name": name, "roll_number": roll,
                "counted": int(n_counted), "present": int(n_present or 0),
                "attendance_pct": round(pct, 1),
                "shortfall_classes": _classes_needed(n_present or 0, n_counted, threshold),
            })
    out.sort(key=lambda r: r["attendance_pct"])
    return out[:limit]


def _classes_needed(present: int, counted: int, threshold: float) -> int:
    """Consecutive future attendances required to climb back to `threshold`.

    Solving (present + n) / (counted + n) >= t  ->  n >= (t*counted - present) / (1 - t).
    """
    # Exact rational arithmetic: in floats 1 - 0.8 is 0.19999999999999996, which turns an exact
    # 15 into 15.000000000000004 and the ceiling into 16 -- one class too many, on the screen
    # students act on.
    from fractions import Fraction
    import math

    t = Fraction(str(threshold)) / 100
    if counted and Fraction(present, counted) >= t:
        return 0
    if t >= 1:
        return -1                                   # unreachable
    return max(0, math.ceil((t * counted - present) / (1 - t)))


def can_miss(present: int, counted: int, remaining: int, threshold: float = 75.0) -> dict:
    """How many of the remaining scheduled classes a student can still miss.

    The feature students actually open the app for, so the arithmetic is explicit:
    final_pct = (present + attended_from_here) / (counted + remaining) >= t

    `remaining` must be *scheduled classes still to come*, not calendar days -- counting days
    would tell a student they can miss classes that do not exist.
    """
    t = threshold / 100.0
    total = counted + remaining
    need_present = t * total
    can_attend = present + remaining
    slack = can_attend - need_present
    if total <= 0:
        return {"can_miss": 0, "at_risk": False, "reachable": True, "projected_pct": 0.0}

    import math
    # Capped at `remaining`: the slack can exceed the number of classes that actually exist
    # (a student on 100% has more headroom than term left), and "you can miss 12 more" when
    # 10 remain is worse than useless -- it is wrong in the direction that costs attendance.
    misses = min(remaining, max(0, math.floor(slack + 1e-9)))
    reachable = can_attend + 1e-9 >= need_present
    current = 100.0 * present / counted if counted else 0.0
    return {
        "can_miss": misses if reachable else 0,
        "reachable": reachable,
        "at_risk": current < threshold,
        "current_pct": round(current, 1),
        "projected_pct": round(100.0 * can_attend / total, 1),
        "remaining": remaining,
    }


# ------------------------------------------------------------------ daily trend

def attendance_trend(db: Session, *, days: int = 30,
                     department_id: Optional[int] = None) -> List[dict]:
    """Daily attendance percentage, one row per date. Grouped in SQL, not in Python."""
    start = utcnow() - timedelta(days=days)
    day = func.date(ClassSession.scheduled_start).label("day")

    stmt = (
        select(day, func.sum(_counted()).label("counted"), func.sum(_present()).label("present"))
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
        .where(ClassSession.scheduled_start >= start)
        .group_by(day)
        .order_by(day)
    )
    stmt = _apply_department(stmt, department_id)

    return [
        {"date": d, "counted": int(c or 0), "present": int(p or 0),
         "attendance_pct": round(100.0 * (p or 0) / c, 1) if c else None}
        for d, c, p in db.execute(stmt).all()
    ]


def trend_by_department(db: Session, *, days: int = 30,
                        department_ids: Optional[Iterable[int]] = None) -> dict:
    """One series per department, aligned on a shared date axis.

    Returns {"dates": [...], "series": [{"name","code","points":[pct|None,...]}]} so the chart
    never has to align ragged series itself -- a missing day is an explicit null, not a gap that
    silently shifts the line.
    """
    start = utcnow() - timedelta(days=days)
    day = func.date(ClassSession.scheduled_start).label("day")

    stmt = (
        select(Department.id, Department.code, Department.name, day,
               func.sum(_counted()).label("counted"), func.sum(_present()).label("present"))
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .join(Subject, Subject.id == ClassSession.subject_id)
        .join(Department, Department.id == Subject.department_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
        .where(ClassSession.scheduled_start >= start)
        .group_by(Department.id, Department.code, Department.name, day)
        .order_by(day)
    )
    if department_ids is not None:
        stmt = stmt.where(Department.id.in_(list(department_ids)))

    per_dept: dict = defaultdict(dict)
    meta: dict = {}
    dates: set = set()
    for did, code, name, d, counted, present in db.execute(stmt).all():
        meta[did] = {"code": code, "name": name}
        dates.add(d)
        per_dept[did][d] = round(100.0 * (present or 0) / counted, 1) if counted else None

    axis = sorted(dates)
    return {
        "dates": axis,
        "series": [
            {"department_id": did, "code": meta[did]["code"], "name": meta[did]["name"],
             "points": [per_dept[did].get(d) for d in axis]}
            for did in sorted(per_dept)
        ],
    }


def weekday_profile(db: Session, *, days: int = 90,
                    department_id: Optional[int] = None) -> List[dict]:
    """Absence rate per weekday. Feeds the heatmap; 0 = Monday."""
    start = utcnow() - timedelta(days=days)
    # SQLite strftime('%w') is 0=Sunday; shift so 0=Monday to match TimetableSlot.day_of_week.
    # cast() needs a real SQLAlchemy type -- func.INTEGER().type is NullType and fails to compile.
    dow = cast(func.strftime("%w", ClassSession.scheduled_start), Integer)

    stmt = (
        select(dow.label("dow"), func.sum(_counted()).label("counted"),
               func.sum(_present()).label("present"))
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
        .where(ClassSession.scheduled_start >= start)
        .group_by("dow")
    )
    stmt = _apply_department(stmt, department_id)

    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out = []
    for raw_dow, counted, present in db.execute(stmt).all():
        idx = (int(raw_dow) + 6) % 7                       # Sunday-first -> Monday-first
        c, p = int(counted or 0), int(present or 0)
        if not c:
            continue
        out.append({
            "weekday": idx, "label": names[idx], "counted": c, "present": p,
            "absence_pct": round(100.0 * (c - p) / c, 1),
            "attendance_pct": round(100.0 * p / c, 1),
        })
    out.sort(key=lambda r: r["weekday"])
    return out


def remaining_classes(db: Session, section_id: Optional[int], *, today: Optional[date] = None,
                      subject_id: Optional[int] = None, tz: str = "UTC") -> int:
    """Scheduled periods still to come for a section before the term ends.

    Counted from the TIMETABLE, not from calendar days: telling a student they can miss four
    more classes when only two remain is worse than telling them nothing. Holidays and weekends
    fall out naturally because a slot only occurs on its own weekday, and holiday dates are
    subtracted explicitly.
    """
    if section_id is None:
        return 0
    today = today or local_today(tz)

    term = db.scalars(select(AcademicTerm).where(AcademicTerm.is_active.is_(True))).first()
    if term is None or term.end_date <= today:
        return 0

    stmt = select(TimetableSlot).where(TimetableSlot.section_id == section_id)
    if subject_id is not None:
        stmt = stmt.where(TimetableSlot.subject_id == subject_id)
    slots = list(db.scalars(stmt))
    if not slots:
        return 0

    holidays = set(db.scalars(select(Holiday.date)))
    per_weekday: dict[int, int] = defaultdict(int)
    for s in slots:
        per_weekday[s.day_of_week] += 1

    total = 0
    day = today + timedelta(days=1)          # from tomorrow: today's classes may already be held
    while day <= term.end_date:
        if day not in holidays:
            total += per_weekday.get(day.weekday(), 0)
        day += timedelta(days=1)
    return total


def student_summary(db: Session, user: User, *, threshold: float = 75.0,
                    today: Optional[date] = None, tz: str = "UTC") -> dict:
    """Everything the student screen shows, in one query set."""
    profile = db.scalars(
        select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    section_id = profile.section_id if profile else None

    subjects = subject_breakdown(db, user.id)
    counted = sum(s["counted"] for s in subjects)
    present = sum(s["present"] for s in subjects)

    remaining = remaining_classes(db, section_id, today=today, tz=tz)
    overall = can_miss(present, counted, remaining, threshold)
    # "Attend N more classes in a row to reach the minimum" -- 0 when already there.
    overall.update({"counted": counted, "present": present,
                    "classes_needed": _classes_needed(present, counted, threshold)})

    for s in subjects:
        s_remaining = remaining_classes(db, section_id, today=today,
                                        subject_id=s["subject_id"], tz=tz)
        s["remaining"] = s_remaining
        s["projection"] = can_miss(s["present"], s["counted"], s_remaining, threshold)
        s["projection"]["classes_needed"] = _classes_needed(s["present"], s["counted"], threshold)

    return {
        "threshold_pct": threshold,
        "overall": overall,
        "subjects": subjects,
        "section_id": section_id,
    }


def attendance_calendar(db: Session, user_id: int, *, days: int = 60) -> List[dict]:
    """One entry per day the student had at least one class, for the month grid."""
    start = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(func.date(ClassSession.scheduled_start).label("day"),
               _effective().label("status"))
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .where(AttendanceRecordRow.user_id == user_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
        .where(ClassSession.scheduled_start >= start)
        .order_by("day")
    ).all()

    per_day: dict[str, List[str]] = defaultdict(list)
    for day, status in rows:
        per_day[str(day)].append(status)

    out = []
    for day, statuses in sorted(per_day.items()):
        # The worst status of the day is what the square shows: a student who missed one of
        # three periods should not see a clean green day.
        if any(s == AttendanceStatus.ABSENT.value for s in statuses):
            worst = AttendanceStatus.ABSENT.value
        elif any(s == AttendanceStatus.LATE.value for s in statuses):
            worst = AttendanceStatus.LATE.value
        elif all(s in EXCLUDED_FROM_TOTAL for s in statuses):
            worst = (AttendanceStatus.ON_LEAVE.value
                     if any(s == AttendanceStatus.ON_LEAVE.value for s in statuses)
                     else AttendanceStatus.EXCUSED.value)
        else:
            worst = AttendanceStatus.PRESENT.value
        out.append({"date": day, "status": worst, "periods": len(statuses),
                    "statuses": statuses})
    return out


def subject_breakdown(db: Session, user_id: int) -> List[dict]:
    """Per-subject percentage for one student."""
    stmt = (
        select(Subject.id, Subject.code, Subject.name,
               func.sum(_counted()).label("counted"), func.sum(_present()).label("present"))
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .join(Subject, Subject.id == ClassSession.subject_id)
        .where(AttendanceRecordRow.user_id == user_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
        .group_by(Subject.id, Subject.code, Subject.name)
        .order_by(Subject.code)
    )
    out = []
    for sid, code, name, counted, present in db.execute(stmt).all():
        c, p = int(counted or 0), int(present or 0)
        out.append({
            "subject_id": sid, "code": code, "name": name,
            "counted": c, "present": p,
            "attendance_pct": round(100.0 * p / c, 1) if c else None,
        })
    return out


# --------------------------------------------------------------------- today

def todays_periods(db: Session, actor: User, *, on: Optional[date] = None,
                   department_id: Optional[int] = None, tz: str = "UTC") -> List[dict]:
    """Today's timetable for a faculty member, each with whether it has been marked.

    "Which of my classes have I not marked yet" is the question a teacher opens the app to
    answer, so marked-status is resolved here rather than left to N follow-up requests.
    """
    from app.auth import is_faculty, is_super_admin

    on = on or local_today(tz)
    weekday = on.weekday()

    stmt = (
        select(TimetableSlot, Subject, Section)
        .join(Subject, Subject.id == TimetableSlot.subject_id)
        .join(Section, Section.id == TimetableSlot.section_id)
        .where(TimetableSlot.day_of_week == weekday)
        .order_by(TimetableSlot.start_minute)
    )
    if is_faculty(actor):
        stmt = stmt.where(TimetableSlot.faculty_id == actor.id)
    elif not is_super_admin(actor) and department_id is not None:
        stmt = stmt.where(Subject.department_id == department_id)

    slots = db.execute(stmt).all()
    if not slots:
        return []

    slot_ids = [s.TimetableSlot.id for s in slots]
    day_start = datetime.combine(on, datetime.min.time()).replace(tzinfo=timezone.utc)
    sessions = {
        s.timetable_slot_id: s
        for s in db.scalars(
            select(ClassSession)
            .where(ClassSession.timetable_slot_id.in_(slot_ids))
            .where(ClassSession.scheduled_start >= day_start - timedelta(days=1))
            .where(ClassSession.scheduled_start < day_start + timedelta(days=2))
            .where(ClassSession.deleted_at.is_(None))
        )
    }

    out = []
    for row in slots:
        slot, subject, section = row.TimetableSlot, row.Subject, row.Section
        sess = sessions.get(slot.id)
        out.append({
            "slot_id": slot.id,
            "session_id": sess.id if sess else None,
            "subject_code": subject.code,
            "subject_name": subject.name,
            "section_id": section.id,
            "section_label": f"{section.name}",
            "room": slot.room,
            "start_time": slot.start_time,
            "end_time": slot.end_time,
            "marked": bool(sess and sess.marked_at),
            "locked": bool(sess and sess.is_locked),
            "capture_method": sess.capture_method if sess else None,
        })
    return out


def org_summary(db: Session, *, department_id: Optional[int] = None,
                threshold: float = 75.0) -> dict:
    """Headline numbers for the top of a dashboard."""
    counted = func.sum(_counted())
    present = func.sum(_present())
    stmt = (
        select(counted, present)
        .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        .where(AttendanceRecordRow.deleted_at.is_(None))
        .where(ClassSession.deleted_at.is_(None))
    )
    stmt = _apply_department(stmt, department_id)
    row = db.execute(stmt).first()
    n_counted, n_present = int(row[0] or 0), int(row[1] or 0)

    low = defaulters(db, threshold=threshold, department_id=department_id, limit=10_000)
    at_risk = [d for d in low if d["attendance_pct"] >= threshold - 1]
    return {
        "records_counted": n_counted,
        "average_pct": round(100.0 * n_present / n_counted, 1) if n_counted else 0.0,
        "defaulters": len(low),
        "at_risk": len(at_risk),
        "threshold_pct": threshold,
    }


def _as_utc(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)
