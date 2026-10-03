"""Phase 7: CCTV — roster-only matching, marking, review queue, unknowns, credentials, health.

Same scope note as test_worker_integration.py: the real tracker, confirmation state machine,
roster matching, marking and review paths run; the two CNNs are scripted. Accuracy on real faces
needs real cameras and real people.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from app.crypto import encrypt_embedding
from app.db import SessionLocal
from app.gallery_service import invalidate
from occlubio.pipeline.face_analyzer import FaceResult
from occlubio.utils import l2_normalize
from test_worker_integration import FakeCapture, live_cfg, run_worker  # noqa: F401


def _vec_with_cosine(t: np.ndarray, cos: float, seed: int) -> np.ndarray:
    r = np.random.default_rng(seed).normal(size=t.size).astype(np.float32)
    r -= (r @ t) * t
    r /= np.linalg.norm(r)
    return l2_normalize(cos * t + np.sqrt(1 - cos ** 2) * r)


class Scripted:
    """Three people in view: an enrolled match, a near match, and a stranger."""

    antispoof_available = False

    def __init__(self, embeddings):
        self.embeddings = embeddings
        self.boxes = [np.array([50 + 200 * i, 50, 150 + 200 * i, 170], np.float32)
                      for i in range(len(embeddings))]

    def detect(self, frame):
        out = []
        for i, box in enumerate(self.boxes):
            kps = np.array([[box[0] + 20, 90], [box[0] + 60, 90], [box[0] + 40, 115],
                            [box[0] + 22, 140], [box[0] + 58, 140]], np.float32)
            f = FaceResult(bbox=box.copy(), kps=kps, det_score=0.95)
            f.meta = {"who": i}
            out.append(f)
        return out

    def align(self, frame, face):
        return np.full((112, 112, 3), 100 + 40 * face.meta["who"], np.uint8)

    def assess(self, chip, det_score):
        return True, 0.85, {"type": "clear", "occluded_ratio": 0.05}, {"live": True, "score": 1.0}

    def embed(self, frame, face, chip):
        return self.embeddings[face.meta["who"]]


@pytest.fixture()
def room(api, make_user, tmp_path, monkeypatch):
    """A lecture running in R1 with a camera; students A and B enrolled, stranger C is not."""
    from app.models import (Camera, ClassSession, Enrollment, RosterEntry, Section,
                            StudentProfile)

    monkeypatch.setenv("ATTENDANCE_REVIEW_DIR", str(tmp_path / "review"))
    t_id, t_h = make_user("cctv.teacher", role="faculty")
    a, a_h = make_user("stu.a")
    b, b_h = make_user("stu.b")
    rng = np.random.default_rng(11)
    tpl = {a: l2_normalize(rng.normal(size=512).astype(np.float32)),
           b: l2_normalize(rng.normal(size=512).astype(np.float32))}
    db = SessionLocal()
    try:
        for uid, t in tpl.items():
            db.add(StudentProfile(user_id=uid, status="approved"))
            db.add(Enrollment(user_id=uid, embedding_encrypted=encrypt_embedding(t), dim=512,
                              n_images=5, mean_quality=0.8, min_quality=0.7, status="approved"))
        cam = Camera(name="lh1-cam", room="R1", source="fake", auto_start=True)
        db.add(cam)
        db.flush()
        start = datetime.now(timezone.utc) - timedelta(minutes=2)
        s = ClassSession(title="CS301 Period", room="R1", owner_id=t_id, scheduled_start=start,
                         scheduled_end=start + timedelta(minutes=50), capture_method="manual",
                         state="active", camera_id=cam.id)
        db.add(s)
        db.flush()
        for uid in tpl:
            db.add(RosterEntry(session_id=s.id, user_id=uid))
        db.commit()
        out = {"teacher": t_id, "teacher_h": t_h, "a": a, "b": b, "a_h": a_h, "tpl": tpl,
               "camera_id": cam.id, "session_id": s.id}
    finally:
        db.close()
    invalidate()
    return out


def _records(session_id):
    from app.models import AttendanceRecordRow

    db = SessionLocal()
    try:
        return {r.user_id: r for r in db.query(AttendanceRecordRow).filter_by(session_id=session_id)}
    finally:
        db.close()


def test_cctv_marks_matches_queues_near_misses_and_ignores_strangers(api, room, live_cfg, monkeypatch):
    from app.models import ReviewItem, Sighting, UnknownSighting

    stranger = l2_normalize(np.random.default_rng(99).normal(size=512).astype(np.float32))
    near = _vec_with_cosine(room["tpl"][room["b"]], 0.38, seed=5)   # review band [0.32, 0.45)
    pipeline = Scripted([room["tpl"][room["a"]], near, stranger])
    run_worker(monkeypatch, live_cfg, room["camera_id"], pipeline, FakeCapture, seconds=7.0)

    recs = _records(room["session_id"])
    assert room["a"] in recs, "the enrolled student was not marked"
    assert recs[room["a"]].source == "cctv" and recs[room["a"]].effective_status == "present"
    assert room["b"] not in recs, "a near match must never be auto-marked"

    db = SessionLocal()
    try:
        items = db.query(ReviewItem).filter_by(session_id=room["session_id"]).all()
        assert [i.user_id for i in items] == [room["b"]]
        assert items[0].snapshot_path and Path(items[0].snapshot_path).exists()
        raw = Path(items[0].snapshot_path).read_bytes()
        assert not raw.startswith(b"\xff\xd8"), "review crop must be encrypted on disk"
        assert db.query(UnknownSighting).count() == 0, "an unknown face was stored"
        users = {s.user_id for s in db.query(Sighting).all()}
        assert users <= {room["a"], room["b"]}
        assert all(s.thumbnail_path is None for s in db.query(Sighting).all())
    finally:
        db.close()


def test_review_queue_accept_and_reject(api, room, live_cfg, monkeypatch):
    from app.cctv import save_review_crop
    from app.models import ReviewItem

    db = SessionLocal()
    try:
        crop = save_review_crop(np.full((112, 112, 3), 90, np.uint8))
        item = ReviewItem(session_id=room["session_id"], user_id=room["b"], score=0.39,
                          frames=4, seen_at=datetime.now(timezone.utc), snapshot_path=crop,
                          reason="near match")
        db.add(item)
        db.commit()
        iid = item.id
    finally:
        db.close()
    q = api.get(f"/api/review-queue?session_id={room['session_id']}", headers=room["teacher_h"]).json()
    assert q[0]["snapshot"].startswith("data:image/jpeg;base64,")
    assert api.get(f"/api/review-queue?session_id={room['session_id']}",
                   headers=room["a_h"]).status_code == 403
    r = api.post(f"/api/review-queue/{iid}/accept", json={}, headers=room["teacher_h"]).json()
    assert r["marked"] == "present"
    assert _records(room["session_id"])[room["b"]].source == "cctv"
    assert not Path(crop).exists(), "the crop must be deleted once decided"


def test_late_arrival_is_marked_late(api, room, live_cfg, monkeypatch):
    from app.models import ClassSession

    db = SessionLocal()
    try:
        s = db.get(ClassSession, room["session_id"])
        s.scheduled_start = datetime.now(timezone.utc) - timedelta(minutes=15)
        db.commit()
    finally:
        db.close()
    pipeline = Scripted([room["tpl"][room["a"]]])
    run_worker(monkeypatch, live_cfg, room["camera_id"], pipeline, FakeCapture)
    assert _records(room["session_id"])[room["a"]].effective_status == "late"


def test_offline_camera_during_lecture_alerts_teacher_once(api, room, live_cfg, monkeypatch):
    from app.models import Camera, CameraStatus, Notification

    class DeadCapture(FakeCapture):
        def isOpened(self):
            return False

    run_worker(monkeypatch, live_cfg, room["camera_id"], Scripted([]), DeadCapture, seconds=4.0)
    db = SessionLocal()
    try:
        cam = db.get(Camera, room["camera_id"])
        assert cam.status in (CameraStatus.OFFLINE.value, CameraStatus.STOPPED.value, "offline", "stopped")
        alerts = db.query(Notification).filter_by(type="camera_offline", channel="inapp",
                                                  user_id=room["teacher"]).count()
        assert alerts == 1
    finally:
        db.close()


def test_camera_credentials_are_encrypted_masked_and_never_returned(api, make_user, monkeypatch):
    from app.cctv import mask_source, stream_url
    from app.models import Camera

    _, admin = make_user("cam.admin", role="super_admin")
    r = api.post("/api/cameras", json={"name": "c1", "room": "R9",
                                        "source": "rtsp://admin:secret@10.0.0.5:554/stream1"},
                 headers=admin)
    assert r.status_code == 422                       # credentials belong in their own fields
    r = api.post("/api/cameras", json={"name": "c1", "room": "R9", "source": "rtsp://10.0.0.5:554/stream1",
                                        "username": "admin", "password": "s3cr@t/1"}, headers=admin)
    assert r.status_code == 201 and r.json()["has_credentials"]
    assert "s3cr" not in r.text and "admin" not in r.json()["source"]
    db = SessionLocal()
    cam = db.query(Camera).filter_by(name="c1").one()
    db.close()
    assert b"s3cr" not in (cam.password_encrypted or b"")
    assert stream_url(cam) == "rtsp://admin:s3cr%40t%2F1@10.0.0.5:554/stream1"
    assert mask_source(stream_url(cam)) == "rtsp://***@10.0.0.5:554/stream1"
    listed = api.get("/api/cameras", headers=admin).text
    assert "s3cr" not in listed

    import app.routes.cameras as cams

    monkeypatch.setattr(cams, "grab_frame", lambda url: (np.zeros((480, 640, 3), np.uint8), ""))
    t = api.post(f"/api/cameras/{cam.id}/test", headers=admin).json()
    assert t["ok"] and t["width"] == 640 and t["preview"].startswith("data:image/jpeg")
    monkeypatch.setattr(cams, "grab_frame", lambda url: (None, "No response within 12 seconds."))
    t = api.post(f"/api/cameras/{cam.id}/test", headers=admin).json()
    assert not t["ok"] and "No response" in t["error"]


def test_camera_manager_starts_and_stops_with_lectures(api, room, monkeypatch):
    from app import camera_manager
    from app.models import ClassSession
    from app.runtime import cfg
    import app.worker as worker_mod

    running = set()
    monkeypatch.setattr(worker_mod.registry, "is_running", lambda cid: cid in running)
    monkeypatch.setattr(worker_mod.registry, "start", lambda cid, c: running.add(cid))
    monkeypatch.setattr(worker_mod.registry, "stop", lambda cid: running.discard(cid) or True)

    db = SessionLocal()
    try:
        assert camera_manager.tick(db, cfg)["started"] == 1
        assert room["camera_id"] in running
        s = db.get(ClassSession, room["session_id"])
        s.state = "closed"
        db.commit()
        assert camera_manager.tick(db, cfg)["stopped"] == 1
        assert not running
    finally:
        db.close()


def test_review_snapshots_expire(api, room, tmp_path):
    from app.cctv import save_review_crop
    from app.models import ReviewItem
    from app.routes.cameras import purge_review_snapshots

    db = SessionLocal()
    try:
        crop = save_review_crop(np.full((112, 112, 3), 90, np.uint8))
        db.add(ReviewItem(session_id=room["session_id"], user_id=room["b"], score=0.4, frames=3,
                          seen_at=datetime.now(timezone.utc), snapshot_path=crop,
                          created_at=datetime.now(timezone.utc) - timedelta(days=8)))
        db.commit()
        assert purge_review_snapshots(db, 7) == 1
        assert not Path(crop).exists()
        assert db.query(ReviewItem).one().status == "expired"
    finally:
        db.close()
