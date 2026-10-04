"""Phase 3: academic structure, registration + OTP, approvals, profile, import, files, admin."""
from __future__ import annotations

import email
import os
import re
from datetime import date
from pathlib import Path

import cv2
import numpy as np
import pytest


def _png() -> bytes:
    ok, buf = cv2.imencode(".png", np.full((16, 16, 3), 128, np.uint8))
    assert ok
    return buf.tobytes()


def _outbox_messages():
    """Deliver queued emails into the test outbox, then return them oldest first."""
    from app.db import SessionLocal
    from app.notify import dispatch_emails

    db = SessionLocal()
    try:
        dispatch_emails(db, "http://portal.test", "Test College")
    finally:
        db.close()
    folder = Path(os.environ["ATTENDANCE_OUTBOX"])
    msgs = []
    for p in sorted(folder.glob("*.eml")):
        msgs.append(email.message_from_bytes(p.read_bytes()))
    return msgs


def _body(msg) -> str:
    part = msg.get_body(("plain",)) if hasattr(msg, "get_body") else msg
    return (part or msg).get_payload(decode=True).decode()


def _latest_mail_to(addr: str):
    for m in reversed(_outbox_messages()):
        if m["To"] == addr:
            return _body(m)
    raise AssertionError(f"no mail to {addr}")


@pytest.fixture()
def campus(api, make_user, email_codes_on):
    """CSE + ECE branches, a 2023-2027 batch, sections, a term, a teacher per section."""
    admin_id, admin = make_user("root", role="super_admin")
    r = api.post("/api/departments", json={"code": "CSE", "name": "Computer Science"},
                 headers=admin)
    assert r.status_code == 201, r.text
    cse = r.json()["id"]
    ece = api.post("/api/departments", json={"code": "ECE", "name": "Electronics"},
                   headers=admin).json()["id"]
    batch = api.post("/api/batches", json={"start_year": 2023, "end_year": 2027},
                     headers=admin).json()["id"]
    batch2 = api.post("/api/batches", json={"start_year": 2024, "end_year": 2028},
                      headers=admin).json()["id"]
    sec_a = api.post("/api/sections", json={"department_id": cse, "batch_id": batch, "name": "A",
                                            "year": 2, "semester": 3}, headers=admin).json()["id"]
    sec_b = api.post("/api/sections", json={"department_id": cse, "batch_id": batch, "name": "B",
                                            "year": 2, "semester": 3}, headers=admin).json()["id"]
    sec_e = api.post("/api/sections", json={"department_id": ece, "batch_id": batch, "name": "A",
                                            "year": 2, "semester": 3}, headers=admin).json()["id"]
    sec_24 = api.post("/api/sections", json={"department_id": cse, "batch_id": batch2,
                                             "name": "A", "year": 1, "semester": 1},
                      headers=admin).json()["id"]
    api.post("/api/terms", json={"name": "2026 Odd", "start_date": "2026-07-01",
                                 "end_date": "2026-12-15", "is_active": True}, headers=admin)
    subj = api.post("/api/subjects", json={"code": "CS301", "name": "Data Structures",
                                           "department_id": cse, "year": 2, "semester": 3},
                    headers=admin).json()["id"]
    t_a, t_a_h = make_user("teach.a", role="faculty", department_id=cse)
    t_b, t_b_h = make_user("teach.b", role="faculty", department_id=cse)
    assert api.post("/api/assignments", json={"faculty_id": t_a, "subject_id": subj,
                                              "section_id": sec_a}, headers=admin).status_code == 201
    assert api.post("/api/assignments", json={"faculty_id": t_b, "subject_id": subj,
                                              "section_id": sec_b}, headers=admin).status_code == 201
    return {"admin": admin, "admin_id": admin_id, "cse": cse, "ece": ece, "batch": batch,
            "batch2": batch2, "sec_a": sec_a, "sec_b": sec_b, "sec_e": sec_e, "sec_24": sec_24,
            "subject": subj, "teacher_a": t_a_h, "teacher_a_id": t_a, "teacher_b": t_b_h}


def _signup(api, c, **over):
    form = {"full_name": "Asha Verma", "email": "asha@college.edu", "mobile": "9876543210",
            "password": "Secret-pass-1", "roll_number": "CSE23014", "enrollment_no": "EN014",
            "department_id": str(c["cse"]), "year": "2", "batch_id": str(c["batch"]),
            "section_id": str(c["sec_a"]), "dob": "2005-04-17", "gender": "female",
            "guardian_name": "Rajesh Verma", "guardian_phone": "9812345678",
            "address": "12 MG Road, Pune"}
    form.update({k: str(v) for k, v in over.items()})
    photo = over.pop("_photo", None) if "_photo" in over else _png()
    return api.post("/api/auth/signup", data=form,
                    files={"photo": ("me.png", photo, "image/png")})


def _verify(api, addr: str):
    code = re.search(r"\b(\d{6})\b", _latest_mail_to(addr)).group(1)
    return api.post("/api/auth/verify-email", json={"email": addr, "code": code})


def _login(api, ident: str, pw: str = "Secret-pass-1"):
    return api.post("/api/auth/login", json={"username": ident, "password": pw})


def _auth(r) -> dict:
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------------------- academic structure

def test_public_options_feed_the_signup_dropdowns(api, campus):
    opts = api.get("/api/public/academic-options").json()
    assert {d["code"] for d in opts["departments"]} == {"CSE", "ECE"}
    assert {b["label"] for b in opts["batches"]} == {"2023-2027", "2024-2028"}
    assert any(s["label"].startswith("CSE Y2-A") for s in opts["sections"])
    assert "students" not in str(opts).lower() or all("email" not in str(s) for s in opts["sections"])


def test_teacher_cannot_create_branches_or_sections(api, campus):
    assert api.post("/api/departments", json={"code": "ME", "name": "Mech"},
                    headers=campus["teacher_a"]).status_code == 403
    assert api.post("/api/sections", json={"department_id": campus["cse"], "name": "C",
                                           "year": 2, "semester": 3},
                    headers=campus["teacher_a"]).status_code == 403


def test_duplicates_in_academic_setup_are_a_clear_409_not_a_server_error(api, campus):
    """Found by the Firefox e2e run: a repeated batch used to escape as a 500 at flush time."""
    admin = campus["admin"]
    cases = [
        ("/api/batches", {"start_year": 2023, "end_year": 2027}, "already exists"),
        ("/api/departments", {"code": "CSE", "name": "Again"}, "already exists"),
        ("/api/sections", {"department_id": campus["cse"], "batch_id": campus["batch"], "name": "A",
                           "year": 2, "semester": 3}, "already exists"),
    ]
    for path, body, phrase in cases:
        r = api.post(path, json=body, headers=admin)
        assert r.status_code == 409, (path, r.status_code, r.text)
        assert phrase in r.json()["detail"]
    # The session is still usable after the rollback.
    assert api.post("/api/batches", json={"start_year": 2031, "end_year": 2035}, headers=admin).status_code == 201


def test_hod_is_confined_to_own_branch(api, campus, make_user):
    _, hod = make_user("hod.cse", role="admin", department_id=campus["cse"])
    ok = api.post("/api/sections", json={"department_id": campus["cse"], "batch_id": campus["batch"],
                                         "name": "C", "year": 2, "semester": 3}, headers=hod)
    assert ok.status_code == 201
    bad = api.post("/api/sections", json={"department_id": campus["ece"], "name": "C",
                                          "year": 2, "semester": 3}, headers=hod)
    assert bad.status_code == 403


def test_branch_or_batch_with_students_cannot_be_deleted(api, campus):
    assert _signup(api, campus).status_code == 201
    r = api.delete(f"/api/departments/{campus['cse']}", headers=campus["admin"])
    assert r.status_code == 409
    assert "still has 1 student" in r.json()["detail"]
    r = api.delete(f"/api/batches/{campus['batch']}", headers=campus["admin"])
    assert r.status_code == 409
    assert "still has 1 student" in r.json()["detail"]


def test_timetable_rejects_double_booking(api, campus):
    api.post("/api/rooms", json={"name": "LH-101"}, headers=campus["admin"])
    slot = {"section_id": campus["sec_a"], "subject_id": campus["subject"],
            "faculty_id": campus["teacher_a_id"], "day_of_week": 0, "start_time": "09:00",
            "end_time": "09:50", "room": "LH-101"}
    assert api.post("/api/timetable", json=slot, headers=campus["admin"]).status_code == 201
    clash = {**slot, "section_id": campus["sec_b"], "start_time": "09:30", "end_time": "10:20"}
    r = api.post("/api/timetable", json=clash, headers=campus["admin"])
    assert r.status_code == 409          # same teacher and same room at overlapping time
    unknown_room = {**slot, "start_time": "11:00", "end_time": "11:50", "room": "Nowhere"}
    assert api.post("/api/timetable", json=unknown_room, headers=campus["admin"]).status_code == 422


# ------------------------------------------------------------------ registration

def test_without_email_codes_a_student_signs_in_right_after_registering(api, campus):
    from app import settings_service
    from app.db import SessionLocal
    from app.runtime import cfg

    db = SessionLocal()
    settings_service.update(db, cfg, {"email_verification_required": False}, actor_id=None)
    db.commit()
    db.close()
    settings_service.invalidate()

    r = _signup(api, campus)
    assert r.status_code == 201 and r.json()["otp_sent"] is False
    login = _login(api, "asha@college.edu")
    assert login.status_code == 200 and login.json()["student_status"] == "pending"
    # Teachers are told straight away, and still have to approve.
    assert api.get("/api/approvals/summary", headers=campus["teacher_a"]).json()["registrations"] == 1


def test_teacher_approval_vouches_for_an_unverified_email(api, campus):
    """The code never arrived (mail provider refusing): the teacher can still approve, which
    verifies the address, and the student can then sign in."""
    assert _signup(api, campus).status_code == 201
    assert _login(api, "asha@college.edu").json()["detail"]["code"] == "email_unverified"
    assert api.get("/api/approvals/summary", headers=campus["admin"]).json()["registrations"] == 1
    sid = api.get("/api/students?status=pending", headers=campus["admin"]).json()["rows"][0]["id"]
    assert api.post(f"/api/students/{sid}/approve", headers=campus["admin"]).status_code == 200
    r = _login(api, "asha@college.edu")
    assert r.status_code == 200 and r.json()["student_status"] == "approved"


def test_system_status_reports_a_bouncing_mail_provider(api, campus, monkeypatch):
    from app.db import SessionLocal
    from app.models import Notification, User

    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    db = SessionLocal()
    uid = db.query(User).first().id
    db.add(Notification(user_id=uid, type="verify_email", payload="{}", channel="email",
                        error="SMTPDataError: (550, b'You can only send testing emails to your own email address')"))
    db.commit()
    db.close()
    warnings = api.get("/api/system/status", headers=campus["admin"]).json()["warnings"]
    assert any(w.startswith("EMAIL FAILING") and "only send testing emails" in w for w in warnings)


def test_signup_verify_pending_then_teacher_approves(api, campus):
    r = _signup(api, campus)
    assert r.status_code == 201, r.text

    # Cannot sign in until the email is verified.
    r = _login(api, "asha@college.edu")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_unverified"

    bad = api.post("/api/auth/verify-email", json={"email": "asha@college.edu", "code": "000000"})
    assert bad.status_code == 400
    assert _verify(api, "asha@college.edu").status_code == 200

    r = _login(api, "CSE23014")                       # roll number works as a login too
    assert r.status_code == 200
    assert r.json()["student_status"] == "pending"
    student = _auth(r)
    sid = r.json()["user_id"]
    assert api.get("/api/me", headers=student).json()["student_status"] == "pending"

    # The class teacher was told, and sees the registration.
    listing = api.get("/api/students?status=pending", headers=campus["teacher_a"]).json()
    assert [row["id"] for row in listing["rows"]] == [sid]
    # A teacher of another section neither sees nor can approve it.
    assert api.get("/api/students?status=pending",
                   headers=campus["teacher_b"]).json()["rows"] == []
    assert api.post(f"/api/students/{sid}/approve",
                    headers=campus["teacher_b"]).status_code == 403

    assert api.post(f"/api/students/{sid}/approve",
                    headers=campus["teacher_a"]).status_code == 200
    assert api.get("/api/me", headers=student).json()["student_status"] == "approved"
    assert "approved" in _latest_mail_to("asha@college.edu").lower()


def test_rejected_student_sees_the_reason_and_can_resubmit(api, campus):
    _signup(api, campus)
    _verify(api, "asha@college.edu")
    r = _login(api, "asha@college.edu")
    sid, student = r.json()["user_id"], _auth(r)
    no_reason = api.post(f"/api/students/{sid}/reject", json={}, headers=campus["teacher_a"])
    assert no_reason.status_code == 422
    api.post(f"/api/students/{sid}/reject", json={"reason": "Wrong section selected"},
             headers=campus["teacher_a"])
    me = api.get("/api/me", headers=student).json()
    assert me["student_status"] == "rejected"
    assert me["rejection_reason"] == "Wrong section selected"

    fixed = api.patch("/api/me/profile", json={"section_id": campus["sec_b"]}, headers=student)
    assert fixed.status_code == 200
    assert api.post("/api/me/resubmit", headers=student).json()["student"]["status"] == "pending"


def test_duplicate_roll_in_same_branch_and_batch_is_rejected(api, campus):
    assert _signup(api, campus).status_code == 201
    r = _signup(api, campus, email="other@college.edu", mobile="9876500000",
                enrollment_no="EN999", section_id=campus["sec_b"])
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["field"] == "roll_number"
    assert "already registered in CSE 2023-2027" in detail["message"]


def test_duplicate_email_and_mobile_rejected(api, campus):
    _signup(api, campus)
    r = _signup(api, campus, roll_number="X1", enrollment_no="E2", mobile="9000000001")
    assert r.status_code == 409 and r.json()["detail"]["field"] == "email"
    r = _signup(api, campus, roll_number="X1", enrollment_no="E2", email="new@college.edu")
    assert r.status_code == 409 and r.json()["detail"]["field"] == "mobile"


def test_signup_validates_class_consistency_and_fields(api, campus):
    r = _signup(api, campus, section_id=campus["sec_e"])          # ECE section, CSE branch
    assert r.status_code == 422 and r.json()["detail"]["field"] == "section_id"
    r = _signup(api, campus, password="short")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "password"
    r = _signup(api, campus, mobile="12")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "mobile"


def test_signup_photo_is_checked_by_content_not_extension(api, campus):
    form_photo = b"<html><script>alert(1)</script></html>"
    r = api.post("/api/auth/signup", data={
        "full_name": "X Y", "email": "x@college.edu", "mobile": "9876543211",
        "password": "Secret-pass-1", "roll_number": "R1", "enrollment_no": "E1",
        "department_id": campus["cse"], "year": 2, "batch_id": campus["batch"],
        "section_id": campus["sec_a"], "dob": "2005-01-01", "gender": "male",
        "guardian_name": "G", "guardian_phone": "9812345670", "address": "Somewhere 1"},
        files={"photo": ("photo.jpg", form_photo, "image/jpeg")})
    assert r.status_code == 415


# --------------------------------------------------------------- profile & edits

def _approved_student(api, campus):
    _signup(api, campus)
    _verify(api, "asha@college.edu")
    r = _login(api, "asha@college.edu")
    sid = r.json()["user_id"]
    api.post(f"/api/students/{sid}/approve", headers=campus["teacher_a"])
    return sid, _auth(_login(api, "asha@college.edu"))


def test_locked_fields_need_an_edit_request_after_approval(api, campus):
    sid, student = _approved_student(api, campus)
    r = api.patch("/api/me/profile", json={"roll_number": "CSE23999"}, headers=student)
    assert r.status_code == 403
    ok = api.patch("/api/me/profile", json={"address": "New hostel, Block C"}, headers=student)
    assert ok.status_code == 200
    assert ok.json()["student"]["address"] == "New hostel, Block C"

    req = api.post("/api/me/edit-requests", json={"changes": {"roll_number": "CSE23999"},
                                                  "reason": "Typo in my roll number"},
                   headers=student)
    assert req.status_code == 201
    rid = req.json()["id"]
    assert api.post(f"/api/edit-requests/{rid}/approve", json={},
                    headers=campus["teacher_b"]).status_code == 403
    assert api.post(f"/api/edit-requests/{rid}/approve", json={},
                    headers=campus["teacher_a"]).status_code == 200
    prof = api.get("/api/me/profile", headers=student).json()
    assert prof["student"]["roll_number"] == "CSE23999"


def test_change_password_revokes_other_sessions(api, campus):
    sid, student = _approved_student(api, campus)
    r = api.post("/api/me/password", json={"current_password": "wrong",
                                           "new_password": "Another-pass-2"}, headers=student)
    assert r.status_code == 400
    import time

    time.sleep(1.1)                    # token iat has 1-second resolution
    r = api.post("/api/me/password", json={"current_password": "Secret-pass-1",
                                           "new_password": "Another-pass-2"}, headers=student)
    assert r.status_code == 200
    assert api.get("/api/me", headers=student).status_code == 401
    assert _login(api, "asha@college.edu", "Another-pass-2").status_code == 200


def test_forgot_and_reset_password(api, campus):
    _approved_student(api, campus)
    r = api.post("/api/auth/forgot-password", json={"email": "nobody@college.edu"})
    assert r.status_code == 200                       # no account enumeration
    api.post("/api/auth/forgot-password", json={"email": "asha@college.edu"})
    body = _latest_mail_to("asha@college.edu")
    token = re.search(r"token=([\w\-]+)", body).group(1)
    assert api.post("/api/auth/reset-password",
                    json={"token": token, "password": "weak"}).status_code == 422
    assert api.post("/api/auth/reset-password",
                    json={"token": token, "password": "Brand-new-3"}).status_code == 200
    assert api.post("/api/auth/reset-password",
                    json={"token": token, "password": "Brand-new-4"}).status_code == 400
    assert _login(api, "asha@college.edu", "Brand-new-3").status_code == 200


def test_sensitive_emails_are_scrubbed_after_delivery(api, campus):
    from app.db import SessionLocal
    from app.models import Notification

    _signup(api, campus)
    _outbox_messages()
    db = SessionLocal()
    rows = db.query(Notification).filter(Notification.type == "verify_email").all()
    db.close()
    assert rows and all(r.channel == "email" for r in rows)          # never an in-app copy
    assert all(not re.search(r"\d{6}", r.body or "") for r in rows)


# ------------------------------------------------------------------- isolation

def test_student_cannot_reach_staff_endpoints_or_other_students(api, campus):
    sid, student = _approved_student(api, campus)
    assert api.get("/api/students", headers=student).status_code == 403
    assert api.get(f"/api/students/{sid}", headers=student).status_code == 403
    assert api.post(f"/api/students/{sid}/approve", headers=student).status_code == 403


def test_profile_photo_served_only_to_authorised_users(api, campus, make_user):
    sid, student = _approved_student(api, campus)
    url = api.get("/api/me/profile", headers=student).json()["student"]["photo_url"]
    assert api.get(url, headers=student).status_code == 200
    assert api.get(url, headers=campus["teacher_a"]).status_code == 200
    assert api.get(url, headers=campus["teacher_b"]).status_code == 404
    _, other = make_user("other.student")
    assert api.get(url, headers=other).status_code == 404


# ---------------------------------------------------------------------- import

def test_bulk_import_reports_bad_rows_and_creates_good_ones(api, campus):
    tpl = api.get("/api/students/import/template", headers=campus["teacher_a"])
    assert tpl.status_code == 200 and tpl.text.startswith("full_name,email,mobile")
    header = tpl.text.splitlines()[0]
    rows = [
        "Ravi Kumar,ravi@college.edu,9800000001,CSE23020,EN020,CSE,2023-2027,2,A,2005-02-02,male,G One,9811111111,,Addr 1",
        "Bad Email,not-an-email,9800000002,CSE23021,EN021,CSE,2023-2027,2,A,,,,,,",
        "Wrong Class,w@college.edu,9800000003,CSE23022,EN022,CSE,2023-2027,2,B,,,,,,",
        "Dup Roll,d@college.edu,9800000004,CSE23020,EN023,CSE,2023-2027,2,A,,,,,,",
        "Meena Das,meena@college.edu,9800000005,CSE23024,EN024,CSE,2023-2027,2,A,,female,,,,",
    ]
    csv_bytes = ("\n".join([header] + rows) + "\n").encode()
    dry = api.post("/api/students/import", data={"dry_run": "true"},
                   files={"file": ("s.csv", csv_bytes, "text/csv")}, headers=campus["teacher_a"])
    assert dry.status_code == 200
    assert dry.json()["created"] == 0 and dry.json()["valid"] == 2

    r = api.post("/api/students/import", files={"file": ("s.csv", csv_bytes, "text/csv")},
                 headers=campus["teacher_a"])
    out = r.json()
    assert out["created"] == 2
    errs = {e["row"]: e for e in out["errors"]}
    assert errs[3]["field"] == "email"
    assert errs[4]["field"] == "section"            # section B is not this teacher's class
    assert errs[5]["field"] == "roll_number"
    listing = api.get("/api/students", headers=campus["teacher_a"]).json()
    assert {r["roll_number"] for r in listing["rows"]} == {"CSE23020", "CSE23024"}
    # Imported students get a set-your-password invite.
    assert "set your password" in _latest_mail_to("meena@college.edu").lower()


def test_xlsx_import(api, campus):
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["full_name", "email", "mobile", "roll_number", "enrollment_no", "branch_code",
               "batch", "year", "section", "dob", "gender", "guardian_name", "guardian_phone",
               "guardian_email", "address"])
    ws.append(["Xl Student", "xl@college.edu", 9800000009, "CSE23050", "EN050", "CSE",
               "2023-2027", 2, "A", date(2005, 5, 5), "male", None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = api.post("/api/students/import",
                 files={"file": ("s.xlsx", buf.getvalue(),
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                 headers=campus["admin"])
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 1, r.json()


# ----------------------------------------------------------------------- admin

def test_role_guards_on_staff_management(api, campus, make_user):
    _, hod = make_user("hod.cse2", role="admin", department_id=campus["cse"])
    r = api.post("/api/admin/users", json={"full_name": "New Admin", "email": "na@college.edu",
                                           "role": "super_admin"}, headers=hod)
    assert r.status_code == 403
    r = api.post("/api/admin/users", json={"full_name": "New Teacher", "email": "nt@college.edu",
                                           "role": "faculty", "department_id": campus["cse"]},
                 headers=hod)
    assert r.status_code == 201
    r = api.post("/api/admin/users", json={"full_name": "ECE Teacher", "email": "et@college.edu",
                                           "role": "faculty", "department_id": campus["ece"]},
                 headers=hod)
    assert r.status_code == 403
    me = api.get("/api/me", headers=campus["admin"]).json()
    r = api.patch(f"/api/admin/users/{me['id']}", json={"role": "faculty",
                                                        "department_id": campus["cse"]},
                  headers=campus["admin"])
    assert r.status_code == 409                       # cannot demote yourself


def test_settings_validation_and_audit(api, campus):
    assert api.patch("/api/admin/settings", json={"min_attendance_pct": 80},
                     headers=campus["teacher_a"]).status_code == 403
    bad = api.patch("/api/admin/settings", json={"present_window_min": 30, "late_window_min": 20},
                    headers=campus["admin"])
    assert bad.status_code == 422
    ok = api.patch("/api/admin/settings", json={"min_attendance_pct": 80},
                   headers=campus["admin"])
    assert ok.status_code == 200 and ok.json()["values"]["min_attendance_pct"] == 80.0
    log = api.get("/api/admin/audit?action=settings_changed", headers=campus["admin"]).json()
    assert log["meta"]["total"] == 1
    assert "min_attendance_pct" in log["rows"][0]["detail"]
