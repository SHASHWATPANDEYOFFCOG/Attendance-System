"""End-to-end worker tests driven by a fake camera.

SCOPE - READ THIS BEFORE TRUSTING THESE TESTS
---------------------------------------------
These exercise the **real** IoU tracker, the **real** FAISS gallery (with encrypted templates
loaded from the database), the **real** confirmation state machine, real session resolution, real
sighting writes and the real recompute path. The two CNNs are stubbed: detection returns scripted
boxes and embedding returns the enrolled template.

So they prove the attendance machinery is correctly wired. They do **not** prove that face
recognition works on real faces under occlusion - only a benchmark on real enrolled identities
can do that (see tools/roc.py and the Part A gate in README.md).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.crypto import encrypt_embedding
from app.db import SessionLocal
from app.gallery_service import invalidate
from app.models import Camera, CameraStatus, ClassSession, Enrollment, RosterEntry, Sighting, User
from occlubio.pipeline.face_analyzer import FaceResult
from occlubio.utils import l2_normalize

FRAME_INTERVAL_S = 0.025          # ~40 fps source
N_FRAMES = 160                    # ~4 s, enough to clear min_span_seconds comfortably


# ------------------------------------------------------------- fake hardware

class FakeCapture:
    """Stands in for cv2.VideoCapture. Optionally dies partway to test reconnection."""

    def __init__(self, n_frames=N_FRAMES, die_after=None):
        self.n = n_frames
        self.die_after = die_after
        self.i = 0
        self.opened = True
        self.reads = 0

    def isOpened(self):
        return self.opened

    def set(self, *_a):
        return True

    def read(self):
        time.sleep(FRAME_INTERVAL_S)
        self.reads += 1
        if self.die_after is not None and self.reads > self.die_after:
            return False, None
        if self.i >= self.n:
            return False, None
        self.i += 1
        return True, np.zeros((480, 640, 3), np.uint8)

    def release(self):
        self.opened = False


class ScriptedPipeline:
    """Returns fixed boxes and the enrolled template for each of two people."""

    antispoof_available = False

    def __init__(self, templates):
        self.templates = templates            # list of 512-d unit vectors
        self.boxes = [
            np.array([50, 50, 150, 170], np.float32),
            np.array([300, 50, 400, 170], np.float32),
        ][: len(templates)]

    def detect(self, frame):
        out = []
        for idx, box in enumerate(self.boxes):
            kps = np.array([[70, 90], [110, 90], [90, 115], [72, 140], [108, 140]], np.float32)
            f = FaceResult(bbox=box.copy(), kps=kps, det_score=0.95)
            f.meta = {"who": idx}
            out.append(f)
        return out

    def align(self, frame, face):
        return np.full((112, 112, 3), 128, np.uint8)

    def assess(self, chip, det_score):
        return True, 0.85, {"type": "clear", "occluded_ratio": 0.05}, {"live": True, "score": 1.0}

    def embed(self, frame, face, chip):
        return self.templates[face.meta["who"]]


# ------------------------------------------------------------------ fixtures

@pytest.fixture()
def two_enrolled(api, cfg):
    """Two users with real encrypted templates in the DB and a rebuilt FAISS index."""
    from app.crypto import hash_password
    from app.models import Role

    rng = np.random.default_rng(7)
    templates = [l2_normalize(rng.normal(size=512).astype(np.float32)) for _ in range(2)]

    db = SessionLocal()
    try:
        ids = []
        for i, tpl in enumerate(templates):
            u = User(username=f"person{i}", display_name=f"Person {i}", role=Role.STUDENT,
                     password_hash=hash_password("password123"), consent_given=True,
                     consent_at=datetime.now(timezone.utc))
            db.add(u)
            db.commit()
            db.refresh(u)
            db.add(Enrollment(user_id=u.id, embedding_encrypted=encrypt_embedding(tpl),
                              dim=512, n_images=5, mean_quality=0.8, min_quality=0.7))
            db.commit()
            ids.append(u.id)

        prof = User(username="prof", display_name="Prof", role=Role.FACULTY,
                    password_hash=hash_password("password123"))
        db.add(prof)
        db.commit()
        db.refresh(prof)

        cam = Camera(name="door-1", room="R1", source="fake", mode="kiosk")
        db.add(cam)
        db.commit()
        db.refresh(cam)

        start = datetime.now(timezone.utc) - timedelta(minutes=2)
        s = ClassSession(title="Live", room="R1", camera_id=cam.id, owner_id=prof.id,
                         scheduled_start=start, scheduled_end=start + timedelta(minutes=50),
                         mode="kiosk", grace_minutes=10, min_presence_seconds=1500)
        db.add(s)
        db.commit()
        db.refresh(s)
        for uid in ids:
            db.add(RosterEntry(session_id=s.id, user_id=uid))
        db.commit()

        invalidate()
        return {"user_ids": ids, "templates": templates, "camera_id": cam.id,
                "session_id": s.id, "prof_id": prof.id}
    finally:
        db.close()


@pytest.fixture()
def live_cfg(cfg):
    """Anti-spoof set to permissive so the worker will actually run.

    The shipped default is `strict`, which refuses to start without PAD weights. That refusal is
    itself a requirement and has its own test below.
    """
    cfg.attendance.antispoof_mode = "permissive"
    return cfg


def run_worker(monkeypatch, cfg, camera_id, pipeline, capture_factory, seconds=6.0):
    """Start a CameraWorker against a fake capture and let it run."""
    from app import worker as worker_mod

    monkeypatch.setattr(worker_mod, "get_pipeline", lambda _c: pipeline)
    monkeypatch.setattr(worker_mod.CameraWorker, "_open",
                        staticmethod(lambda source: capture_factory()))

    w = worker_mod.CameraWorker(camera_id, cfg, pipeline=pipeline)
    w.start()
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.1)
        db = SessionLocal()
        try:
            if db.query(Sighting).filter(Sighting.confirmed.is_(True)).count() >= 2:
                break
        finally:
            db.close()
    w.stop()
    w.join(timeout=10)
    return w


def confirmed_per_user():
    db = SessionLocal()
    try:
        counts = {}
        for s in db.query(Sighting).filter(Sighting.confirmed.is_(True)).all():
            counts[s.user_id] = counts.get(s.user_id, 0) + 1
        return counts
    finally:
        db.close()


# ----------------------------------------------------------- anti-spoof gate

def test_strict_mode_refuses_to_start_without_pad_weights(api, cfg, monkeypatch, two_enrolled):
    """B9: with no PAD weights, a strict-mode camera must refuse to run at all."""
    assert str(cfg.attendance.antispoof_mode) == "strict", "the shipped default must be strict"

    pipeline = ScriptedPipeline(two_enrolled["templates"])
    run_worker(monkeypatch, cfg, two_enrolled["camera_id"], pipeline, FakeCapture, seconds=2.0)

    assert confirmed_per_user() == {}, "a strict-mode camera stamped someone present without PAD"
    db = SessionLocal()
    try:
        cam = db.get(Camera, two_enrolled["camera_id"])
        assert cam.status == CameraStatus.ERROR
        assert "anti-spoof" in (cam.status_detail or "").lower()
    finally:
        db.close()


# --------------------------------------------------------------------- tests

def test_two_people_are_confirmed_and_recorded(api, live_cfg, monkeypatch, two_enrolled):
    pipeline = ScriptedPipeline(two_enrolled["templates"])
    run_worker(monkeypatch, live_cfg, two_enrolled["camera_id"], pipeline, FakeCapture)

    db = SessionLocal()
    try:
        confirmed = db.query(Sighting).filter(Sighting.confirmed.is_(True)).all()
        assert len(confirmed) == 2, f"expected 2 confirmed check-ins, got {len(confirmed)}"
        assert {s.user_id for s in confirmed} == set(two_enrolled["user_ids"])
        for s in confirmed:
            assert s.session_id == two_enrolled["session_id"], "session resolution failed"
            assert s.frames_matched >= live_cfg.attendance.confirm_frames
            assert s.median_confidence >= live_cfg.gallery.match_threshold
            assert s.antispoof_result == "not_evaluated"
    finally:
        db.close()


def test_cooldown_prevents_duplicate_checkins_while_loitering(api, live_cfg, monkeypatch,
                                                              two_enrolled):
    """The faces never leave frame; the worker must still record exactly one check-in each."""
    pipeline = ScriptedPipeline(two_enrolled["templates"])
    run_worker(monkeypatch, live_cfg, two_enrolled["camera_id"], pipeline, FakeCapture, seconds=8.0)

    counts = confirmed_per_user()
    assert counts, "no check-ins were recorded at all"
    assert all(v == 1 for v in counts.values()), counts


def test_records_and_csv_agree_after_a_live_run(api, live_cfg, monkeypatch, two_enrolled):
    import csv as csvmod
    import io

    from app.auth import create_token

    pipeline = ScriptedPipeline(two_enrolled["templates"])
    run_worker(monkeypatch, live_cfg, two_enrolled["camera_id"], pipeline, FakeCapture)

    db = SessionLocal()
    try:
        prof = db.get(User, two_enrolled["prof_id"])
        headers = {"Authorization": f"Bearer {create_token(prof, 'access')}"}
    finally:
        db.close()

    sid = two_enrolled["session_id"]
    api.post(f"/api/sessions/{sid}/recompute", headers=headers)
    body = api.get(f"/api/sessions/{sid}/attendance", headers=headers).json()
    statuses = {r["user_id"]: r["effective_status"] for r in body["records"]}
    assert set(statuses) == set(two_enrolled["user_ids"])
    assert all(v == "present" for v in statuses.values()), statuses

    text = api.get(f"/api/reports/attendance.csv?session_id={sid}", headers=headers).text
    rows = {int(r["user_id"]): r["effective_status"] for r in csvmod.DictReader(io.StringIO(text))}
    assert rows == statuses


def test_confirmed_tracks_stop_being_embedded(api, live_cfg, monkeypatch, two_enrolled):
    """The largest CPU saving available - verify embedding actually stops after confirmation."""
    pipeline = ScriptedPipeline(two_enrolled["templates"])
    calls = {"n": 0}
    real_embed = pipeline.embed

    def counting_embed(frame, face, chip):
        calls["n"] += 1
        return real_embed(frame, face, chip)

    run_seconds = 8.0
    pipeline.embed = counting_embed
    run_worker(monkeypatch, live_cfg, two_enrolled["camera_id"], pipeline, FakeCapture,
               seconds=run_seconds)
    after_stop = calls["n"]

    time.sleep(0.3)
    assert calls["n"] == after_stop, "embedding continued after both tracks were confirmed"

    # Confirmation is gated by min_span_seconds, not by confirm_frames: at this frame rate and
    # stride, each person needs ~min_span_seconds of evidence before they can be confirmed.
    processed_per_s = (1.0 / FRAME_INTERVAL_S) / live_cfg.attendance.detect_every_n_frames
    floor = 2 * live_cfg.attendance.min_span_seconds * processed_per_s
    unoptimised = 2 * processed_per_s * run_seconds

    assert after_stop < unoptimised / 2, (
        f"embedded {after_stop} times; skipping confirmed tracks should keep this far below "
        f"the {unoptimised:.0f} an unoptimised loop would do")
    assert after_stop < floor * 3, (after_stop, floor)


def test_stream_drop_triggers_reconnect_without_duplicate_checkins(api, live_cfg, monkeypatch,
                                                                   two_enrolled):
    """A camera that dies mid-session must reconnect, and must not re-stamp anyone."""
    from app import worker as worker_mod

    opened = {"n": 0}

    def factory():
        opened["n"] += 1
        # The first capture dies early; the reconnected one runs normally.
        return FakeCapture(die_after=45) if opened["n"] == 1 else FakeCapture()

    pipeline = ScriptedPipeline(two_enrolled["templates"])
    monkeypatch.setattr(worker_mod, "get_pipeline", lambda _c: pipeline)
    monkeypatch.setattr(worker_mod.CameraWorker, "_open", staticmethod(lambda source: factory()))

    w = worker_mod.CameraWorker(two_enrolled["camera_id"], live_cfg, pipeline=pipeline)
    w.backoff = [1]                       # keep the test short
    w.start()
    time.sleep(10.0)
    w.stop()
    w.join(timeout=10)

    assert opened["n"] >= 2, "the worker did not attempt to reconnect after the stream dropped"

    counts = confirmed_per_user()
    assert counts, "no check-ins survived the reconnect"
    assert all(v == 1 for v in counts.values()), f"duplicate check-ins after reconnect: {counts}"

    db = SessionLocal()
    try:
        assert db.get(Camera, two_enrolled["camera_id"]).last_heartbeat is not None
    finally:
        db.close()


def test_disk_spool_replays_after_a_database_outage(api, live_cfg, two_enrolled, tmp_path):
    """Events buffered to disk during an outage must land in the database afterwards."""
    from app import worker as worker_mod

    spool = tmp_path / "spool.jsonl"
    w = worker_mod.CameraWorker(two_enrolled["camera_id"], live_cfg)
    w.spool = spool

    uid = two_enrolled["user_ids"][0]
    w._spool({"kind": "sighting", "camera_id": two_enrolled["camera_id"], "user_id": uid,
              "session_id": two_enrolled["session_id"], "track_id": 3, "frames": 7,
              "confidence": 0.71, "confirmed": True,
              "at": datetime.now(timezone.utc).isoformat()})
    assert spool.exists()

    db = SessionLocal()
    try:
        w._flush_spool(db)
        rows = db.query(Sighting).filter(Sighting.user_id == uid, Sighting.track_id == 3).all()
        assert len(rows) == 1
        assert "spool" in (rows[0].review_reason or "")
    finally:
        db.close()
    assert not spool.exists(), "spool should be cleared once flushed"


def test_unscheduled_checkin_when_no_session_is_active(api, live_cfg, monkeypatch, two_enrolled):
    """No scheduled session -> session_id NULL. The worker must never guess a session."""
    db = SessionLocal()
    try:
        s = db.get(ClassSession, two_enrolled["session_id"])
        s.scheduled_start = datetime.now(timezone.utc) + timedelta(days=2)
        s.scheduled_end = s.scheduled_start + timedelta(minutes=50)
        db.commit()
    finally:
        db.close()

    pipeline = ScriptedPipeline(two_enrolled["templates"])
    run_worker(monkeypatch, live_cfg, two_enrolled["camera_id"], pipeline, FakeCapture)

    db = SessionLocal()
    try:
        confirmed = db.query(Sighting).filter(Sighting.confirmed.is_(True)).all()
        assert confirmed, "no check-ins were recorded at all"
        assert all(s.session_id is None for s in confirmed), \
            "an out-of-hours check-in was attached to a scheduled session"
    finally:
        db.close()
