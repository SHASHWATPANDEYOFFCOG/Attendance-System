"""Phase 6: face enrollment (consent, quality, liveness, duplicates, review) and selfie marking.

A fake pipeline stands in for InsightFace. Each "frame" is a small JSON document describing what
the camera would see (how many faces, head pose, which person, blur, spoof), so every rule the
server applies can be exercised exactly. Real-model accuracy needs real people and a real camera.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from test_portal_sessions import CAMPUS, _db, _make_session, klass  # noqa: F401

POSES = {"front": (0.0, 0.5), "left": (0.25, 0.5), "right": (-0.25, 0.5),
         "up": (0.0, 0.40), "down": (0.0, 0.60)}


def _kps(yaw: float, pitch: float) -> np.ndarray:
    eye_y, mouth_y = 50.0, 90.0
    return np.array([[40, eye_y], [80, eye_y], [60 + yaw * 40, eye_y + pitch * (mouth_y - eye_y)],
                     [48, mouth_y], [72, mouth_y]], dtype=np.float32)


def frame(pose="front", person=1, faces=1, blur=False, live=True, small=False) -> bytes:
    return json.dumps({"pose": pose, "person": person, "faces": faces, "blur": blur,
                       "live": live, "small": small}).encode()


class FakePipeline:
    antispoof_available = False

    def __init__(self):
        self._last = None

    def detect(self, f):
        side = 30 if f["small"] else 200
        yaw, pitch = POSES[f["pose"]]
        return [SimpleNamespace(kps=_kps(yaw, pitch), wh=(side, side), det_score=0.9,
                                embedding=None, src=f) for _ in range(f["faces"])]

    def align(self, img, face):
        self._last = face.src
        if face.src["blur"]:
            return np.full((112, 112, 3), 128, np.uint8)             # sharpness 0 -> blurry
        rng = np.random.default_rng(7)
        return rng.integers(60, 200, (112, 112, 3), dtype=np.uint8)

    def assess(self, chip, det_score):
        live = self._last["live"]
        return (not self._last["blur"], 0.9, {"type": "clear", "occluded_ratio": 0.0},
                {"live": live, "score": 1.0 if live else 0.0})

    def embed(self, img, face, chip):
        base = np.random.default_rng(face.src["person"]).normal(size=512)
        noise = np.random.default_rng().normal(scale=0.05, size=512)
        v = (base + noise).astype(np.float32)
        return v / np.linalg.norm(v)


@pytest.fixture()
def fake(api, monkeypatch):
    import app.pipeline_service as ps
    import app.routes.face as face_mod

    p = FakePipeline()
    monkeypatch.setattr(ps, "_instance", p)
    monkeypatch.setattr(face_mod, "decode", lambda data: json.loads(data))
    return p


def _consent(api, h):
    assert api.post("/api/me/face/consent", json={"consent": True}, headers=h).status_code == 200


def _enroll(api, h, *, person=1, override=None, steps_override=None):
    ch = api.post("/api/me/face/challenge", json={"purpose": "enroll"}, headers=h).json()
    steps = steps_override or ch["steps"]
    files = []
    for i, step in enumerate(steps):
        data = (override or {}).get(i) or frame(step, person=person)
        files.append(("images", (f"{i}.jpg", data, "image/jpeg")))
    return api.post("/api/me/face/enroll", data={"challenge_id": ch["id"]}, files=files, headers=h), ch


def _approve_face(api, klass, uid):
    pending = api.get("/api/face-enrollments", headers=klass["teacher_h"]).json()
    eid = next(e["id"] for e in pending if e["student_id"] == uid)
    assert api.post(f"/api/face-enrollments/{eid}/approve", json={},
                    headers=klass["teacher_h"]).status_code == 200


# --------------------------------------------------------------- enrollment

def test_consent_is_required_and_pending_accounts_cannot_enroll(api, klass, fake):
    h = klass["h"][klass["students"][0]]
    # Test users are created with consent; withdraw it to start from "not consented".
    api.post("/api/me/face/consent", json={"consent": False}, headers=h)
    r, _ = _enroll(api, h)
    assert r.status_code == 403 and "consent" in r.json()["detail"]
    _consent(api, klass["pending_h"])
    r, _ = _enroll(api, klass["pending_h"])
    assert r.status_code == 403 and "approved" in r.json()["detail"]


def test_enroll_review_and_approve(api, klass, fake):
    uid = klass["students"][0]
    h = klass["h"][uid]
    _consent(api, h)
    r, ch = _enroll(api, h)
    assert r.status_code == 201, r.text
    assert ch["steps"][0] == "front" and sorted(ch["steps"][1:]) == ["down", "left", "right", "up"]
    assert api.get("/api/me/face", headers=h).json()["enrollment"] == "pending"
    assert api.get("/api/me", headers=h).json()["has_biometrics"] is False   # not live yet

    listing = api.get("/api/face-enrollments", headers=klass["teacher_h"]).json()
    assert [e["student_id"] for e in listing] == [uid] and listing[0]["liveness_passed"]
    assert api.get("/api/face-enrollments", headers=klass["other_h"]).json() == []
    eid = listing[0]["id"]
    samples = api.get(f"/api/face-enrollments/{eid}/samples", headers=klass["teacher_h"]).json()
    assert len(samples["images"]) == 5 and samples["images"][0].startswith("data:image/jpeg")
    assert api.get(f"/api/face-enrollments/{eid}/samples",
                   headers=klass["other_h"]).status_code == 403

    _approve_face(api, klass, uid)
    assert api.get("/api/me", headers=h).json()["has_biometrics"] is True
    from app.models import Enrollment

    db = _db()
    row = db.get(Enrollment, eid)
    db.close()
    assert row.status == "approved" and row.samples_encrypted is None      # photos wiped


@pytest.mark.parametrize("bad,expect", [
    (frame("front", faces=0), "No face found"),
    (frame("front", faces=2), "2 faces"),
    (frame("front", blur=True), "blurry"),
    (frame("front", small=True), "too small"),
])
def test_enroll_rejects_bad_frames(api, klass, fake, bad, expect):
    h = klass["h"][klass["students"][0]]
    _consent(api, h)
    r, _ = _enroll(api, h, override={0: bad})
    assert r.status_code == 422 and expect in r.json()["detail"]["message"]


def test_printed_photo_or_phone_screen_fails_liveness(api, klass, fake):
    """A static image never shows the head turning: every frame has the front pose."""
    h = klass["h"][klass["students"][0]]
    _consent(api, h)
    still = {i: frame("front") for i in range(5)}
    r, _ = _enroll(api, h, override=still)
    assert r.status_code == 422
    assert r.json()["detail"]["kind"] == "liveness"


def test_poses_in_the_wrong_order_fail_liveness(api, klass, fake):
    h = klass["h"][klass["students"][0]]
    _consent(api, h)
    ch = api.post("/api/me/face/challenge", json={"purpose": "enroll"}, headers=h).json()
    wrong = ["front"] + list(reversed(ch["steps"][1:]))
    files = [("images", (f"{i}.jpg", frame(s), "image/jpeg")) for i, s in enumerate(wrong)]
    r = api.post("/api/me/face/enroll", data={"challenge_id": ch["id"]}, files=files, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["kind"] == "liveness"
    # The challenge is single-use: replaying it with the right answers is refused too.
    files = [("images", (f"{i}.jpg", frame(s), "image/jpeg")) for i, s in enumerate(ch["steps"])]
    r = api.post("/api/me/face/enroll", data={"challenge_id": ch["id"]}, files=files, headers=h)
    assert r.status_code == 422 and "already used" in r.json()["detail"]["message"]


def test_antispoof_rejection_when_a_model_is_configured(api, klass, fake):
    fake.antispoof_available = True
    h = klass["h"][klass["students"][0]]
    _consent(api, h)
    r, _ = _enroll(api, h)
    assert r.status_code == 201                                          # live frames pass
    h2 = klass["h"][klass["students"][1]]
    _consent(api, h2)
    ch = api.post("/api/me/face/challenge", json={"purpose": "enroll"}, headers=h2).json()
    files = [("images", (f"{i}.jpg", frame(s, person=2, live=False), "image/jpeg"))
             for i, s in enumerate(ch["steps"])]
    r = api.post("/api/me/face/enroll", data={"challenge_id": ch["id"]}, files=files, headers=h2)
    assert r.status_code == 422 and r.json()["detail"]["kind"] == "spoof"


def test_duplicate_face_is_refused_and_teacher_flagged(api, klass, fake):
    a, b = klass["students"][0], klass["students"][1]
    _consent(api, klass["h"][a])
    _enroll(api, klass["h"][a], person=1)
    _approve_face(api, klass, a)
    _consent(api, klass["h"][b])
    r, _ = _enroll(api, klass["h"][b], person=1)                         # same face, other account
    assert r.status_code == 409 and r.json()["detail"]["kind"] == "duplicate"
    notes = api.get("/api/notifications", headers=klass["teacher_h"]).json()["rows"]
    assert any(n["type"] == "face_duplicate" for n in notes)
    # Two people cannot both be waiting with the same face either.
    c = klass["students"][2]
    _consent(api, klass["h"][c])
    assert _enroll(api, klass["h"][c], person=9)[0].status_code == 201
    d = klass["students"][3]
    _consent(api, klass["h"][d])
    assert _enroll(api, klass["h"][d], person=9)[0].status_code == 409


def test_reenrollment_needs_an_approved_request(api, klass, fake):
    uid = klass["students"][0]
    h = klass["h"][uid]
    _consent(api, h)
    _enroll(api, h)
    _approve_face(api, klass, uid)
    r, _ = _enroll(api, h)
    assert r.status_code == 409
    rid = api.post("/api/me/face/reenroll-request", json={"reason": "Grew a beard"}, headers=h).json()["id"]
    assert api.post(f"/api/reenroll-requests/{rid}/approve", json={},
                    headers=klass["teacher_h"]).status_code == 200
    r, _ = _enroll(api, h)
    assert r.status_code == 201
    assert api.get("/api/me/face", headers=h).json()["enrollment"] == "approved"  # old one live


def test_withdrawing_consent_erases_face_data(api, klass, fake):
    from app.models import Enrollment

    uid = klass["students"][0]
    h = klass["h"][uid]
    _consent(api, h)
    _enroll(api, h)
    _approve_face(api, klass, uid)
    r = api.post("/api/me/face/consent", json={"consent": False}, headers=h).json()
    assert r["consent_given"] is False and r["enrollment"] == "none"
    db = _db()
    assert db.query(Enrollment).filter_by(user_id=uid).count() == 0
    db.close()


# ------------------------------------------------------------- selfie marking

def _selfie(api, h, sid, *, person=1, still=False, lat=CAMPUS[0]):
    ch = api.post("/api/me/face/challenge", json={"purpose": "attendance", "session_id": sid},
                  headers=h).json()
    steps = ch["steps"]
    files = [("frames", (f"{i}.jpg", frame("front" if still else s, person=person), "image/jpeg"))
             for i, s in enumerate(steps)]
    return api.post(f"/api/attendance/sessions/{sid}/self-mark",
                    data={"challenge_id": ch["id"], "lat": lat, "lng": CAMPUS[1], "accuracy": 10},
                    files=files, headers=h)


def test_selfie_mark_success_and_failure_modes(api, klass, fake):
    uid = klass["students"][0]
    h = klass["h"][uid]
    _consent(api, h)
    _enroll(api, h, person=1)
    sid = _make_session(klass)

    r = _selfie(api, h, sid)
    assert r.status_code == 409 and "not enrolled" in r.json()["detail"]["message"]  # not approved yet
    _approve_face(api, klass, uid)

    r = _selfie(api, h, sid, person=5)
    assert r.status_code == 403 and "did not match" in r.json()["detail"]["message"]
    r = _selfie(api, h, sid, still=True)
    assert r.status_code == 422 and r.json()["detail"]["kind"] == "liveness"
    r = _selfie(api, h, sid, lat=CAMPUS[0] + 0.1)
    assert r.status_code == 403 and "outside campus" in r.json()["detail"]["message"]
    assert r.json()["detail"]["attempts_left"] == 0
    r = _selfie(api, h, sid)
    assert r.status_code == 429                                          # three strikes


def test_selfie_mark_records_mobile_with_confidence(api, klass, fake):
    from app.models import AttendanceRecordRow

    uid = klass["students"][1]
    h = klass["h"][uid]
    _consent(api, h)
    _enroll(api, h, person=3)
    _approve_face(api, klass, uid)
    sid = _make_session(klass)
    r = _selfie(api, h, sid, person=3)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "present" and r.json()["confidence"] > 0.8
    db = _db()
    row = db.query(AttendanceRecordRow).filter_by(session_id=sid, user_id=uid).one()
    db.close()
    assert row.source == "mobile" and row.confidence > 0.8
    assert _selfie(api, h, sid, person=3).status_code == 409


def test_legacy_self_enroll_endpoint_now_waits_for_review(api, klass, monkeypatch):
    """web/enroll.html still works, but a student's own upload is pending until a teacher checks it."""
    import app.api as api_mod
    from app.enroll import EnrollmentOutcome

    captured = {}

    def fake_enroll(db, target, images, cfg, pipeline, actor_is_staff=False, status="approved"):
        captured["status"] = status
        return EnrollmentOutcome(enrollment_id=1, n_accepted=5, mean_quality=0.9, min_quality=0.9)

    monkeypatch.setattr(api_mod, "enroll_user", fake_enroll)
    uid = klass["students"][0]
    files = [("files", (f"{i}.jpg", b"x", "image/jpeg")) for i in range(5)]
    api.post(f"/api/users/{uid}/enroll", files=files, headers=klass["h"][uid])
    assert captured["status"] == "pending"
    api.post(f"/api/users/{uid}/enroll", files=files, headers=klass["teacher_h"])
    assert captured["status"] == "approved"
