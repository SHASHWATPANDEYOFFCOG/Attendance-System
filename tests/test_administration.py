"""Access codes, workspaces, tablets, camera isolation, approval decisions, academic years and
account self-service. Every rule here is enforced by the API; these tests call it directly."""
from __future__ import annotations

import pytest

from test_portal_sessions import _db, _make_session, klass  # noqa: F401

AUTH_CODE, ADMIN_CODE = "occlubio-authority", "occlubio-administrator"


# ----------------------------------------------------------------- access codes

def test_administrator_code_unlocks_the_administrator_role(api, make_user):
    _, teacher = make_user("t1", role="faculty")
    bad = api.post("/api/access/administrator", json={"code": "guess-guess"}, headers=teacher)
    assert bad.status_code == 403 and bad.json()["detail"]["field"] == "code"
    assert api.get("/api/admin/access-codes", headers=teacher).status_code == 403
    ok = api.post("/api/access/administrator", json={"code": ADMIN_CODE}, headers=teacher)
    assert ok.status_code == 200 and ok.json()["role"] == "super_admin"
    assert api.get("/api/me", headers=teacher).json()["role"] == "super_admin"     # effective at once


def test_changing_a_code_revokes_the_old_one_and_never_reveals_either(api, make_user):
    _, root = make_user("root", role="super_admin")
    _, teacher = make_user("t1", role="faculty")
    st = api.get("/api/admin/access-codes", headers=root).json()
    assert st["administrator"]["is_default"] and ADMIN_CODE not in str(st)
    # validation: confirm must match, minimum length, codes must differ
    assert api.put("/api/admin/access-codes/administrator", json={"code": "new-admin-code", "confirm": "x"},
                   headers=root).status_code == 422
    assert api.put("/api/admin/access-codes/administrator", json={"code": "short", "confirm": "short"},
                   headers=root).status_code == 422
    assert api.put("/api/admin/access-codes/administrator", json={"code": AUTH_CODE, "confirm": AUTH_CODE},
                   headers=root).status_code == 422
    r = api.put("/api/admin/access-codes/administrator", json={"code": "Fresh-Admin-77", "confirm": "Fresh-Admin-77"},
                headers=root)
    assert r.status_code == 200 and r.json()["administrator"]["is_default"] is False
    assert "Fresh-Admin-77" not in r.text
    assert api.post("/api/access/administrator", json={"code": ADMIN_CODE}, headers=teacher).status_code == 403
    assert api.post("/api/access/administrator", json={"code": "Fresh-Admin-77"}, headers=teacher).status_code == 200
    # Only a hash is stored.
    from app.models import Setting
    db = _db()
    stored = db.query(Setting).filter_by(key="access_code.administrator").one().value
    db.close()
    assert stored.startswith("$argon2") and "Fresh-Admin-77" not in stored


def test_staff_registration_needs_the_current_authority_code(api, make_user):
    _, root = make_user("root", role="super_admin")
    dept = api.post("/api/departments", json={"code": "CSE", "name": "CS"}, headers=root).json()["id"]
    body = {"full_name": "New Teacher", "email": "nt@college.edu", "mobile": "9811122233",
            "password": "Teach-Pass-123", "employee_id": "E1", "department_id": dept}
    r = api.post("/api/auth/staff-signup", json={**body, "access_code": "wrong-code"})
    assert r.status_code == 403 and r.json()["detail"]["field"] == "access_code"
    api.put("/api/admin/access-codes/authority", json={"code": "Staff-Code-2026", "confirm": "Staff-Code-2026"},
            headers=root)
    assert api.post("/api/auth/staff-signup", json={**body, "access_code": AUTH_CODE}).status_code == 403
    assert api.post("/api/auth/staff-signup", json={**body, "access_code": "Staff-Code-2026"}).status_code == 201


# ------------------------------------------------- workspaces, cameras, tablets

@pytest.fixture()
def two_workspaces(api, klass, monkeypatch):
    """Workspace A (the class teacher) and B (another teacher), one camera each."""
    import app.worker as worker

    running: set = set()
    from types import SimpleNamespace

    def _start(cid, cfg):
        running.add(cid)
        return SimpleNamespace(is_alive=lambda: True)
    monkeypatch.setattr(worker.registry, "start", _start)
    monkeypatch.setattr(worker.registry, "stop", lambda cid: running.discard(cid) or True)
    monkeypatch.setattr(worker.registry, "is_running", lambda cid: cid in running)
    admin = klass["admin"]
    other_id = api.get("/api/me", headers=klass["other_h"]).json()["id"]
    a = api.post("/api/workspaces", json={"name": "Block A", "member_ids": [klass["teacher"]]}, headers=admin).json()
    b = api.post("/api/workspaces", json={"name": "Block B", "member_ids": [other_id]}, headers=admin).json()
    cam_a = api.post("/api/cameras", json={"name": "A-front", "room": "A1", "source": "rtsp://10.0.0.1/s",
                                           "workspace_id": a["id"], "camera_type": "rtsp"}, headers=admin).json()
    cam_a2 = api.post("/api/cameras", json={"name": "A-back", "room": "A1", "source": "rtsp://10.0.0.2/s",
                                            "workspace_id": a["id"]}, headers=admin).json()
    cam_b = api.post("/api/cameras", json={"name": "B-front", "room": "B1", "source": "rtsp://10.0.0.3/s",
                                           "workspace_id": b["id"]}, headers=admin).json()
    loose = api.post("/api/cameras", json={"name": "Unassigned", "room": "X", "source": "0"}, headers=admin).json()
    return {**klass, "ws_a": a, "ws_b": b, "cam_a": cam_a, "cam_a2": cam_a2, "cam_b": cam_b, "loose": loose,
            "running": running}


def test_authorities_see_only_their_workspaces_and_cameras(api, two_workspaces):
    k = two_workspaces
    names = [c["name"] for c in api.get("/api/cameras", headers=k["teacher_h"]).json()]
    assert sorted(names) == ["A-back", "A-front"]
    assert [w["name"] for w in api.get("/api/workspaces", headers=k["teacher_h"]).json()] == ["Block A"]
    assert len(api.get("/api/cameras", headers=k["admin"]).json()) == 4
    # Another workspace's camera, or an unassigned one, does not exist for this teacher.
    for cam in (k["cam_b"], k["loose"]):
        assert api.post(f"/api/cameras/{cam['id']}/start", headers=k["teacher_h"]).status_code == 404
        assert api.post(f"/api/cameras/{cam['id']}/test", headers=k["teacher_h"]).status_code == 404
    assert api.post(f"/api/cameras/{k['cam_a']['id']}/start", headers=k["teacher_h"]).status_code == 200
    # Only administrators add, edit or remove cameras and create workspaces.
    assert api.post("/api/workspaces", json={"name": "Mine"}, headers=k["teacher_h"]).status_code == 403
    assert api.patch(f"/api/cameras/{k['cam_a']['id']}", json={"name": "x"}, headers=k["teacher_h"]).status_code == 403
    assert api.patch(f"/api/workspaces/{k['ws_a']['id']}", json={"member_ids": []},
                     headers=k["teacher_h"]).status_code == 403
    assert api.patch(f"/api/workspaces/{k['ws_a']['id']}", json={"location": "Ground floor"},
                     headers=k["teacher_h"]).status_code == 200


def _pair(api, k, camera_ids):
    t = api.post("/api/tablets", json={"name": "Front desk tablet", "workspace_id": k["ws_a"]["id"],
                                       "camera_ids": camera_ids}, headers=k["teacher_h"])
    assert t.status_code == 201, t.text
    code = t.json()["pairing_code"]
    assert len(code) == 8 and t.json()["status"] == "pending"
    p = api.post("/api/tablets/pair", json={"pairing_code": code.lower()[:4] + "-" + code[4:]}, headers=k["teacher_h"])
    assert p.status_code == 200, p.text
    assert api.post("/api/tablets/pair", json={"pairing_code": code}, headers=k["teacher_h"]).status_code == 400  # one-time
    return t.json()["id"], p.json()["device_token"]


def test_tablets_pair_once_and_are_limited_to_their_workspace(api, two_workspaces):
    k = two_workspaces
    assert api.post("/api/tablets", json={"name": "Stolen", "workspace_id": k["ws_b"]["id"]},
                    headers=k["teacher_h"]).status_code == 404
    assert api.post("/api/tablets", json={"name": "Bad", "workspace_id": k["ws_a"]["id"],
                                          "camera_ids": [k["cam_b"]["id"]]}, headers=k["teacher_h"]).status_code == 422
    tid, token = _pair(api, k, [k["cam_a"]["id"]])
    dev = {**k["teacher_h"], "X-Device-Token": token}
    me = api.get("/api/tablets/this-device", headers=dev).json()
    assert me["paired"] and me["tablet"]["status"] == "active"
    assert [t["id"] for t in api.get("/api/tablets", headers=k["other_h"]).json()] == []
    # The other teacher cannot use it from their account either.
    other_dev = {**k["other_h"], "X-Device-Token": token}
    assert api.get("/api/tablets/this-device", headers=other_dev).json()["usable"] is False


def test_attendance_from_photo_and_camera_need_a_registered_tablet(api, two_workspaces):
    k = two_workspaces
    sid = _make_session(k)
    roster = [k["students"][0]]
    plain = api.post(f"/api/sessions/{sid}/class-photo/confirm", json={"user_ids": roster}, headers=k["teacher_h"])
    assert plain.status_code == 403 and plain.json()["detail"]["code"] == "tablet_required"
    info = api.get(f"/api/sessions/{sid}/camera", headers=k["teacher_h"]).json()
    assert info["allowed"] is False and "registered tablet" in info["reason"]

    tid, token = _pair(api, k, [k["cam_a"]["id"]])
    dev = {**k["teacher_h"], "X-Device-Token": token}
    assert api.post(f"/api/sessions/{sid}/class-photo/confirm", json={"user_ids": roster}, headers=dev).status_code == 200
    # The tablet sees and connects only its own cameras.
    seen = [c["name"] for c in api.get(f"/api/sessions/{sid}/camera", headers=dev).json()["available"]]
    assert seen == ["A-front"]
    assert api.post(f"/api/sessions/{sid}/camera", json={"camera_id": k["cam_a2"]["id"]}, headers=dev).status_code == 404
    assert api.post(f"/api/sessions/{sid}/camera", json={"camera_id": k["cam_a"]["id"]}, headers=dev).status_code == 200

    # Disabled or revoked: refused on the very next request.
    api.patch(f"/api/tablets/{tid}", json={"status": "disabled"}, headers=k["teacher_h"])
    assert api.post(f"/api/sessions/{sid}/class-photo/confirm", json={"user_ids": roster},
                    headers=dev).status_code == 403
    api.patch(f"/api/tablets/{tid}", json={"status": "active"}, headers=k["teacher_h"])
    api.post(f"/api/tablets/{tid}/revoke", headers=k["teacher_h"])
    assert api.get("/api/tablets/this-device", headers=dev).json()["paired"] is False
    # Administrators are exempt from the tablet requirement.
    assert api.post(f"/api/sessions/{sid}/class-photo/confirm", json={"user_ids": [k["students"][1]]},
                    headers=k["admin"]).status_code == 200


def test_overview_counts_are_scoped(api, two_workspaces):
    k = two_workspaces
    admin = api.get("/api/admin/overview", headers=k["admin"]).json()
    assert admin["cameras"]["total"] == 4 and admin["workspaces"] == 2 and "authorities" in admin
    mine = api.get("/api/admin/overview", headers=k["teacher_h"]).json()
    assert mine["cameras"]["total"] == 2 and mine["workspaces"] == 1 and "authorities" not in mine
    assert mine["students"]["approved"] == 4


# ------------------------------------------------------------ approval decisions

def test_revoke_restore_and_bulk_decisions_are_audited(api, klass):
    sid = klass["students"][0]
    h = klass["teacher_h"]
    assert api.post(f"/api/students/{sid}/revoke", json={}, headers=h).status_code == 422
    r = api.post(f"/api/students/{sid}/revoke", json={"reason": "Left the course"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert api.get("/api/me", headers=klass["h"][sid]).json()["student_status"] == "revoked"
    # A revoked student is no longer on a lecture's roster.
    lecture = _make_session(klass)
    roster = [row["user_id"] for row in api.get(f"/api/sessions/{lecture}/live", headers=h).json()["roster"]]
    assert sid not in roster
    assert api.post(f"/api/students/{sid}/approve", headers=h).status_code == 409       # use Restore
    assert api.post(f"/api/students/{sid}/restore", headers=h).json()["status"] == "approved"

    others = klass["students"][1:3]
    bulk = api.post("/api/students/bulk-decision", json={"ids": others + [klass["pending"]], "action": "revoke",
                                                          "reason": "Duplicate accounts"}, headers=h).json()
    assert sorted(bulk["done"]) == sorted(others)
    assert [f["id"] for f in bulk["failed"]] == [klass["pending"]]                     # pending: cannot revoke
    assert api.post("/api/students/bulk-decision", json={"ids": others, "action": "reject"},
                    headers=h).status_code == 422                                          # no reason
    # Another teacher's student is reported, not touched.
    outside = api.post("/api/students/bulk-decision", json={"ids": [klass["students"][3]], "action": "revoke",
                                                             "reason": "x" * 5}, headers=klass["other_h"]).json()
    assert outside["done"] == [] and outside["failed"][0]["id"] == klass["students"][3]

    log = api.get("/api/admin/audit?action=student_access_revoked", headers=klass["admin"]).json()
    rows = log.get("rows", log)
    entry = next(r for r in rows if str(r.get("target_id")) == str(sid))
    assert '"from": "approved"' in str(entry.get("detail")) or entry.get("detail", {}).get("from") == "approved"


def test_approval_list_filters_by_status_and_academic_year(api, klass):
    admin = klass["admin"]
    y = api.post("/api/academic-years", json={"label": "2026-27", "start_date": "2026-07-01",
                                              "end_date": "2027-06-30", "is_current": True}, headers=admin)
    assert y.status_code == 201, y.text
    yid = y.json()["id"]
    sec = api.get("/api/sections", headers=admin).json()[0]
    api.patch(f"/api/sections/{sec['id']}", json={"department_id": sec["department_id"], "name": sec["name"],
                                                   "year": sec["year"], "semester": sec["semester"],
                                                   "batch_id": sec["batch_id"], "academic_year_id": yid}, headers=admin)
    rows = api.get(f"/api/students?academic_year_id={yid}&status=approved", headers=admin).json()["rows"]
    assert len(rows) == 4 and rows[0]["academic_year"] == "2026-27"
    assert api.get(f"/api/students?academic_year_id={yid}&status=pending", headers=admin).json()["meta"]["total"] == 1
    # A year that still has sections cannot be deleted; only an administrator manages years.
    assert api.delete(f"/api/academic-years/{yid}", headers=admin).status_code == 409
    assert api.post("/api/academic-years", json={"label": "2027-28", "start_date": "2027-07-01",
                                                 "end_date": "2028-06-30"}, headers=klass["teacher_h"]).status_code == 403


def test_inactive_branches_are_not_offered_to_new_registrations(api, klass):
    admin = klass["admin"]
    dept = api.get("/api/departments", headers=admin).json()[0]
    assert dept["is_active"] is True
    api.patch(f"/api/departments/{dept['id']}", json={"code": dept["code"], "name": dept["name"], "is_active": False},
              headers=admin)
    opts = api.get("/api/public/academic-options").json()
    assert opts["departments"] == [] and opts["sections"] == []


# --------------------------------------------------------------------- account

def test_anyone_can_edit_their_own_name_and_sign_out_everywhere(api, make_user):
    _, h = make_user("t1", role="faculty")
    r = api.patch("/api/me/account", json={"full_name": "Meera Iyer", "phone": "9876500011"}, headers=h)
    assert r.status_code == 200 and r.json()["full_name"] == "Meera Iyer"
    assert api.patch("/api/me/account", json={"phone": "12"}, headers=h).status_code == 422
    import time
    time.sleep(1.1)                                  # tokens are compared at one-second resolution
    assert api.post("/api/me/sessions/revoke-all", headers=h).status_code == 200
    assert api.get("/api/me", headers=h).status_code == 401
