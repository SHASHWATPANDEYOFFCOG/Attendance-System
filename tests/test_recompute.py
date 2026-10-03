"""Recompute, overrides, CSV parity, retention and erasure.

The premise under test: attendance records are derived data. Wipe them, rebuild from the
immutable sighting log, and nothing changes — except human overrides, which outrank derivation
and must survive.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import AttendanceRecordRow, AuditLog, Sighting, User


def add_sighting(session_id, user_id, start_min=1, end_min=1, *, confirmed=True,
                 needs_review=False, reason=None, frames=8, conf=0.62, occ=0.1,
                 base=None, camera_id=None):
    base = base or (datetime.now(timezone.utc) - timedelta(minutes=5))
    db = SessionLocal()
    try:
        row = Sighting(
            session_id=session_id, camera_id=camera_id, user_id=user_id, track_id=1,
            first_seen=base + timedelta(minutes=start_min),
            last_seen=base + timedelta(minutes=end_min),
            frames_matched=frames, median_confidence=conf, max_confidence=conf,
            best_quality=0.7, mean_occluded_ratio=occ, confirmed=confirmed,
            antispoof_result="not_evaluated", needs_review=needs_review, review_reason=reason,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def records_of(client, headers, sid):
    return client.get(f"/api/sessions/{sid}/attendance", headers=headers).json()["records"]


# --------------------------------------------------------------- determinism

def test_wipe_and_recompute_reproduces_identical_records(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    bob, _ = make_user("bob")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    sid = make_session(prof, roster=[alice, bob], start=start)
    add_sighting(sid, alice, 1, 1, base=start)

    before = records_of(api, h, sid)
    assert before, "no records were computed"

    db = SessionLocal()
    try:
        db.query(AttendanceRecordRow).delete()
        db.commit()
    finally:
        db.close()

    assert api.post(f"/api/sessions/{sid}/recompute", headers=h).status_code == 200
    after = records_of(api, h, sid)

    key = lambda rs: sorted((r["user_id"], r["status"], r["total_visible_s"],
                             r["frames_matched"], r["needs_review"]) for r in rs)
    assert key(before) == key(after)


def test_recompute_is_idempotent(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    sid = make_session(prof, roster=[alice], start=start)
    add_sighting(sid, alice, 1, 1, base=start)

    api.post(f"/api/sessions/{sid}/recompute", headers=h)
    first = records_of(api, h, sid)
    api.post(f"/api/sessions/{sid}/recompute", headers=h)
    second = records_of(api, h, sid)
    assert [r["status"] for r in first] == [r["status"] for r in second]


def test_absent_when_no_sighting_exists(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    sid = make_session(prof, roster=[alice])
    assert records_of(api, h, sid)[0]["status"] == "absent"


def test_unconfirmed_sighting_yields_review_not_absent(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    sid = make_session(prof, roster=[alice], start=start)
    add_sighting(sid, alice, 1, 1, confirmed=False, needs_review=True,
                 reason="track lost before confirmation", base=start)

    rec = records_of(api, h, sid)[0]
    assert rec["status"] == "needs_review"
    assert rec["status"] != "absent"


# ----------------------------------------------------------------- overrides

def test_override_requires_a_reason(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    sid = make_session(prof, roster=[alice])
    rid = records_of(api, h, sid)[0]["id"]

    assert api.patch(f"/api/attendance/{rid}", json={"status": "present"},
                     headers=h).status_code == 422
    assert api.patch(f"/api/attendance/{rid}", json={"status": "present", "reason": "ok"},
                     headers=h).status_code == 422       # too short (min_length=3)


def test_override_applies_and_is_audit_logged(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    sid = make_session(prof, roster=[alice])
    rid = records_of(api, h, sid)[0]["id"]

    r = api.patch(f"/api/attendance/{rid}",
                  json={"status": "present", "reason": "arrived, camera was offline"}, headers=h)
    assert r.status_code == 200
    assert r.json()["effective_status"] == "present"

    db = SessionLocal()
    try:
        entry = db.query(AuditLog).filter(AuditLog.action == "attendance_override").one()
        assert entry.reason == "arrived, camera was offline"
        assert "absent -> present" in entry.detail
    finally:
        db.close()


def test_override_survives_recompute(api, make_user, make_session):
    """A human decision outranks a derived one."""
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    sid = make_session(prof, roster=[alice])
    rid = records_of(api, h, sid)[0]["id"]

    api.patch(f"/api/attendance/{rid}",
              json={"status": "present", "reason": "verified in person"}, headers=h)
    api.post(f"/api/sessions/{sid}/recompute", headers=h)

    rec = records_of(api, h, sid)[0]
    assert rec["status"] == "absent", "the derived status should still be recorded"
    assert rec["effective_status"] == "present", "the override was lost on recompute"
    assert rec["override_reason"] == "verified in person"


def test_student_cannot_override(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, a_h = make_user("alice")
    sid = make_session(prof, roster=[alice])
    rid = records_of(api, h, sid)[0]["id"]
    assert api.patch(f"/api/attendance/{rid}",
                     json={"status": "present", "reason": "please"}, headers=a_h).status_code == 403


# ----------------------------------------------------------------- csv parity

def test_csv_matches_json(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice", display_name="Alice A")
    bob, _ = make_user("bob", display_name="Bob B")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    sid = make_session(prof, roster=[alice, bob], start=start)
    add_sighting(sid, alice, 1, 1, base=start)

    json_rows = {r["user_id"]: r for r in records_of(api, h, sid)}
    csv_text = api.get(f"/api/reports/attendance.csv?session_id={sid}", headers=h).text
    csv_rows = {int(r["user_id"]): r for r in csv.DictReader(io.StringIO(csv_text))}

    assert set(csv_rows) == set(json_rows)
    for uid, jrow in json_rows.items():
        assert csv_rows[uid]["effective_status"] == jrow["effective_status"]
        assert csv_rows[uid]["status"] == jrow["status"]
        assert float(csv_rows[uid]["total_visible_s"]) == pytest.approx(jrow["total_visible_s"])


def test_csv_export_is_audit_logged(api, make_user, make_session):
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    sid = make_session(prof, roster=[alice])
    api.get(f"/api/reports/attendance.csv?session_id={sid}", headers=h)

    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter(AuditLog.action == "export_csv").count() == 1
    finally:
        db.close()


# ------------------------------------------------------- privacy operations

def test_erasure_drops_templates_but_keeps_attendance(api, make_user, make_session, cfg):
    from app.attendance_service import erase_biometrics
    from app.crypto import encrypt_embedding
    from app.models import Enrollment
    import numpy as np

    prof, h = make_user("prof", role="faculty")
    alice, a_h = make_user("alice")
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    sid = make_session(prof, roster=[alice], start=start)
    add_sighting(sid, alice, 1, 1, base=start)
    records_of(api, h, sid)

    db = SessionLocal()
    try:
        db.add(Enrollment(user_id=alice, embedding_encrypted=encrypt_embedding(
            np.ones(512, dtype=np.float32)), dim=512, n_images=5, mean_quality=0.7))
        db.commit()
        assert db.query(Enrollment).filter(Enrollment.user_id == alice).count() == 1
    finally:
        db.close()

    r = api.delete(f"/api/users/{alice}/biometrics", headers=a_h)
    assert r.status_code == 200
    assert r.json()["templates_deleted"] == 1
    assert r.json()["attendance_history_retained"] is True

    db = SessionLocal()
    try:
        assert db.query(Enrollment).filter(Enrollment.user_id == alice).count() == 0
        assert db.query(AttendanceRecordRow).filter(
            AttendanceRecordRow.user_id == alice).count() == 1
        assert db.get(User, alice).consent_given is False
        assert db.query(AuditLog).filter(AuditLog.action == "erase_biometrics").count() == 1
    finally:
        db.close()


def test_retention_sweep_is_admin_only_and_logged(api, make_user):
    _f, faculty = make_user("prof", role="faculty")
    _a, admin = make_user("root", role="admin")
    assert api.post("/api/admin/retention", headers=faculty).status_code == 403

    r = api.post("/api/admin/retention", headers=admin)
    assert r.status_code == 200
    assert "cutoff_utc" in r.json()

    db = SessionLocal()
    try:
        assert db.query(AuditLog).filter(AuditLog.action == "retention_sweep").count() == 1
    finally:
        db.close()


def test_unscheduled_sightings_are_excluded_from_a_session(api, make_user, make_session):
    """A sighting with no session must never leak into another session's roll."""
    prof, h = make_user("prof", role="faculty")
    alice, _ = make_user("alice")
    sid = make_session(prof, roster=[alice])
    add_sighting(None, alice, 1, 1)          # unscheduled
    assert records_of(api, h, sid)[0]["status"] == "absent"
