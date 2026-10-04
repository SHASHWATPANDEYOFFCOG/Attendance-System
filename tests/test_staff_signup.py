"""Staff self-registration: a form anyone can fill in must grant nothing until approved."""
from __future__ import annotations

import re

import pytest

from tests.test_portal_students import _latest_mail_to


@pytest.fixture()
def branches(api, make_user):
    _, root = make_user("root", role="super_admin")
    cse = api.post("/api/departments", json={"code": "CSE", "name": "Computer Science"}, headers=root).json()["id"]
    ece = api.post("/api/departments", json={"code": "ECE", "name": "Electronics"}, headers=root).json()["id"]
    _, hod = make_user("hod.cse", role="admin", department_id=cse)
    _, teacher = make_user("t.cse", role="faculty", department_id=cse)
    return {"root": root, "hod": hod, "teacher": teacher, "cse": cse, "ece": ece}


def _register(api, dept, *, email="new.teacher@college.edu", role="faculty", emp="EMP-100",
              mobile="9811122233"):
    return api.post("/api/auth/staff-signup", json={
        "full_name": "New Teacher", "email": email, "mobile": mobile, "password": "Teach-Pass-123",
        "employee_id": emp, "designation": "Assistant Professor", "department_id": dept,
        "requested_role": role})


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


def test_cannot_approve_before_email_is_verified(api, branches):
    _register(api, branches["cse"])
    reg = api.get("/api/staff-registrations", headers=branches["root"]).json()[0]
    assert api.post(f"/api/staff-registrations/{reg['id']}/decide", json={"approve": True},
                    headers=branches["root"]).status_code == 409


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
