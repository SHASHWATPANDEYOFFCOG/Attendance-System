"""Attendance arithmetic and the analytics aggregations.

The percentage rule is the thing most worth pinning down: approved leave leaves the
DENOMINATOR, on-duty counts as PRESENT, and an override outranks the derived status. Getting
any of those wrong changes whether a real student passes.
"""
from __future__ import annotations

import pytest

from app.analytics_service import _classes_needed, can_miss


# ------------------------------------------------------------- can-miss counter
# "You can miss N more classes" is the feature students open the app for, so it gets the
# tightest tests in the suite.

def test_can_miss_on_a_clean_75_percent_boundary():
    # 30 attended of 40 held (75.0%), 10 still to come.
    # Missing m: (30 + 10 - m) / 50 >= 0.75  ->  40 - m >= 37.5  ->  m <= 2.5  ->  2
    r = can_miss(present=30, counted=40, remaining=10, threshold=75.0)
    assert r["can_miss"] == 2
    assert r["reachable"] is True
    assert r["at_risk"] is False


def test_can_miss_never_returns_negative():
    """A student already far below must be told 0, not a negative number."""
    r = can_miss(present=10, counted=40, remaining=5, threshold=75.0)
    assert r["can_miss"] == 0
    assert r["at_risk"] is True


def test_can_miss_flags_an_unreachable_target():
    """If attending every remaining class still misses the threshold, say so rather than
    implying the student can recover."""
    r = can_miss(present=10, counted=40, remaining=5, threshold=75.0)
    assert r["reachable"] is False
    assert r["can_miss"] == 0
    # 15 of 45 = 33.3% even with a perfect record from here
    assert r["projected_pct"] == pytest.approx(33.3, abs=0.1)


def test_can_miss_with_a_perfect_record():
    r = can_miss(present=40, counted=40, remaining=10, threshold=75.0)
    # (40 + 10 - m)/50 >= .75 -> m <= 12.5, but only 10 remain
    assert r["can_miss"] == 10
    assert r["projected_pct"] == 100.0


def test_can_miss_with_no_classes_remaining_is_zero():
    r = can_miss(present=30, counted=40, remaining=0, threshold=75.0)
    assert r["can_miss"] == 0
    assert r["current_pct"] == 75.0


def test_can_miss_handles_an_empty_term():
    r = can_miss(present=0, counted=0, remaining=0, threshold=75.0)
    assert r["can_miss"] == 0
    assert r["projected_pct"] == 0.0


def test_can_miss_exact_boundary_is_not_off_by_one():
    """The floating-point trap: 0.75 * 4 == 3.0 must count as meeting the threshold."""
    r = can_miss(present=3, counted=4, remaining=0, threshold=75.0)
    assert r["at_risk"] is False, "75.0% exactly must not be flagged as below 75%"

    # 3 of 4 with 4 to come: (3+4-m)/8 >= .75 -> m <= 1
    r2 = can_miss(present=3, counted=4, remaining=4, threshold=75.0)
    assert r2["can_miss"] == 1


@pytest.mark.parametrize("present,counted,remaining,expected", [
    (0, 0, 10, 2),        # nothing held yet: (10-m)/10 >= .75 -> m <= 2.5 -> 2
    (9, 12, 8, 2),        # (9+8-m)/20 >= .75 -> m <= 2
    (75, 100, 0, 0),
    (74, 100, 1, 0),      # (74+1-m)/101 >= .75 -> 75-m >= 75.75 -> unreachable
])
def test_can_miss_table(present, counted, remaining, expected):
    assert can_miss(present, counted, remaining, 75.0)["can_miss"] == expected


# ------------------------------------------------------- shortfall (recovery)

def test_classes_needed_to_recover():
    # 60 of 100 = 60%. Need n: (60+n)/(100+n) >= .75 -> n >= 60
    assert _classes_needed(60, 100, 75.0) == 60


def test_classes_needed_is_zero_when_already_above():
    assert _classes_needed(80, 100, 75.0) == 0
    assert _classes_needed(75, 100, 75.0) == 0        # exactly at threshold


def test_classes_needed_at_a_hundred_percent_threshold_is_unreachable():
    assert _classes_needed(50, 100, 100.0) == -1


# ============================================================ HTTP aggregations

@pytest.fixture()
def staff(api, make_user):
    _uid, headers = make_user("root", role="super_admin")
    return headers


def test_analytics_routes_are_staff_only(api, make_user):
    _uid, student = make_user("alice")
    for path in ("/api/analytics/summary", "/api/analytics/trend",
                 "/api/analytics/weekday", "/api/reports/defaulters",
                 "/api/timetable/today"):
        assert api.get(path, headers=student).status_code == 403, path


def test_analytics_routes_reject_anonymous(api):
    for path in ("/api/analytics/summary", "/api/reports/defaulters"):
        assert api.get(path, headers={}).status_code in (401, 403), path


def test_summary_on_an_empty_database(api, staff):
    """Empty is a real state -- it must return zeros, not divide by zero."""
    body = api.get("/api/analytics/summary", headers=staff).json()
    assert body["records_counted"] == 0
    assert body["average_pct"] == 0.0
    assert body["defaulters"] == 0


def test_trend_and_weekday_on_an_empty_database(api, staff):
    trend = api.get("/api/analytics/trend", headers=staff).json()
    assert trend["dates"] == [] and trend["series"] == []
    weekday = api.get("/api/analytics/weekday", headers=staff).json()
    assert weekday["profile"] == []


def test_defaulters_on_an_empty_database(api, staff):
    body = api.get("/api/reports/defaulters", headers=staff).json()
    assert body["count"] == 0 and body["defaulters"] == []


def test_timetable_today_with_no_slots(api, staff):
    body = api.get("/api/timetable/today", headers=staff).json()
    assert body["periods"] == []
    assert "date" in body


def test_hod_cannot_widen_scope_to_another_department(api, make_user):
    """An HOD passing ?department_id= for someone else's department must be refused, not
    silently served their own data."""
    from app.db import SessionLocal
    from app.models import Department

    db = SessionLocal()
    try:
        a, b = Department(code="AA", name="A"), Department(code="BB", name="B")
        db.add_all([a, b])
        db.commit()
        a_id, b_id = a.id, b.id
    finally:
        db.close()

    _uid, hod = make_user("hod.a", role="admin", department_id=a_id)
    assert api.get(f"/api/reports/defaulters?department_id={b_id}",
                   headers=hod).status_code == 403
    assert api.get(f"/api/analytics/summary?department_id={b_id}",
                   headers=hod).status_code == 403
    # Their own department is fine.
    assert api.get(f"/api/reports/defaulters?department_id={a_id}",
                   headers=hod).status_code == 200


def test_student_summary_is_self_scoped(api, make_user):
    """A student may read their own summary and nobody else's."""
    a_id, a = make_user("alice")
    b_id, _b = make_user("bob")

    own = api.get("/api/me/summary", headers=a)
    assert own.status_code == 200
    assert own.json()["student"]["id"] == a_id

    assert api.get(f"/api/me/summary?user_id={b_id}", headers=a).status_code == 403


def test_student_summary_on_an_empty_record(api, make_user):
    """A student with no classes yet must get zeros, not a crash or a fake 100%."""
    _id, h = make_user("newbie")
    body = api.get("/api/me/summary", headers=h).json()
    assert body["overall"]["counted"] == 0
    assert body["overall"]["can_miss"] == 0
    assert body["subjects"] == []
    assert body["calendar"] == []


def test_staff_may_read_a_students_summary(api, make_user):
    sid, _s = make_user("pupil")
    _fid, staff = make_user("prof", role="faculty")
    r = api.get(f"/api/me/summary?user_id={sid}", headers=staff)
    assert r.status_code == 200
    assert r.json()["student"]["id"] == sid


def test_remaining_classes_is_zero_without_a_section(api):
    """No section means no timetable, so there is nothing left to attend -- and the can-miss
    counter must say 0 rather than inventing headroom."""
    from app.analytics_service import remaining_classes
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        assert remaining_classes(db, None) == 0
        assert remaining_classes(db, 9999) == 0
    finally:
        db.close()


def test_remaining_classes_counts_the_timetable_not_calendar_days(api):
    """Two slots a week over two remaining weeks is 4 classes, not 14 days."""
    from datetime import date, timedelta

    from app.analytics_service import remaining_classes
    from app.db import SessionLocal
    from app.models import (
        AcademicTerm, Department, Holiday, Program, Section, Subject, TimetableSlot, User, Role,
    )
    from app.crypto import hash_password

    db = SessionLocal()
    try:
        today = date(2026, 8, 3)                       # a Monday, fixed so the test is stable
        term = AcademicTerm(name="TT", start_date=today - timedelta(days=30),
                            end_date=today + timedelta(days=14), is_active=True)
        dept = Department(code="XX", name="X")
        db.add_all([term, dept])
        db.commit()
        db.refresh(term)
        db.refresh(dept)

        prog = Program(department_id=dept.id, name="P")
        db.add(prog)
        db.commit()
        db.refresh(prog)
        sec = Section(program_id=prog.id, name="A", year=1, semester=1)
        subj = Subject(code="XX101", name="X", department_id=dept.id)
        prof = User(username="p", display_name="P", role=Role.FACULTY,
                    password_hash=hash_password("password123"))
        db.add_all([sec, subj, prof])
        db.commit()
        for o in (sec, subj, prof):
            db.refresh(o)

        # Tuesday and Thursday, one period each.
        for dow in (1, 3):
            db.add(TimetableSlot(section_id=sec.id, subject_id=subj.id, faculty_id=prof.id,
                                 term_id=term.id, day_of_week=dow, start_minute=540,
                                 end_minute=590, room="R"))
        db.commit()

        # 14 days from Tue 4 Aug to Mon 17 Aug -> Tue/Thu on 4,6,11,13 = 4 classes.
        assert remaining_classes(db, sec.id, today=today) == 4

        # Declaring one of those a holiday removes exactly one class.
        db.add(Holiday(date=date(2026, 8, 6), name="Holiday", applies_to=None))
        db.commit()
        assert remaining_classes(db, sec.id, today=today) == 3
    finally:
        db.close()


def test_super_admin_may_narrow_to_any_department(api, make_user):
    from app.db import SessionLocal
    from app.models import Department

    db = SessionLocal()
    try:
        d = Department(code="ZZ", name="Z")
        db.add(d)
        db.commit()
        did = d.id
    finally:
        db.close()

    _uid, root = make_user("root", role="super_admin")
    assert api.get(f"/api/analytics/summary?department_id={did}",
                   headers=root).status_code == 200
