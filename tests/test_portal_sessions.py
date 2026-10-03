"""Phase 4: session lifecycle, timetable automation, QR marking, reasons, history, holidays."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

CAMPUS = (18.5204, 73.8567)        # any fixed point; tests place students relative to it


def _db():
    from app.db import SessionLocal

    return SessionLocal()


@pytest.fixture()
def klass(api, make_user):
    """A CSE section with 4 approved students, 1 pending, a teacher, a term and a subject."""
    from app import settings_service
    from app.models import (AcademicTerm, Batch, Department, FacultyAssignment, Program,
                            Section, StudentProfile, Subject)
    from app.runtime import cfg

    _, admin = make_user("root", role="super_admin")
    t_id, t_h = make_user("teach", role="faculty")
    other_t, other_h = make_user("other.teach", role="faculty")
    db = _db()
    d = Department(code="CSE", name="CS")
    db.add(d)
    db.flush()
    p = Program(department_id=d.id, name="B.Tech CSE", duration_years=4)
    b = Batch(label="2023-2027", start_year=2023, end_year=2027)
    db.add_all([p, b])
    db.flush()
    sec = Section(program_id=p.id, name="A", year=2, semester=3, batch_id=b.id)
    subj = Subject(code="CS301", name="Data Structures", department_id=d.id)
    term = AcademicTerm(name="T", start_date=date(2020, 1, 1), end_date=date(2099, 1, 1),
                        is_active=True)
    db.add_all([sec, subj, term])
    db.flush()
    db.add(FacultyAssignment(faculty_id=t_id, subject_id=subj.id, section_id=sec.id,
                             term_id=term.id))
    ids = {"section": sec.id, "subject": subj.id, "term": term.id, "dept": d.id}
    db.commit()
    db.close()

    students, headers = [], {}
    for i in range(4):
        uid, h = make_user(f"stu{i}", roll_number=f"R{i}")
        students.append(uid)
        headers[uid] = h
    pend_id, pend_h = make_user("pending.stu", roll_number="RP")
    db = _db()
    for uid in students:
        db.add(StudentProfile(user_id=uid, section_id=ids["section"], status="approved",
                              department_id=ids["dept"]))
    db.add(StudentProfile(user_id=pend_id, section_id=ids["section"], status="pending",
                          department_id=ids["dept"]))
    db.commit()
    settings_service.update(db, cfg, {"campus_lat": CAMPUS[0], "campus_lng": CAMPUS[1],
                                      "geofence_radius_m": 200}, None)
    db.commit()
    db.close()
    return {**ids, "admin": admin, "teacher": t_id, "teacher_h": t_h, "other_h": other_h,
            "students": students, "h": headers, "pending": pend_id, "pending_h": pend_h}


def _make_session(klass, *, started_minutes_ago=2, length=50, state="active"):
    from app.models import ClassSession, RosterEntry
    from app.session_code import new_secret

    now = datetime.now(timezone.utc)
    db = _db()
    s = ClassSession(title="CS301 Period", room="LH-1", owner_id=klass["teacher"],
                     scheduled_start=now - timedelta(minutes=started_minutes_ago),
                     scheduled_end=now - timedelta(minutes=started_minutes_ago) + timedelta(minutes=length),
                     subject_id=klass["subject"], section_id=klass["section"],
                     term_id=klass["term"], capture_method="manual", state=state,
                     code_secret=new_secret())
    db.add(s)
    db.flush()
    for uid in klass["students"] + [klass["pending"]]:
        db.add(RosterEntry(session_id=s.id, user_id=uid))
    db.commit()
    sid = s.id
    db.close()
    return sid


def _code(sid):
    from app.models import ClassSession
    from app.session_code import current

    db = _db()
    secret = db.get(ClassSession, sid).code_secret
    db.close()
    return current(secret, 30)[0]


def _qr(api, klass, uid, sid, *, code=None, lat=CAMPUS[0], lng=CAMPUS[1], acc=15):
    return api.post("/api/attendance/qr", json={"session_id": sid, "code": code or _code(sid),
                                                "lat": lat, "lng": lng, "accuracy": acc},
                    headers=klass["h"].get(uid) or klass["pending_h"])


# --------------------------------------------------------------------------- QR

def test_qr_mark_succeeds_inside_geofence_with_current_code(api, klass):
    sid = _make_session(klass)
    uid = klass["students"][0]
    r = _qr(api, klass, uid, sid)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "present"
    live = api.get(f"/api/sessions/{sid}/live", headers=klass["teacher_h"]).json()
    row = next(x for x in live["roster"] if x["user_id"] == uid)
    assert row["status"] == "present" and row["method"] == "qr"


def test_qr_rejects_outside_geofence(api, klass):
    sid = _make_session(klass)
    r = _qr(api, klass, klass["students"][0], sid, lat=CAMPUS[0] + 0.05)     # ~5.5 km north
    assert r.status_code == 403
    assert "outside campus" in r.json()["detail"]["message"]


def test_qr_rejects_imprecise_location(api, klass):
    sid = _make_session(klass)
    r = _qr(api, klass, klass["students"][0], sid, acc=2000)
    assert r.status_code == 403 and "imprecise" in r.json()["detail"]["message"]


def test_qr_rejects_wrong_or_expired_code(api, klass):
    sid = _make_session(klass)
    r = _qr(api, klass, klass["students"][0], sid, code="000000" if _code(sid) != "000000" else "111111")
    assert r.status_code == 422 and "code" in r.json()["detail"]["message"]
    # A code from five minutes ago is dead.
    from app.models import ClassSession
    from app.session_code import _code as raw

    db = _db()
    secret = db.get(ClassSession, sid).code_secret
    db.close()
    import time

    stale = raw(secret, int(time.time() // 30) - 10)
    r = _qr(api, klass, klass["students"][0], sid, code=stale)
    assert r.status_code == 422


def test_qr_rejects_outside_time_window(api, klass):
    sid = _make_session(klass, started_minutes_ago=25)       # late window is 20 minutes
    r = _qr(api, klass, klass["students"][0], sid)
    assert r.status_code == 409 and "window has closed" in r.json()["detail"]["message"]


def test_qr_marks_late_between_present_and_late_windows(api, klass):
    sid = _make_session(klass, started_minutes_ago=15)
    r = _qr(api, klass, klass["students"][0], sid)
    assert r.status_code == 200 and r.json()["status"] == "late"


def test_qr_rejects_already_marked_and_double_submit(api, klass):
    sid = _make_session(klass)
    uid = klass["students"][1]
    first = _qr(api, klass, uid, sid)
    second = _qr(api, klass, uid, sid)
    assert first.status_code == 200
    assert second.status_code == 409 and "already marked" in second.json()["detail"]["message"]
    from app.models import AttendanceRecordRow

    db = _db()
    n = db.query(AttendanceRecordRow).filter_by(session_id=sid, user_id=uid).count()
    db.close()
    assert n == 1


def test_concurrent_marks_never_create_two_records(api, klass):
    """Two writers racing for the same student and session: exactly one row."""
    from concurrent.futures import ThreadPoolExecutor

    from app.models import AttendanceRecordRow, ClassSession, User
    from app.runtime import cfg
    from app.session_service import record_mark

    sid = _make_session(klass)
    uid = klass["students"][2]

    def go(method):
        db = _db()
        try:
            s = db.get(ClassSession, sid)
            u = db.get(User, uid)
            return record_mark(db, s, u, method, cfg, status="present")[1]
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        created = list(pool.map(go, ["qr", "mobile", "cctv", "qr"]))
    db = _db()
    n = db.query(AttendanceRecordRow).filter_by(session_id=sid, user_id=uid).count()
    db.close()
    assert n == 1
    assert created.count(True) == 1


def test_pending_student_and_non_member_cannot_self_mark(api, klass, make_user):
    sid = _make_session(klass)
    r = _qr(api, klass, klass["pending"], sid)
    assert r.status_code == 403 and "awaiting approval" in r.json()["detail"]["message"]

    from app.models import StudentProfile

    outsider, oh = make_user("outsider")
    db = _db()
    db.add(StudentProfile(user_id=outsider, status="approved"))
    db.commit()
    db.close()
    r = api.post("/api/attendance/qr", json={"session_id": sid, "code": _code(sid),
                                             "lat": CAMPUS[0], "lng": CAMPUS[1]}, headers=oh)
    assert r.status_code == 403 and "not enrolled" in r.json()["detail"]["message"]


def test_retry_limit_blocks_after_three_failures(api, klass):
    sid = _make_session(klass)
    uid = klass["students"][3]
    for _ in range(3):
        assert _qr(api, klass, uid, sid, lat=CAMPUS[0] + 1).status_code == 403
    r = _qr(api, klass, uid, sid)                          # even a valid attempt is now refused
    assert r.status_code == 429
    from app.models import SelfMarkAttempt

    db = _db()
    assert db.query(SelfMarkAttempt).filter_by(session_id=sid, user_id=uid, success=False).count() == 3
    db.close()


def test_geofence_fails_closed_when_campus_not_configured(api, klass):
    from app import settings_service
    from app.runtime import cfg

    db = _db()
    settings_service.update(db, cfg, {"campus_lat": None, "campus_lng": None}, None)
    db.commit()
    db.close()
    sid = _make_session(klass)
    r = _qr(api, klass, klass["students"][0], sid)
    assert r.status_code == 403 and "not been configured" in r.json()["detail"]["message"]


def test_inactive_session_refuses(api, klass):
    sid = _make_session(klass, state="scheduled")
    r = _qr(api, klass, klass["students"][0], sid)
    assert r.status_code == 409 and "not started" in r.json()["detail"]["message"]


# ------------------------------------------------------------------- lifecycle

def test_close_marks_remaining_absent_and_leave_covered_on_leave(api, klass):
    from app.models import AttendanceRecordRow, LeaveRequest

    sid = _make_session(klass)
    s0, s1, s2, _s3 = klass["students"]
    _qr(api, klass, s0, sid)
    today = datetime.now(timezone.utc).date()
    db = _db()
    db.add(LeaveRequest(requester_id=s1, type="medical", from_date=today - timedelta(days=1),
                        to_date=today + timedelta(days=1), reason="flu", status="approved"))
    db.commit()
    db.close()

    r = api.post(f"/api/sessions/{sid}/stop", headers=klass["teacher_h"])
    assert r.status_code == 200, r.text
    db = _db()
    rows = {r.user_id: r for r in db.query(AttendanceRecordRow).filter_by(session_id=sid)}
    db.close()
    assert rows[s0].effective_status == "present"
    assert rows[s1].effective_status == "on_leave"
    assert rows[s2].effective_status == "absent" and rows[s2].source == "system"
    assert klass["pending"] not in rows                     # pending students are never marked
    again = api.post(f"/api/sessions/{sid}/stop", headers=klass["teacher_h"])
    assert again.status_code == 409


def test_approved_leave_rewrites_already_closed_absences(api, klass):
    from app.models import AttendanceRecordRow, LeaveRequest, User
    from app.runtime import cfg
    from app.session_service import apply_leave

    sid = _make_session(klass)
    api.post(f"/api/sessions/{sid}/stop", headers=klass["teacher_h"])
    uid = klass["students"][2]
    today = datetime.now(timezone.utc).date()
    db = _db()
    leave = LeaveRequest(requester_id=uid, type="medical", from_date=today - timedelta(days=1),
                         to_date=today + timedelta(days=1), reason="x", status="approved")
    db.add(leave)
    db.commit()
    assert apply_leave(db, leave, cfg, db.get(User, klass["teacher"])) == 1
    db.commit()
    row = db.query(AttendanceRecordRow).filter_by(session_id=sid, user_id=uid).one()
    db.close()
    assert row.effective_status == "on_leave"


def test_scheduler_opens_starts_and_closes_from_the_timetable(api, klass):
    from app.clock import tz_of, zone
    from app.models import ClassSession, TimetableSlot
    from app.runtime import cfg
    from app.session_service import tick

    local = datetime.now(timezone.utc).astimezone(zone(tz_of(cfg)))
    minute = local.hour * 60 + local.minute
    if minute < 2 or minute > 24 * 60 - 3:
        pytest.skip("too close to local midnight for a same-day slot")
    db = _db()
    db.add(TimetableSlot(section_id=klass["section"], subject_id=klass["subject"],
                         faculty_id=klass["teacher"], term_id=klass["term"],
                         day_of_week=local.weekday(), start_minute=minute - 1,
                         end_minute=min(minute + 1, 24 * 60 - 1), room="LH-1"))
    db.commit()
    assert tick(db, cfg)["started"] == 1
    sess = db.query(ClassSession).filter_by(state="active").one()
    assert sess.code_secret
    assert tick(db, cfg)["started"] == 0                    # idempotent
    out = tick(db, cfg, now=sess.scheduled_end + timedelta(seconds=1))
    assert out["closed"] == 1
    db.refresh(sess)
    assert sess.state == "closed"
    db.close()


def test_no_session_on_a_holiday(api, klass):
    from app.models import Holiday, TimetableSlot

    today = datetime.now(timezone.utc).date()
    db = _db()
    slot = TimetableSlot(section_id=klass["section"], subject_id=klass["subject"],
                         faculty_id=klass["teacher"], term_id=klass["term"],
                         day_of_week=today.weekday(), start_minute=600, end_minute=650,
                         room="LH-1")
    db.add_all([slot, Holiday(date=today, name="Founders Day")])
    db.commit()
    slot_id = slot.id
    db.close()
    r = api.post("/api/sessions/open", json={"slot_id": slot_id, "date": today.isoformat()},
                 headers=klass["teacher_h"])
    assert r.status_code == 409 and "holiday" in r.json()["detail"]


# -------------------------------------------------------------- manual + audit

def test_manual_change_requires_reason_and_is_audited(api, klass):
    from app.models import AuditLog

    sid = _make_session(klass)
    uid = klass["students"][0]
    _qr(api, klass, uid, sid)                               # recorded as present via QR
    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": uid, "status": "absent"}]},
                 headers=klass["teacher_h"])
    assert r.status_code == 422
    assert r.json()["detail"]["needs_reason"] == [uid]

    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": uid, "status": "absent",
                                  "reason": "left after the code was shown"}]},
                 headers=klass["teacher_h"])
    assert r.status_code == 200
    db = _db()
    entry = db.query(AuditLog).filter_by(action="attendance_changed").one()
    db.close()
    assert entry.actor_id == klass["teacher"]
    assert entry.reason == "left after the code was shown"
    assert "present -> absent" in entry.detail


def test_marking_over_a_close_time_absence_needs_no_reason(api, klass):
    sid = _make_session(klass)
    api.post(f"/api/sessions/{sid}/stop", headers=klass["teacher_h"])
    uid = klass["students"][3]
    r = api.post(f"/api/attendance/sessions/{sid}/records",
                 json={"marks": [{"user_id": uid, "status": "present"}]},
                 headers=klass["teacher_h"])
    assert r.status_code == 200, r.text


def test_teacher_cannot_view_another_teachers_session(api, klass):
    sid = _make_session(klass)
    assert api.get(f"/api/sessions/{sid}/live", headers=klass["other_h"]).status_code == 403
    assert api.get(f"/api/sessions/{sid}/code", headers=klass["other_h"]).status_code == 403
    stu = klass["h"][klass["students"][0]]
    assert api.get(f"/api/sessions/{sid}/code", headers=stu).status_code == 403
    ok = api.get(f"/api/sessions/{sid}/code", headers=klass["teacher_h"])
    assert ok.status_code == 200 and len(ok.json()["code"]) == 6


# --------------------------------------------------------------------- student

def test_active_sessions_and_history_with_pdf(api, klass):
    sid = _make_session(klass)
    uid = klass["students"][0]
    h = klass["h"][uid]
    active = api.get("/api/me/sessions/active", headers=h).json()
    assert active["approved"] and active["sessions"][0]["id"] == sid
    assert active["sessions"][0]["would_be"] == "present"
    _qr(api, klass, uid, sid)
    hist = api.get("/api/me/history", headers=h).json()
    assert hist["meta"]["total"] == 1 and hist["rows"][0]["status"] == "present"
    assert hist["rows"][0]["method"] == "QR code"
    pdf = api.get("/api/me/history?format=pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert api.get("/api/me/history?status=absent", headers=h).json()["meta"]["total"] == 0


def test_student_cannot_read_another_students_history(api, klass):
    a, b = klass["students"][0], klass["students"][1]
    r = api.get(f"/api/me/history?user_id={b}", headers=klass["h"][a])
    assert r.status_code == 403
    assert api.get(f"/api/me/history?user_id={b}", headers=klass["teacher_h"]).status_code == 200


def test_classes_needed_arithmetic():
    from app.analytics_service import _classes_needed

    assert _classes_needed(6, 10, 75) == 6          # (6+6)/(10+6) = 75%
    assert _classes_needed(15, 20, 75) == 0          # already at 75%
    assert _classes_needed(0, 4, 75) == 12           # (0+12)/(4+12) = 75%
    assert _classes_needed(7, 10, 70) == 0
    assert _classes_needed(5, 10, 80) == 15          # (5+15)/(10+15) = 80%


def test_percentage_counts_on_leave_out_of_the_denominator(api, klass):
    from app.models import AttendanceRecordRow, ClassSession
    from app.session_service import overall_pct

    uid = klass["students"][0]
    db = _db()
    now = datetime.now(timezone.utc)
    for i, st in enumerate(["present", "present", "present", "absent", "on_leave", "excused"]):
        s = ClassSession(title="x", room="R", owner_id=klass["teacher"],
                         scheduled_start=now - timedelta(days=i + 1),
                         scheduled_end=now - timedelta(days=i + 1) + timedelta(hours=1),
                         subject_id=klass["subject"], section_id=klass["section"], state="closed")
        db.add(s)
        db.flush()
        db.add(AttendanceRecordRow(session_id=s.id, user_id=uid, status=st, source="manual"))
    db.commit()
    present, counted = overall_pct(db, uid)
    db.close()
    assert (present, counted) == (3, 4)              # 75%: leave and excused excluded
