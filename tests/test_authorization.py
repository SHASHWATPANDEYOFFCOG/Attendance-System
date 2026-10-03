"""Authorization — the tests that prove scoping happens server-side.

If any of these fail, the dashboard is leaking rows and no amount of CSS hides it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _record_ids(client, headers, session_id):
    r = client.get(f"/api/sessions/{session_id}/attendance", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------- student vs student

def test_student_cannot_read_another_students_session_rows(api, make_user, make_session):
    alice, a_h = make_user("alice")
    bob, _ = make_user("bob")
    prof, _ = make_user("prof", role="faculty")
    sid = make_session(prof, roster=[alice, bob])

    body = _record_ids(api, a_h, sid)
    returned = {r["user_id"] for r in body["records"]}
    assert returned == {alice}, "a student received another student's attendance row"
    assert body["summary"] is None, "class-wide summary leaked to a student"


def test_student_cannot_read_a_session_they_are_not_rostered_into(api, make_user, make_session):
    _alice, a_h = make_user("alice")
    bob, _ = make_user("bob")
    prof, _ = make_user("prof", role="faculty")
    sid = make_session(prof, roster=[bob])

    assert api.get(f"/api/sessions/{sid}/attendance", headers=a_h).status_code == 403


def test_me_attendance_returns_only_the_callers_rows(api, make_user, make_session):
    alice, a_h = make_user("alice")
    bob, b_h = make_user("bob")
    prof, _ = make_user("prof", role="faculty")
    make_session(prof, roster=[alice, bob])

    for headers, uid in ((a_h, alice), (b_h, bob)):
        rows = api.get("/api/me/attendance", headers=headers).json()["records"]
        assert all(r["user_id"] == uid for r in rows)


# ------------------------------------------------------------- live stream

def test_student_cannot_open_the_live_stream(api, make_user):
    _uid, headers = make_user("alice")
    assert api.get("/api/live/stream", headers=headers).status_code == 403


class _FakeRequest:
    """Minimal stand-in for starlette's Request that reports an immediate disconnect."""

    query_params: dict = {}

    async def is_disconnected(self) -> bool:
        return True


def test_faculty_is_not_rejected_by_the_live_stream(api, make_user):
    """Called directly: consuming the SSE body under TestClient would block forever, but the
    authorization decision is made before the first byte is streamed."""
    import anyio
    from fastapi.responses import StreamingResponse

    from app.api import live_stream
    from app.db import SessionLocal
    from app.models import User

    uid, _headers = make_user("prof", role="faculty")
    db = SessionLocal()
    try:
        actor = db.get(User, uid)
        response = anyio.run(live_stream, _FakeRequest(), None, actor)
        assert isinstance(response, StreamingResponse)
    finally:
        db.close()


# ------------------------------------------------------------------ cameras

def test_student_cannot_list_cameras(api, make_user):
    _uid, headers = make_user("alice")
    assert api.get("/api/cameras", headers=headers).status_code == 403


def test_student_dashboard_carries_no_camera_data(api, make_user):
    _uid, headers = make_user("alice")
    body = api.get("/api/dashboard", headers=headers).json()
    assert body["scope"] == "self"
    assert body["cameras"] == []
    assert "review_queue" not in body


def test_only_admin_creates_cameras(api, make_user):
    _f, faculty = make_user("prof", role="faculty")
    _a, admin = make_user("root", role="admin")
    payload = {"name": "door-1", "room": "R1", "source": "0", "mode": "kiosk"}
    assert api.post("/api/cameras", json=payload, headers=faculty).status_code == 403
    assert api.post("/api/cameras", json=payload, headers=admin).status_code == 201


# ---------------------------------------------------------- faculty scoping

def test_faculty_cannot_touch_another_faculty_members_session(api, make_user, make_session):
    p1, _h1 = make_user("prof1", role="faculty")
    _p2, h2 = make_user("prof2", role="faculty")
    student, _ = make_user("alice")
    sid = make_session(p1, roster=[student])

    assert api.get(f"/api/sessions/{sid}/attendance", headers=h2).status_code == 403
    assert api.post(f"/api/sessions/{sid}/recompute", headers=h2).status_code == 403
    assert api.post(f"/api/sessions/{sid}/roster", json={"user_ids": []},
                    headers=h2).status_code == 403
    assert api.get(f"/api/reports/attendance.csv?session_id={sid}",
                   headers=h2).status_code == 403


def test_admin_may_access_any_session(api, make_user, make_session):
    prof, _ = make_user("prof", role="faculty")
    _admin, admin_h = make_user("root", role="admin")
    student, _ = make_user("alice")
    sid = make_session(prof, roster=[student])
    assert api.get(f"/api/sessions/{sid}/attendance", headers=admin_h).status_code == 200


def test_students_cannot_manage_sessions(api, make_user):
    _uid, headers = make_user("alice")
    body = {"title": "X", "room": "R1",
            "scheduled_start": datetime.now(timezone.utc).isoformat(),
            "scheduled_end": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    assert api.post("/api/sessions", json=body, headers=headers).status_code == 403


def test_student_session_list_is_limited_to_their_roster(api, make_user, make_session):
    alice, a_h = make_user("alice")
    bob, _ = make_user("bob")
    prof, _ = make_user("prof", role="faculty")
    mine = make_session(prof, roster=[alice], room="R1")
    theirs = make_session(prof, roster=[bob], room="R2")

    ids = {s["id"] for s in api.get("/api/sessions", headers=a_h).json()}
    assert mine in ids and theirs not in ids


# -------------------------------------------------------------- unauthenticated

@pytest.mark.parametrize("path", [
    "/api/me", "/api/dashboard", "/api/cameras", "/api/sessions",
    "/api/me/attendance", "/api/audit",
])
def test_endpoints_reject_anonymous_callers(api, path):
    assert api.get(path).status_code in (401, 403)


def test_garbage_token_is_rejected(api):
    assert api.get("/api/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401


# ------------------------------------------------------------------- audit

def test_only_admin_reads_the_audit_log(api, make_user):
    _f, faculty = make_user("prof", role="faculty")
    _a, admin = make_user("root", role="admin")
    assert api.get("/api/audit", headers=faculty).status_code == 403
    assert api.get("/api/audit", headers=admin).status_code == 200


def test_student_cannot_erase_another_users_biometrics(api, make_user):
    _alice, a_h = make_user("alice")
    bob, _ = make_user("bob")
    assert api.delete(f"/api/users/{bob}/biometrics", headers=a_h).status_code == 403


def test_student_cannot_enroll_another_user(api, make_user):
    _alice, a_h = make_user("alice")
    bob, _ = make_user("bob")
    files = {"files": ("x.jpg", b"not-an-image", "image/jpeg")}
    assert api.post(f"/api/users/{bob}/enroll", files=files, headers=a_h).status_code == 403
