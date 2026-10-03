"""Role-based access control across a real two-department organisation.

The question these answer is the one that matters: can an authenticated user reach data that is
not theirs by changing an id in the URL? Every check goes through the HTTP layer, not the
helper functions, because a guard that exists but is not wired into a route protects nothing.

Org built by the `org` fixture:

    CSE                              ECE
      Section CSE-A                    Section ECE-A
      Subject CS301                    Subject EC301
      hod.cse    (ADMIN, dept=CSE)     hod.ece    (ADMIN, dept=ECE)
      prof.cse   (FACULTY, assigned)   prof.ece   (FACULTY, assigned)
      stu.cse    (STUDENT)             stu.ece    (STUDENT)
      parent.cse (PARENT -> stu.cse)
    principal    (SUPER_ADMIN, no department)
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
    ClassSession,
    Department,
    FacultyAssignment,
    Program,
    Role,
    RosterEntry,
    Section,
    StudentProfile,
    Subject,
    User,
)


def _hdr(user: User) -> dict:
    return {"Authorization": f"Bearer {create_token(user, 'access')}"}


@pytest.fixture()
def org(api):
    """Two self-contained departments, each with a session that has real academic context."""
    db = SessionLocal()
    pw = hash_password("password123")
    out: dict = {}
    try:
        term = AcademicTerm(name="Term", start_date=date(2026, 1, 1),
                            end_date=date(2026, 12, 31), is_active=True)
        db.add(term)
        db.commit()
        db.refresh(term)
        out["term"] = term.id

        principal = User(username="principal", display_name="Principal",
                         role=Role.SUPER_ADMIN, password_hash=pw)
        db.add(principal)
        db.commit()
        db.refresh(principal)
        out["principal"] = principal.id
        out["principal_h"] = _hdr(principal)

        for code in ("cse", "ece"):
            dept = Department(code=code.upper(), name=f"{code.upper()} Department")
            db.add(dept)
            db.commit()
            db.refresh(dept)

            prog = Program(department_id=dept.id, name=f"B.Tech {code.upper()}")
            db.add(prog)
            db.commit()
            db.refresh(prog)

            sec = Section(program_id=prog.id, name="A", year=3, semester=5)
            db.add(sec)
            subj = Subject(code=f"{code.upper()}301", name=f"{code.upper()} Core",
                           department_id=dept.id)
            db.add(subj)
            db.commit()
            db.refresh(sec)
            db.refresh(subj)

            hod = User(username=f"hod.{code}", display_name=f"HOD {code}",
                       role=Role.ADMIN, password_hash=pw, department_id=dept.id)
            prof = User(username=f"prof.{code}", display_name=f"Prof {code}",
                        role=Role.FACULTY, password_hash=pw, department_id=dept.id)
            stu = User(username=f"stu.{code}", display_name=f"Student {code}",
                       role=Role.STUDENT, password_hash=pw, roll_number=f"R-{code}")
            db.add_all([hod, prof, stu])
            db.commit()
            for u in (hod, prof, stu):
                db.refresh(u)

            db.add(StudentProfile(user_id=stu.id, section_id=sec.id, admission_year=2021))
            db.add(FacultyAssignment(faculty_id=prof.id, subject_id=subj.id,
                                     section_id=sec.id, term_id=term.id))

            start = datetime.now(timezone.utc) - timedelta(minutes=5)
            sess = ClassSession(
                title=f"{code.upper()} Lecture", room=f"{code.upper()}-101",
                owner_id=prof.id, scheduled_start=start,
                scheduled_end=start + timedelta(minutes=50),
                mode="kiosk", grace_minutes=10, min_presence_seconds=1500,
                subject_id=subj.id, section_id=sec.id, term_id=term.id,
            )
            db.add(sess)
            db.commit()
            db.refresh(sess)
            db.add(RosterEntry(session_id=sess.id, user_id=stu.id))
            db.commit()

            out[f"{code}_dept"] = dept.id
            out[f"{code}_section"] = sec.id
            out[f"{code}_subject"] = subj.id
            out[f"{code}_hod"] = hod.id
            out[f"{code}_hod_h"] = _hdr(hod)
            out[f"{code}_prof"] = prof.id
            out[f"{code}_prof_h"] = _hdr(prof)
            out[f"{code}_stu"] = stu.id
            out[f"{code}_stu_h"] = _hdr(stu)
            out[f"{code}_session"] = sess.id

        parent = User(username="parent.cse", display_name="Parent CSE",
                      role=Role.PARENT, password_hash=pw)
        db.add(parent)
        db.commit()
        db.refresh(parent)
        prof_row = db.query(StudentProfile).filter(
            StudentProfile.user_id == out["cse_stu"]).one()
        prof_row.parent_id = parent.id
        db.commit()
        out["parent"] = parent.id
        out["parent_h"] = _hdr(parent)

        return out
    finally:
        db.close()


# ============================================================ department scoping

def test_hod_can_read_their_own_department(api, org):
    r = api.get(f"/api/sessions/{org['cse_session']}/attendance", headers=org["cse_hod_h"])
    assert r.status_code == 200


def test_hod_cannot_read_another_department(api, org):
    """The headline check: changing the id in the URL must not cross the boundary."""
    r = api.get(f"/api/sessions/{org['ece_session']}/attendance", headers=org["cse_hod_h"])
    assert r.status_code == 403, r.text
    assert "another department" in r.text.lower()


def test_hod_cannot_override_a_record_in_another_department(api, org):
    api.get(f"/api/sessions/{org['ece_session']}/attendance", headers=org["principal_h"])
    db = SessionLocal()
    try:
        rec = db.query(AttendanceRecordRow).filter(
            AttendanceRecordRow.session_id == org["ece_session"]).first()
        assert rec is not None, "no record to attempt an override against"
        rid = rec.id
    finally:
        db.close()

    r = api.patch(f"/api/attendance/{rid}",
                  json={"status": "present", "reason": "not my department"},
                  headers=org["cse_hod_h"])
    assert r.status_code == 403, r.text


def test_hod_cannot_recompute_another_department(api, org):
    r = api.post(f"/api/sessions/{org['ece_session']}/recompute", headers=org["cse_hod_h"])
    assert r.status_code == 403


def test_hod_cannot_export_another_departments_csv(api, org):
    r = api.get(f"/api/reports/attendance.csv?session_id={org['ece_session']}",
                headers=org["cse_hod_h"])
    assert r.status_code == 403


def test_super_admin_crosses_every_department(api, org):
    for code in ("cse", "ece"):
        r = api.get(f"/api/sessions/{org[f'{code}_session']}/attendance",
                    headers=org["principal_h"])
        assert r.status_code == 200, f"{code}: {r.text}"


def test_super_admin_reaches_admin_only_routes(api, org):
    """Regression: `is_admin` once matched only Role.ADMIN, locking the super admin out of
    the audit log and the retention sweep on their own system."""
    assert api.get("/api/audit", headers=org["principal_h"]).status_code == 200
    assert api.post("/api/admin/retention", headers=org["principal_h"]).status_code == 200


def test_admin_without_a_department_cannot_read_a_scoped_session(api, org, make_user):
    """An unscoped admin is refused a scoped resource rather than waved through."""
    _uid, headers = make_user("floating.admin", role="admin")
    r = api.get(f"/api/sessions/{org['cse_session']}/attendance", headers=headers)
    assert r.status_code == 403
    assert "no department" in r.text.lower()


# ================================================================ faculty scope

def test_assigned_faculty_can_read_their_session(api, org):
    r = api.get(f"/api/sessions/{org['cse_session']}/attendance", headers=org["cse_prof_h"])
    assert r.status_code == 200


def test_faculty_cannot_read_another_faculties_session(api, org):
    r = api.get(f"/api/sessions/{org['ece_session']}/attendance", headers=org["cse_prof_h"])
    assert r.status_code == 403
    assert "do not teach" in r.text.lower()


def test_faculty_assignment_grants_access_without_ownership(api, org):
    """A session generated from a timetable slot is owned by whoever the slot names, but the
    teacher of record must still get in via FacultyAssignment."""
    db = SessionLocal()
    try:
        sess = db.get(ClassSession, org["cse_session"])
        sess.owner_id = org["principal"]          # someone else owns it now
        db.commit()
    finally:
        db.close()

    r = api.get(f"/api/sessions/{org['cse_session']}/attendance", headers=org["cse_prof_h"])
    assert r.status_code == 200, "the assigned teacher lost access when ownership moved"


def test_faculty_loses_access_when_the_assignment_is_removed(api, org):
    db = SessionLocal()
    try:
        sess = db.get(ClassSession, org["cse_session"])
        sess.owner_id = org["principal"]
        db.query(FacultyAssignment).filter(
            FacultyAssignment.faculty_id == org["cse_prof"]).delete()
        db.commit()
    finally:
        db.close()

    r = api.get(f"/api/sessions/{org['cse_session']}/attendance", headers=org["cse_prof_h"])
    assert r.status_code == 403


# ======================================================================= student

def test_student_cannot_read_another_students_session(api, org):
    r = api.get(f"/api/sessions/{org['ece_session']}/attendance", headers=org["cse_stu_h"])
    assert r.status_code == 403


def test_student_cannot_reach_staff_surfaces(api, org):
    h = org["cse_stu_h"]
    assert api.get("/api/cameras", headers=h).status_code == 403
    assert api.get("/api/audit", headers=h).status_code == 403
    assert api.get("/api/live/stream", headers=h).status_code == 403
    assert api.post("/api/admin/retention", headers=h).status_code == 403


def test_student_dashboard_is_self_scoped(api, org):
    body = api.get("/api/dashboard", headers=org["cse_stu_h"]).json()
    assert body["scope"] == "self"
    assert body["cameras"] == []


# ======================================================================== parent

def test_parent_may_read_their_linked_student(api, org):
    from app.auth import assert_can_read_user
    db = SessionLocal()
    try:
        parent = db.get(User, org["parent"])
        assert_can_read_user(parent, org["cse_stu"], db)          # must not raise
    finally:
        db.close()


def test_parent_may_not_read_an_unlinked_student(api, org):
    from fastapi import HTTPException

    from app.auth import assert_can_read_user
    db = SessionLocal()
    try:
        parent = db.get(User, org["parent"])
        with pytest.raises(HTTPException) as exc:
            assert_can_read_user(parent, org["ece_stu"], db)
        assert exc.value.status_code == 403
    finally:
        db.close()


def test_parent_cannot_reach_staff_surfaces(api, org):
    """Regression: these guards were written as `if is_student(...)`, so PARENT -- a role added
    later -- fell straight through into the staff branch and could open every classroom's live
    camera feed."""
    h = org["parent_h"]
    assert api.get("/api/cameras", headers=h).status_code == 403
    assert api.get("/api/audit", headers=h).status_code == 403
    assert api.get("/api/live/stream", headers=h).status_code == 403
    assert api.post("/api/admin/retention", headers=h).status_code == 403
    assert api.post(f"/api/sessions/{org['cse_session']}/recompute",
                    headers=h).status_code == 403


def test_parent_sees_only_their_own_childs_row(api, org):
    """The parent's child is on this roster, so the session is visible -- but the response must
    contain exactly one record, and no cohort summary."""
    r = api.get(f"/api/sessions/{org['cse_session']}/attendance", headers=org["parent_h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert [rec["user_id"] for rec in body["records"]] == [org["cse_stu"]]
    assert body["summary"] is None, "a parent received the cohort summary"


def test_parent_blocked_from_a_session_their_child_is_not_in(api, org):
    r = api.get(f"/api/sessions/{org['ece_session']}/attendance", headers=org["parent_h"])
    assert r.status_code == 403


def test_parent_dashboard_is_self_scoped_to_the_linked_student(api, org):
    body = api.get("/api/dashboard", headers=org["parent_h"]).json()
    assert body["scope"] == "self"
    assert body["cameras"] == []
    assert body["viewing_student_id"] == org["cse_stu"]
    assert [s["id"] for s in body["linked_students"]] == [org["cse_stu"]]


def test_parent_cannot_enroll_or_erase_another_persons_biometrics(api, org):
    h = org["parent_h"]
    assert api.delete(f"/api/users/{org['cse_stu']}/biometrics", headers=h).status_code == 403
    assert api.delete(f"/api/users/{org['ece_stu']}/biometrics", headers=h).status_code == 403


# ================================================================ marking guard

def test_a_locked_session_cannot_be_marked(api, org):
    from fastapi import HTTPException

    from app.auth import assert_can_mark_session
    db = SessionLocal()
    try:
        sess = db.get(ClassSession, org["cse_session"])
        sess.is_locked = True
        db.commit()
        prof = db.get(User, org["cse_prof"])

        with pytest.raises(HTTPException) as exc:
            assert_can_mark_session(prof, sess)
        assert exc.value.status_code == 409
        assert "correction request" in exc.value.detail.lower()
    finally:
        db.close()


def test_an_unlocked_session_can_be_marked_by_its_teacher(api, org):
    from app.auth import assert_can_mark_session
    db = SessionLocal()
    try:
        sess = db.get(ClassSession, org["cse_session"])
        prof = db.get(User, org["cse_prof"])
        assert_can_mark_session(prof, sess)                        # must not raise
    finally:
        db.close()


def test_a_faculty_from_another_department_cannot_mark(api, org):
    from fastapi import HTTPException

    from app.auth import assert_can_mark_session
    db = SessionLocal()
    try:
        sess = db.get(ClassSession, org["cse_session"])
        intruder = db.get(User, org["ece_prof"])
        with pytest.raises(HTTPException) as exc:
            assert_can_mark_session(intruder, sess)
        assert exc.value.status_code == 403
    finally:
        db.close()


# =================================================================== token rules

def test_a_refresh_token_is_rejected_as_an_access_token(api, org):
    db = SessionLocal()
    try:
        user = db.get(User, org["principal"])
        refresh = create_token(user, "refresh")
    finally:
        db.close()
    r = api.get("/api/dashboard", headers={"Authorization": f"Bearer {refresh}"})
    assert r.status_code == 401


def test_a_disabled_account_is_rejected(api, org):
    db = SessionLocal()
    try:
        user = db.get(User, org["cse_hod"])
        user.is_active = False
        db.commit()
    finally:
        db.close()
    assert api.get("/api/dashboard", headers=org["cse_hod_h"]).status_code == 401
