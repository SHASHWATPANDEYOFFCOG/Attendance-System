"""Phase 5: leaves, issues, messages, announcements, notifications."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from test_portal_sessions import _db, _make_session, klass  # noqa: F401  (fixture re-export)

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _apply(api, h, **over):
    today = datetime.now(timezone.utc).date()
    form = {"type": "medical", "from_date": today.isoformat(), "to_date": today.isoformat(),
            "reason": "Fever", "explanation": "Doctor advised rest for a day."}
    form.update({k: str(v) for k, v in over.items() if not k.startswith("_")})
    files = {"attachment": ("note.pdf", over.get("_file", PDF), "application/pdf")} \
        if over.get("_file", PDF) is not None else None
    return api.post("/api/me/leaves", data=form, files=files, headers=h)


# --------------------------------------------------------------------- leaves

def test_leave_apply_scope_and_approval_rewrites_closed_absence(api, klass):
    from app.models import AttendanceRecordRow

    sid = _make_session(klass)
    api.post(f"/api/sessions/{sid}/stop", headers=klass["teacher_h"])     # student absent
    uid = klass["students"][0]
    r = _apply(api, klass["h"][uid])
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    assert r.json()["attachment"]["content_type"] == "application/pdf"

    # Responsible teacher sees it; a teacher of another class does not.
    assert [x["id"] for x in api.get("/api/leaves", headers=klass["teacher_h"]).json()["rows"]] == [lid]
    assert api.get("/api/leaves", headers=klass["other_h"]).json()["rows"] == []
    assert api.post(f"/api/leaves/{lid}/approve", json={}, headers=klass["other_h"]).status_code == 403
    # The certificate opens for the teacher, not for another student.
    url = r.json()["attachment"]["url"]
    assert api.get(url, headers=klass["teacher_h"]).status_code == 200
    assert api.get(url, headers=klass["h"][klass["students"][1]]).status_code == 404

    out = api.post(f"/api/leaves/{lid}/approve", json={"remark": "Get well"},
                   headers=klass["teacher_h"]).json()
    assert out["status"] == "approved" and out["records_changed"] == 1
    db = _db()
    row = db.query(AttendanceRecordRow).filter_by(session_id=sid, user_id=uid).one()
    db.close()
    assert row.effective_status == "on_leave"
    mine = api.get("/api/me/leaves", headers=klass["h"][uid]).json()
    assert mine[0]["status"] == "approved" and mine[0]["remark"] == "Get well"


def test_leave_validation(api, klass):
    h = klass["h"][klass["students"][0]]
    today = datetime.now(timezone.utc).date()
    r = _apply(api, h, from_date=today, to_date=today - timedelta(days=1))
    assert r.status_code == 422 and r.json()["detail"]["field"] == "to_date"
    r = _apply(api, h, from_date=today - timedelta(days=30), to_date=today - timedelta(days=29))
    assert r.status_code == 422 and "in the past" in r.json()["detail"]["message"]
    r = _apply(api, h, type="holiday")
    assert r.status_code == 422 and r.json()["detail"]["field"] == "type"
    r = _apply(api, h, _file=b"MZ\x90\x00 not a pdf")
    assert r.status_code == 415
    r = _apply(api, h, _file=b"%PDF-" + b"0" * (5 * 1024 * 1024 + 10))
    assert r.status_code == 413
    assert _apply(api, h).status_code == 201
    r = _apply(api, h)
    assert r.status_code == 422 and "overlapping" in r.json()["detail"]["message"]
    r = _apply(api, klass["pending_h"])
    assert r.status_code == 403


def test_leave_edit_and_cancel_only_while_pending(api, klass):
    h = klass["h"][klass["students"][1]]
    lid = _apply(api, h).json()["id"]
    today = datetime.now(timezone.utc).date().isoformat()
    r = api.post(f"/api/me/leaves/{lid}", data={"type": "personal", "from_date": today,
                                                 "to_date": today, "reason": "Family function",
                                                 "remove_attachment": "true"}, headers=h)
    assert r.status_code == 200 and r.json()["type"] == "personal" and r.json()["attachment"] is None
    assert api.delete(f"/api/me/leaves/{lid}", headers=h).json()["status"] == "cancelled"
    assert api.delete(f"/api/me/leaves/{lid}", headers=h).status_code == 409


def test_reject_needs_remark_and_bulk_approve(api, klass):
    a = _apply(api, klass["h"][klass["students"][0]]).json()["id"]
    b = _apply(api, klass["h"][klass["students"][1]]).json()["id"]
    c = _apply(api, klass["h"][klass["students"][2]]).json()["id"]
    assert api.post(f"/api/leaves/{a}/reject", json={}, headers=klass["teacher_h"]).status_code == 422
    assert api.post(f"/api/leaves/{a}/reject", json={"remark": "No certificate"},
                    headers=klass["teacher_h"]).json()["status"] == "rejected"
    r = api.post("/api/leaves/bulk-approve", json={"ids": [b, c]}, headers=klass["teacher_h"])
    assert r.status_code == 200 and r.json()["approved"] == 2
    # Bulk is all-or-nothing: an already-decided id refuses the batch.
    d = _apply(api, klass["h"][klass["students"][3]]).json()["id"]
    r = api.post("/api/leaves/bulk-approve", json={"ids": [d, a]}, headers=klass["teacher_h"])
    assert r.status_code == 409
    assert api.get("/api/leaves?status=pending", headers=klass["teacher_h"]).json()["meta"]["total"] == 1


def test_specific_lecture_leave_only_covers_those_lectures(api, klass):
    from app.models import AttendanceRecordRow

    s1 = _make_session(klass, started_minutes_ago=120)
    s2 = _make_session(klass, started_minutes_ago=60)
    for s in (s1, s2):
        api.post(f"/api/sessions/{s}/stop", headers=klass["teacher_h"])
    uid = klass["students"][2]
    h = klass["h"][uid]
    lectures = api.get(f"/api/me/leaves/lectures?from_date={date.today() - timedelta(days=1)}"
                       f"&to_date={date.today() + timedelta(days=1)}", headers=h).json()
    assert {l["id"] for l in lectures} >= {s1, s2}
    lid = _apply(api, h, session_ids=json.dumps([s1]), _file=None).json()["id"]
    api.post(f"/api/leaves/{lid}/approve", json={}, headers=klass["teacher_h"])
    db = _db()
    st = {r.session_id: r.effective_status
          for r in db.query(AttendanceRecordRow).filter_by(user_id=uid)}
    db.close()
    assert st[s1] == "on_leave" and st[s2] == "absent"


# --------------------------------------------------------------------- issues

def test_issue_thread_status_and_isolation(api, klass):
    a, b = klass["students"][0], klass["students"][1]
    r = api.post("/api/me/issues", data={"category": "attendance_correction",
                                          "title": "Marked absent wrongly",
                                          "description": "I was present in CS301 on Monday."},
                 headers=klass["h"][a])
    assert r.status_code == 201
    iid = r.json()["id"]
    assert api.get(f"/api/issues/{iid}", headers=klass["h"][b]).status_code == 404
    assert api.get(f"/api/issues/{iid}", headers=klass["other_h"]).status_code == 404
    listing = api.get("/api/issues?status=active", headers=klass["teacher_h"]).json()
    assert [i["id"] for i in listing["rows"]] == [iid]

    r = api.post(f"/api/issues/{iid}/comments", data={"body": "Checking the register."},
                 headers=klass["teacher_h"])
    assert r.json()["status"] == "in_progress" and len(r.json()["comments"]) == 1
    # Student cannot resolve; staff can.
    assert api.post(f"/api/issues/{iid}/status", json={"status": "resolved"},
                    headers=klass["h"][a]).status_code == 403
    api.post(f"/api/issues/{iid}/status", json={"status": "resolved"}, headers=klass["teacher_h"])
    assert api.post(f"/api/issues/{iid}/status", json={"status": "closed"},
                    headers=klass["h"][a]).json()["status"] == "closed"
    assert api.post(f"/api/issues/{iid}/comments", data={"body": "thanks"},
                    headers=klass["h"][a]).status_code == 409
    notes = api.get("/api/notifications", headers=klass["h"][a]).json()["rows"]
    assert any(n["type"] == "issue_reply" for n in notes)


# ------------------------------------------------------------------- messages

def test_broadcast_to_section_and_private_replies(api, klass, make_user):
    r = api.post("/api/messages/broadcast", json={"audience": "section", "ids": [klass["section"]],
                                                  "body": "Lab moved to LH-2 tomorrow."},
                 headers=klass["teacher_h"])
    assert r.status_code == 201 and r.json()["sent"] == 4          # approved students only
    a, b = klass["students"][0], klass["students"][1]
    convs = api.get("/api/conversations", headers=klass["h"][a]).json()
    assert len(convs) == 1 and convs[0]["unread"] == 1
    cid = convs[0]["id"]
    thread = api.get(f"/api/conversations/{cid}", headers=klass["h"][a]).json()
    assert thread["messages"][0]["body"].startswith("Lab moved")
    assert api.get("/api/conversations", headers=klass["h"][a]).json()[0]["unread"] == 0
    assert api.get(f"/api/conversations/{cid}", headers=klass["h"][b]).status_code == 404
    r = api.post(f"/api/conversations/{cid}/messages", data={"body": "Noted, thanks"},
                 headers=klass["h"][a])
    assert r.status_code == 201
    counts = api.get("/api/notifications/counts", headers=klass["teacher_h"]).json()
    assert counts["messages"] == 1


def test_teacher_cannot_message_students_outside_scope(api, klass, make_user):
    from app.models import StudentProfile

    outsider, _ = make_user("outsider2")
    db = _db()
    db.add(StudentProfile(user_id=outsider, status="approved"))
    db.commit()
    db.close()
    r = api.post("/api/messages/broadcast", json={"audience": "students", "ids": [outsider],
                                                  "body": "hi"}, headers=klass["teacher_h"])
    assert r.status_code == 403
    r = api.post("/api/messages/broadcast", json={"audience": "all", "body": "hello all"},
                 headers=klass["other_h"])
    assert r.status_code == 422                       # nobody in that teacher's scope


# -------------------------------------------------------------- announcements

def test_announcement_audience_expiry_and_read(api, klass, make_user):
    from app.models import StudentProfile

    stranger, sh = make_user("stranger")
    db = _db()
    db.add(StudentProfile(user_id=stranger, status="approved"))
    db.commit()
    db.close()
    r = api.post("/api/announcements", data={"title": "Mid-sem schedule",
                                              "body": "Exams start on the 12th.",
                                              "audience_type": "section",
                                              "audience_ids": json.dumps([klass["section"]]),
                                              "pinned": "true", "send_email": "true"},
                 files={"attachment": ("schedule.pdf", PDF, "application/pdf")},
                 headers=klass["teacher_h"])
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    h = klass["h"][klass["students"][0]]
    mine = api.get("/api/announcements", headers=h).json()
    assert [a["id"] for a in mine] == [aid] and mine[0]["pinned"]
    assert api.get("/api/announcements", headers=sh).json() == []
    assert api.get(mine[0]["attachment"]["url"], headers=h).status_code == 200
    assert api.get(mine[0]["attachment"]["url"], headers=sh).status_code == 404
    assert api.get("/api/notifications/counts", headers=h).json()["announcements"] == 1
    api.post(f"/api/announcements/{aid}/read", headers=h)
    assert api.get("/api/notifications/counts", headers=h).json()["announcements"] == 0

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    r = api.post("/api/announcements", data={"title": "Old", "body": "x", "expires_at": past},
                 headers=klass["teacher_h"])
    assert r.status_code == 422


def test_announcement_email_is_queued_and_delivered(api, klass):
    from app.db import SessionLocal
    from app.models import Notification
    from app.notify import dispatch_emails

    api.post("/api/announcements", data={"title": "Holiday notice", "body": "Closed Friday.",
                                          "send_email": "true"}, headers=klass["teacher_h"])
    db = SessionLocal()
    queued = db.query(Notification).filter_by(channel="email", type="announcement").count()
    out = dispatch_emails(db, "http://x", "College")
    db.close()
    # Students in the fixture have no email address; recipients without one get in-app only.
    assert out["sent"] == queued


# --------------------------------------------------------------- notifications

def test_notifications_list_and_mark_read(api, klass):
    h = klass["h"][klass["students"][0]]
    api.post("/api/messages/broadcast", json={"audience": "students",
                                              "ids": [klass["students"][0]], "body": "See me"},
             headers=klass["teacher_h"])
    rows = api.get("/api/notifications?unread_only=true", headers=h).json()["rows"]
    assert rows and rows[0]["type"] == "message" and not rows[0]["read"]
    api.post("/api/notifications/read", json={}, headers=h)
    assert api.get("/api/notifications/counts", headers=h).json()["notifications"] == 0


def test_personal_stream_never_receives_another_users_events():
    import asyncio

    from app.bus import Event, EventBus

    bus = EventBus()
    loop = asyncio.new_event_loop()
    try:
        bus.bind_loop(loop)
        mine = bus.subscribe(user_id=1)
        staff = bus.subscribe(session_id=None)
        bus.publish(Event(kind="notification", payload={"x": 1}, user_id=2))
        bus.publish(Event(kind="notification", payload={"x": 2}, user_id=1))
        bus.publish(Event(kind="record_updated", payload={}, session_id=5))
        assert mine.qsize() == 1 and mine.get_nowait().payload == {"x": 2}
        assert staff.qsize() == 1 and staff.get_nowait().kind == "record_updated"
    finally:
        loop.close()


def test_weekly_digest_is_idempotent(api, klass):
    from app import digest
    from app.models import Notification
    from app.runtime import cfg

    sid = _make_session(klass)
    api.post(f"/api/sessions/{sid}/stop", headers=klass["teacher_h"])
    db = _db()
    n1 = digest.run(db, cfg, force=True)
    assert n1 == 4
    monday = datetime(2026, 10, 5, 4, 0, tzinfo=timezone.utc)      # 09:30 IST Monday
    from app import settings_service

    settings_service.update(db, cfg, {"weekly_summary_enabled": True}, None)
    db.commit()
    first = digest.run(db, cfg, now=monday)
    second = digest.run(db, cfg, now=monday + timedelta(minutes=10))
    db.close()
    assert first == 4 and second == 0
