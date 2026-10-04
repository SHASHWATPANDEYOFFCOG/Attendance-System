"""Staff self-registration: a form anyone can fill in must grant nothing until approved."""
from __future__ import annotations

import re

import pytest

from tests.test_portal_students import _latest_mail_to


@pytest.fixture()
def open_branches(api, make_user, email_codes_on):
    """Default settings: staff registrations need no approval."""
    _, root = make_user("root", role="super_admin")
    cse = api.post("/api/departments", json={"code": "CSE", "name": "Computer Science"}, headers=root).json()["id"]
    ece = api.post("/api/departments", json={"code": "ECE", "name": "Electronics"}, headers=root).json()["id"]
    _, hod = make_user("hod.cse", role="admin", department_id=cse)
    _, teacher = make_user("t.cse", role="faculty", department_id=cse)
    return {"root": root, "hod": hod, "teacher": teacher, "cse": cse, "ece": ece}


@pytest.fixture()
def branches(api, open_branches):
    """The "Staff registrations need approval" setting switched on."""
    r = api.patch("/api/admin/settings", json={"staff_registration_approval": True},
                  headers=open_branches["root"])
    assert r.status_code == 200, r.text
    return open_branches


def _register(api, dept, *, email="new.teacher@college.edu", role="faculty", emp="EMP-100",
              mobile="9811122233"):
    return api.post("/api/auth/staff-signup", json={
        "full_name": "New Teacher", "email": email, "mobile": mobile, "password": "Teach-Pass-123",
        "employee_id": emp, "designation": "Assistant Professor", "department_id": dept,
        "requested_role": role, "access_code": "occlubio-authority"})


def _verify(api, email):
    code = re.search(r"\b(\d{6})\b", _latest_mail_to(email)).group(1)
    r = api.post("/api/auth/verify-email", json={"email": email, "code": code})
    assert r.status_code == 200, r.text
    return r.json()


def _login(api, email, password="Teach-Pass-123"):
    return api.post("/api/auth/login", json={"username": email, "password": password})


def test_registration_grants_nothing_until_approved(api, branches):
    assert _register(api, branches["cse"]).status_code == 201

    r = _login(api, "new.teacher@college.edu")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "email_unverified"

    v = _verify(api, "new.teacher@college.edu")
    assert v["portal"] == "authority" and "administrator" in v["message"]

    r = _login(api, "new.teacher@college.edu")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "staff_pending"

    # Not a colleague yet: invisible in the staff directory.
    names = [u["email"] for u in api.get("/api/admin/users", headers=branches["root"]).json()]
    assert "new.teacher@college.edu" not in names


def test_hod_approves_a_teacher_of_their_branch_who_can_then_sign_in(api, branches):
    _register(api, branches["cse"])
    _verify(api, "new.teacher@college.edu")
    assert api.get("/api/approvals/summary", headers=branches["hod"]).json()["staff"] == 1

    (reg,) = api.get("/api/staff-registrations", headers=branches["hod"]).json()
    assert reg["employee_id"] == "EMP-100" and reg["requested_role"] == "faculty"
    r = api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True}, headers=branches["hod"])
    assert r.status_code == 200 and r.json()["status"] == "approved"

    r = _login(api, "new.teacher@college.edu")
    assert r.status_code == 200 and r.json()["role"] == "faculty"
    assert "approved" in _latest_mail_to("new.teacher@college.edu")
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True},
                    headers=branches["root"]).status_code == 409          # decided once only


def test_only_a_super_admin_can_grant_hod_rights(api, branches):
    _register(api, branches["cse"], role="admin")
    _verify(api, "new.teacher@college.edu")
    # The HOD does not even see a request for HOD rights.
    assert api.get("/api/staff-registrations", headers=branches["hod"]).json() == []
    (reg,) = api.get("/api/staff-registrations", headers=branches["root"]).json()
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True},
                    headers=branches["hod"]).status_code == 404
    # The super admin may grant less than was asked.
    r = api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True, "role": "faculty"},
                 headers=branches["root"])
    assert r.status_code == 200
    assert _login(api, "new.teacher@college.edu").json()["role"] == "faculty"


def test_hod_of_another_branch_and_teachers_cannot_decide(api, branches, make_user):
    _register(api, branches["ece"])
    _verify(api, "new.teacher@college.edu")
    assert api.get("/api/staff-registrations", headers=branches["hod"]).json() == []
    reg = api.get("/api/staff-registrations", headers=branches["root"]).json()[0]
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True},
                    headers=branches["hod"]).status_code == 404
    assert api.get("/api/staff-registrations", headers=branches["teacher"]).status_code == 403
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True},
                    headers=branches["teacher"]).status_code == 403


def test_rejection_needs_a_reason_which_the_person_then_sees(api, branches):
    _register(api, branches["cse"])
    _verify(api, "new.teacher@college.edu")
    reg = api.get("/api/staff-registrations", headers=branches["root"]).json()[0]
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": False},
                    headers=branches["root"]).status_code == 422
    r = api.post(f"/api/staff-registrations/{reg['id']}/decide",
                 json={"approve": False, "reason": "Not on the faculty list"}, headers=branches["root"])
    assert r.status_code == 200
    r = _login(api, "new.teacher@college.edu")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "staff_rejected"
    assert "Not on the faculty list" in r.json()["detail"]["message"]


def test_approving_vouches_for_an_email_whose_code_never_arrived(api, branches):
    """A bouncing mail provider must not lock a real teacher out: the approver vouches."""
    _register(api, branches["cse"])
    assert _login(api, "new.teacher@college.edu").json()["detail"]["code"] == "email_unverified"
    assert api.get("/api/approvals/summary", headers=branches["root"]).json()["staff"] == 1
    reg = api.get("/api/staff-registrations", headers=branches["root"]).json()[0]
    assert reg["email_verified"] is False
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True},
                    headers=branches["root"]).status_code == 200
    assert _login(api, "new.teacher@college.edu").status_code == 200


def test_duplicates_and_bad_input_are_refused_clearly(api, branches):
    assert _register(api, branches["cse"]).status_code == 201
    r = _register(api, branches["cse"])
    assert r.status_code == 409 and r.json()["detail"]["field"] == "email"
    r = _register(api, branches["cse"], email="other@college.edu", mobile="9811100000")
    assert r.status_code == 409 and r.json()["detail"]["field"] == "employee_id"
    r = _register(api, branches["cse"], email="x@college.edu", mobile="9811100001", emp="E2", role="super_admin")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "requested_role"
    r = _register(api, 9999, email="y@college.edu", mobile="9811100002", emp="E3")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "department_id"


# ------------------------------------------------- approval switched off (the default)

def test_by_default_a_verified_teacher_can_sign_in_at_once(api, open_branches):
    assert _register(api, open_branches["cse"]).status_code == 201
    # The email code is still required.
    assert _login(api, "new.teacher@college.edu").json()["detail"]["code"] == "email_unverified"
    v = _verify(api, "new.teacher@college.edu")
    assert "ready" in v["message"] and v["portal"] == "authority"
    r = _login(api, "new.teacher@college.edu")
    assert r.status_code == 200 and r.json()["role"] == "faculty"
    # A colleague now, and nothing left to approve.
    emails = [u["email"] for u in api.get("/api/admin/users", headers=open_branches["root"]).json()]
    assert "new.teacher@college.edu" in emails
    assert api.get("/api/staff-registrations", headers=open_branches["root"]).json() == []


def test_asking_for_hod_without_approval_only_grants_teacher(api, open_branches):
    _register(api, open_branches["cse"], role="admin")
    v = _verify(api, "new.teacher@college.edu")
    assert "HOD rights" in v["message"]
    assert _login(api, "new.teacher@college.edu").json()["role"] == "faculty"
    # And the self-registered teacher cannot reach admin-only endpoints.
    tok = _login(api, "new.teacher@college.edu").json()["access_token"]
    assert api.get("/api/staff-registrations", headers={"Authorization": f"Bearer {tok}"}).status_code == 403


def test_the_register_page_is_told_whether_approval_is_needed(api, open_branches):
    assert api.get("/api/public/academic-options").json()["policy"]["staff_registration_approval"] is False
    api.patch("/api/admin/settings", json={"staff_registration_approval": True}, headers=open_branches["root"])
    assert api.get("/api/public/academic-options").json()["policy"]["staff_registration_approval"] is True


# ------------------------------------------------------ email codes switched off (the default)

@pytest.fixture()
def no_codes(api, make_user):
    _, root = make_user("root", role="super_admin")
    cse = api.post("/api/departments", json={"code": "CSE", "name": "Computer Science"}, headers=root).json()["id"]
    return {"root": root, "cse": cse}


def test_without_email_codes_a_teacher_registers_and_signs_in_immediately(api, no_codes):
    r = _register(api, no_codes["cse"])
    assert r.status_code == 201
    assert r.json()["otp_sent"] is False and r.json()["account"] == "ready"
    login = _login(api, "new.teacher@college.edu")
    assert login.status_code == 200 and login.json()["role"] == "faculty"


def test_without_email_codes_but_with_approval_the_teacher_still_waits(api, no_codes):
    api.patch("/api/admin/settings", json={"staff_registration_approval": True}, headers=no_codes["root"])
    r = _register(api, no_codes["cse"])
    assert r.json()["otp_sent"] is False and r.json()["account"] == "pending"
    assert _login(api, "new.teacher@college.edu").json()["detail"]["code"] == "staff_pending"


def test_turning_codes_off_releases_people_stuck_waiting_for_one(api, no_codes):
    api.patch("/api/admin/settings", json={"email_verification_required": True}, headers=no_codes["root"])
    _register(api, no_codes["cse"])
    assert _login(api, "new.teacher@college.edu").json()["detail"]["code"] == "email_unverified"
    api.patch("/api/admin/settings", json={"email_verification_required": False}, headers=no_codes["root"])
    r = _login(api, "new.teacher@college.edu")
    assert r.status_code == 200 and r.json()["role"] == "faculty"
