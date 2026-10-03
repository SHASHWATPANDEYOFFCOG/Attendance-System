"""The marking flow: open a period, load the roster, save the register.

This is the screen used every working day, so the invariants that protect a teacher's work get
the tests: opening is idempotent, saving is all-or-nothing, a locked session refuses, and a
manual mark on a face-captured session becomes an override rather than destroying the evidence.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.auth import create_token
from app.crypto import hash_password
from app.db import SessionLocal
from app.models import (
    AcademicTerm,
    AttendanceRecordRow,
    AuditLog,
    CaptureMethod,
    ClassSession,
    Department,
    Program,
    Role,
    RosterEntry,
    Section,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
)


@pytest.fixture()
def klass(api):
    """A department with one subject, one section of 4 students, and a Monday 09:00 slot."""
    db = SessionLocal()
    pw = hash_password("password123")
    out: dict = {}
    try:
        term = AcademicTerm(name="T", start_date=date(2026, 1, 1),
                            end_date=date(2026, 12, 31), is_active=True)
        dept = Department(code="CSE", name="CSE")
        db.add_all([term, dept])
        db.commit()
        db.refresh(term)
        db.refresh(dept)

        prog = Program(department_id=dept.id, name="B.Tech")
        db.add(prog)
        db.commit()
        db.refresh(prog)
        sec = Section(program_id=prog.id, name="A", year=3, semester=5)
        subj = Subject(code="CS301", name="OS", department_id=dept.id)
        db.add_all([sec, subj])
        db.commit()
        db.refresh(sec)
        db.refresh(subj)

        prof = User(username="prof", display_name="Prof", role=Role.FACULTY,
                    password_hash=pw, department_id=dept.id)
        other = User(username="other", display_name="Other", role=Role.FACULTY,
                     password_hash=pw, department_id=dept.id)
        db.add_all([prof, other])
        db.commit()
        db.refresh(prof)
        db.refresh(other)

        students = []
        for i in range(4):
            u = User(username=f"s{i}", display_name=f"Student {i}", role=Role.STUDENT,
                     password_hash=pw, roll_number=f"R{i:03d}")
            db.add(u)
            db.commit()
            db.refresh(u)
            db.add(StudentProfile(user_id=u.id, section_id=sec.id, admission_year=2021))
            students.append(u.id)
        db.commit()

        # Scheduled on TODAY's weekday so `open_session` with no explicit date is valid.
        # Hardcoding Monday would make the whole suite fail on six days out of seven, since a
        # period may only be opened on the weekday it is scheduled for.
        slot = TimetableSlot(section_id=sec.id, subject_id=subj.id, faculty_id=prof.id,
                             term_id=term.id, day_of_week=date.today().weekday(),
                             start_minute=540, end_minute=590, room="LH-1")
        db.add(slot)
        db.commit()
        db.refresh(slot)

        out.update({
            "slot": slot.id, "section": sec.id, "subject": subj.id, "dept": dept.id,
            "prof": prof.id, "students": students,
            "prof_h": {"Authorization": f"Bearer {create_token(prof, 'access')}"},
            "other_h": {"Authorization": f"Bearer {create_token(other, 'access')}"},
        })
        return out
    finally:
        db.close()


def open_session(api, klass, headers=None, on=None):
    body = {"slot_id": klass["slot"]}
    if on:
        body["date"] = on
    return api.post("/api/attendance/sessions", json=body, headers=headers or klass["prof_h"])


def opened(api, klass, **kw):
    """open_session, asserting success — so a failure reports the status and body rather than
    surfacing later as an opaque KeyError: 'session'."""
    r = open_session(api, klass, **kw)
    assert r.status_code == 201, f"open failed: {r.status_code} {r.text}"
    return r.json()


# ------------------------------------------------------------------ opening

def test_open_creates_a_session_with_the_full_roster(api, klass):
    r = open_session(api, klass)
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["roster"]) == 4
    assert body["marked_count"] == 0
    assert body["session"]["subject_code"] == "CS301"
    assert all(row["status"] is None for row in body["roster"])


def test_opening_twice_returns_the_same_session(api, klass):
    """Two tabs, or two teachers, must not produce two registers for one period."""
    a = opened(api, klass)["session"]["id"]
    b = opened(api, klass)["session"]["id"]
    assert a == b

    db = SessionLocal()
    try:
        n = db.query(ClassSession).filter(
            ClassSession.timetable_slot_id == klass["slot"]).count()
        assert n == 1
    finally:
        db.close()


def test_roster_is_sorted_by_roll_number(api, klass):
    rows = opened(api, klass)["roster"]
    assert [r["roll_number"] for r in rows] == sorted(r["roll_number"] for r in rows)


def test_a_student_added_later_appears_on_reopen(api, klass):
    sid = opened(api, klass)["session"]["id"]

    db = SessionLocal()
    try:
        u = User(username="late", display_name="Late Joiner", role=Role.STUDENT,
                 password_hash=hash_password("password123"), roll_number="R999")
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(StudentProfile(user_id=u.id, section_id=klass["section"], admission_year=2021))
        db.commit()
    finally:
        db.close()

    body = opened(api, klass)
    assert body["session"]["id"] == sid
    assert len(body["roster"]) == 5


def test_faculty_cannot_open_a_period_they_do_not_teach(api, klass):
    r = open_session(api, klass, headers=klass["other_h"])
    assert r.status_code == 403
    assert "do not teach" in r.text.lower()


def test_open_rejects_an_unknown_slot(api, klass):
    r = api.post("/api/attendance/sessions", json={"slot_id": 9999}, headers=klass["prof_h"])
    assert r.status_code == 404


def test_open_refuses_a_date_on_the_wrong_weekday(api, klass):
    """A typo in the date would otherwise create a register for a class that never met, and
    every absence on it would count against the whole section."""
    wrong = date.today() + timedelta(days=1)
    r = api.post("/api/attendance/sessions",
                 json={"slot_id": klass["slot"], "date": wrong.isoformat()},
                 headers=klass["prof_h"])
    assert r.status_code == 422
    assert "scheduled on" in r.text


def test_open_accepts_the_same_weekday_a_week_earlier(api, klass):
    same_weekday = date.today() - timedelta(days=7)
    r = api.post("/api/attendance/sessions",
                 json={"slot_id": klass["slot"], "date": same_weekday.isoformat()},
                 headers=klass["prof_h"])
    assert r.status_code == 201


def test_sessions_route_is_not_shadowed_by_the_override_route(api, klass):
    """`/api/attendance/{record_id}` (PATCH) shares a prefix with `/api/attendance/sessions`
    (POST). Starlette resolves this correctly today by continuing past a method mismatch, but
    the two routes are one careless `methods=` argument away from colliding, so pin it."""
    r = api.post("/api/attendance/sessions", json={"slot_id": klass["slot"]},
                 headers=klass["prof_h"])
    assert r.status_code != 405, "the override route is shadowing /api/attendance/sessions"
    assert r.status_code == 201


# ------------------------------------------------------------------- saving

def test_saving_marks_the_whole_register(api, klass):
    sid = opened(api, klass)["session"]["id"]
    marks = [{"user_id": u, "status": "present"} for u in klass["students"]]
    marks[2]["status"] = "absent"

    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": marks}, headers=klass["prof_h"])
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 4

    body = api.get(f"/api/attendance/sessions/{sid}/roster",
                   headers=klass["prof_h"]).json()
    got = {row["user_id"]: row["status"] for row in body["roster"]}
    assert got[klass["students"][2]] == "absent"
    assert sum(1 for v in got.values() if v == "present") == 3
    assert body["marked_count"] == 4


def test_resaving_updates_rather_than_duplicates(api, klass):
    sid = opened(api, klass)["session"]["id"]
    first = [{"user_id": u, "status": "present"} for u in klass["students"]]
    api.post(f"/api/attendance/sessions/{sid}/records", json={"marks": first},
             headers=klass["prof_h"])

    second = [{"user_id": u, "status": "present"} for u in klass["students"]]
    second[0]["status"] = "late"
    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": second, "reason": "arrived after roll call"},
                 headers=klass["prof_h"]).json()
    assert r["created"] == 0 and r["updated"] == 1 and r["unchanged"] == 3

    db = SessionLocal()
    try:
        assert db.query(AttendanceRecordRow).filter(
            AttendanceRecordRow.session_id == sid).count() == 4
    finally:
        db.close()


def test_an_invalid_status_is_refused(api, klass):
    sid = opened(api, klass)["session"]["id"]
    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": klass["students"][0], "status": "needs_review"}]},
                 headers=klass["prof_h"])
    assert r.status_code == 422
    assert "cannot be set by hand" in r.text


def test_a_bad_status_rolls_the_whole_batch_back(api, klass):
    """All-or-nothing: a half-marked register looks complete and hides the missing half."""
    sid = opened(api, klass)["session"]["id"]
    marks = [{"user_id": u, "status": "present"} for u in klass["students"]]
    marks[-1]["status"] = "teleported"

    r = api.post(f"/api/attendance/sessions/{sid}/records", json={"marks": marks},
                 headers=klass["prof_h"])
    assert r.status_code == 422

    db = SessionLocal()
    try:
        assert db.query(AttendanceRecordRow).filter(
            AttendanceRecordRow.session_id == sid).count() == 0, "a partial save leaked through"
    finally:
        db.close()


def test_a_student_not_on_the_roster_is_reported_not_applied(api, klass):
    sid = opened(api, klass)["session"]["id"]
    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": klass["students"][0], "status": "present"},
                                 {"user_id": 4242, "status": "present"}]},
                 headers=klass["prof_h"]).json()
    assert r["created"] == 1
    assert r["not_on_roster"] == [4242]


def test_saving_is_audit_logged(api, klass):
    sid = opened(api, klass)["session"]["id"]
    api.post(f"/api/attendance/sessions/{sid}/records",
             json={"marks": [{"user_id": u, "status": "present"} for u in klass["students"]]},
             headers=klass["prof_h"])

    db = SessionLocal()
    try:
        entry = db.query(AuditLog).filter(AuditLog.action == "attendance_marked").one()
        assert "created=4" in entry.detail
    finally:
        db.close()


def test_faculty_cannot_save_to_another_teachers_session(api, klass):
    sid = opened(api, klass)["session"]["id"]
    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": klass["students"][0], "status": "present"}]},
                 headers=klass["other_h"])
    assert r.status_code == 403


def test_students_cannot_reach_the_marking_routes(api, klass, make_user):
    sid = opened(api, klass)["session"]["id"]
    _uid, student = make_user("pupil")
    assert api.get(f"/api/attendance/sessions/{sid}/roster",
                   headers=student).status_code == 403
    assert api.post(f"/api/attendance/sessions/{sid}/records",
                    json={"marks": [{"user_id": 1, "status": "present"}]},
                    headers=student).status_code == 403


# ------------------------------------------------------------------ locking

def test_a_locked_session_refuses_a_save(api, klass):
    sid = opened(api, klass)["session"]["id"]
    db = SessionLocal()
    try:
        db.get(ClassSession, sid).is_locked = True
        db.commit()
    finally:
        db.close()

    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": klass["students"][0], "status": "present"}]},
                 headers=klass["prof_h"])
    assert r.status_code == 409
    assert "correction request" in r.text.lower()


def test_lock_sweep_locks_only_stale_sessions(api, klass, make_user):
    """A session inside the edit window stays editable; one past it locks."""
    sid = opened(api, klass)["session"]["id"]
    db = SessionLocal()
    try:
        s = db.get(ClassSession, sid)
        s.scheduled_end = datetime.now(timezone.utc) - timedelta(hours=48)
        db.commit()

        fresh = ClassSession(title="Fresh", room="R2", owner_id=klass["prof"],
                             scheduled_start=datetime.now(timezone.utc) - timedelta(minutes=30),
                             scheduled_end=datetime.now(timezone.utc),
                             mode="kiosk", grace_minutes=10, min_presence_seconds=1500)
        db.add(fresh)
        db.commit()
        fresh_id = fresh.id
    finally:
        db.close()

    _uid, admin = make_user("root", role="super_admin")
    r = api.post("/api/admin/lock-stale-sessions", headers=admin)
    assert r.status_code == 200 and r.json()["locked"] == 1

    db = SessionLocal()
    try:
        assert db.get(ClassSession, sid).is_locked is True
        assert db.get(ClassSession, fresh_id).is_locked is False
    finally:
        db.close()


def test_lock_sweep_is_idempotent(api, klass, make_user):
    _uid, admin = make_user("root", role="super_admin")
    assert api.post("/api/admin/lock-stale-sessions", headers=admin).json()["locked"] >= 0
    assert api.post("/api/admin/lock-stale-sessions", headers=admin).json()["locked"] == 0


def test_lock_sweep_is_admin_only(api, klass):
    assert api.post("/api/admin/lock-stale-sessions",
                    headers=klass["prof_h"]).status_code == 403


# ---------------------------------------------- interaction with face capture

def test_a_manual_mark_on_a_face_session_becomes_an_override(api, klass):
    """The derived value and the human decision must BOTH survive: an override outranks the
    pipeline but never erases what the pipeline saw."""
    sid = opened(api, klass)["session"]["id"]
    uid = klass["students"][0]

    db = SessionLocal()
    try:
        s = db.get(ClassSession, sid)
        s.capture_method = CaptureMethod.FACE.value
        db.add(AttendanceRecordRow(session_id=sid, user_id=uid, status="absent",
                                   source=CaptureMethod.FACE.value, frames_matched=0))
        db.commit()
    finally:
        db.close()

    api.post(f"/api/attendance/sessions/{sid}/records",
             json={"marks": [{"user_id": uid, "status": "present",
                              "reason": "seen in class; camera missed them"}]},
             headers=klass["prof_h"])

    db = SessionLocal()
    try:
        row = db.query(AttendanceRecordRow).filter(
            AttendanceRecordRow.session_id == sid,
            AttendanceRecordRow.user_id == uid).one()
        assert row.status == "absent", "the derived value was destroyed"
        assert row.overridden_status == "present"
        assert row.effective_status == "present"
        assert row.overridden_by_id == klass["prof"]
    finally:
        db.close()
