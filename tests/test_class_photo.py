"""Authority-side attendance: a tablet photo of the class, and connecting a camera by hand."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from test_portal_face import POSES, FakePipeline, _approve_face, _consent, _enroll, _kps
from test_portal_sessions import _db, _make_session, klass  # noqa: F401


class ClassPhotoFake(FakePipeline):
    """A "photo" is JSON: {"people": [1, 2, 77], "blur": [77]} — one face per listed person."""

    def detect(self, f):
        if "people" not in f:                     # an enrolment frame
            return super().detect(f)
        faces = []
        for i, person in enumerate(f["people"]):
            src = {"person": person, "blur": person in f.get("blur", []), "live": True}
            faces.append(SimpleNamespace(kps=_kps(*POSES["front"]), wh=(120, 120), det_score=0.9,
                                         bbox=(i * 200 + 10, 50, i * 200 + 130, 170), src=src))
        return faces


@pytest.fixture()
def fake(api, monkeypatch):
    import app.pipeline_service as ps
    import app.routes.face as face_mod

    p = ClassPhotoFake()
    monkeypatch.setattr(ps, "_instance", p)
    monkeypatch.setattr(face_mod, "decode", lambda data: json.loads(data))
    return p


@pytest.fixture()
def enrolled(api, klass, fake):
    """Students 0 and 1 have approved faces (persons 1 and 2); students 2 and 3 have none."""
    for person, uid in ((1, klass["students"][0]), (2, klass["students"][1])):
        h = klass["h"][uid]
        _consent(api, h)
        r, _ = _enroll(api, h, person=person)
        assert r.status_code == 201, r.text
        _approve_face(api, klass, uid)
    return klass


def _photo(api, h, sid, **scene):
    return api.post(f"/api/sessions/{sid}/class-photo",
                    files={"photo": ("class.jpg", json.dumps(scene).encode(), "image/jpeg")}, headers=h)


def test_photo_proposes_matches_only_from_the_roster_and_keeps_strangers_anonymous(api, enrolled):
    sid = _make_session(enrolled)
    r = _photo(api, enrolled["teacher_h"], sid, people=[1, 2, 77])
    assert r.status_code == 200, r.text
    body = r.json()
    matched = {f["user_id"] for f in body["faces"] if f["verdict"] == "match"}
    assert matched == {enrolled["students"][0], enrolled["students"][1]}
    stranger = next(f for f in body["faces"] if f["verdict"] == "unknown")
    assert set(stranger) <= {"box", "verdict"}             # no name, no score, no closest match
    assert all("box" in f for f in body["faces"])          # None here: the fake photo has no pixels
    assert body["roster_size"] == 4 and body["enrolled"] == 2

    # Nothing is written until the teacher confirms.
    db = _db()
    from app.models import AttendanceRecordRow
    assert db.query(AttendanceRecordRow).filter_by(session_id=sid).count() == 0
    db.close()


def test_confirm_marks_the_ticked_students_once(api, enrolled):
    sid = _make_session(enrolled)
    ids = enrolled["students"][:2]
    r = api.post(f"/api/sessions/{sid}/class-photo/confirm",
                 json={"user_ids": ids, "scores": {str(ids[0]): 0.81}}, headers=enrolled["teacher_h"])
    assert r.status_code == 200 and r.json() == {"marked": 2, "already": 0, "status": "present"}
    live = api.get(f"/api/sessions/{sid}/live", headers=enrolled["teacher_h"]).json()
    rows = {row["user_id"]: row for row in live["roster"]}
    assert rows[ids[0]]["status"] == "present" and rows[ids[0]]["method"] == "photo"
    # A second photo of the same students changes nothing.
    again = api.post(f"/api/sessions/{sid}/class-photo/confirm", json={"user_ids": ids},
                     headers=enrolled["teacher_h"]).json()
    assert again["marked"] == 0 and again["already"] == 2
    # The student sees it in their history.
    hist = api.get("/api/me/history", headers=enrolled["h"][ids[0]]).json()
    assert any(r.get("method") == "tablet photo" for r in hist.get("rows", hist))


def test_after_the_late_window_a_student_seen_in_class_is_late(api, enrolled):
    sid = _make_session(enrolled, started_minutes_ago=40, length=60)
    r = api.post(f"/api/sessions/{sid}/class-photo/confirm",
                 json={"user_ids": [enrolled["students"][0]]}, headers=enrolled["teacher_h"])
    assert r.json()["status"] == "late"


def test_duplicates_and_unclear_faces_are_flagged_for_the_teacher(api, enrolled):
    sid = _make_session(enrolled)
    faces = _photo(api, enrolled["teacher_h"], sid, people=[1, 1, 2], blur=[2]).json()["faces"]
    verdicts = sorted(f["verdict"] for f in faces)
    assert verdicts == ["duplicate", "duplicate", "unclear"] or verdicts == ["duplicate", "match", "unclear"]
    assert sum(f["verdict"] == "unclear" for f in faces) == 1


def test_only_this_lectures_staff_may_use_it_and_only_while_live(api, enrolled):
    sid = _make_session(enrolled)
    student_h = enrolled["h"][enrolled["students"][0]]
    assert _photo(api, student_h, sid, people=[1]).status_code == 403
    assert _photo(api, enrolled["other_h"], sid, people=[1]).status_code in (403, 404)
    r = api.post(f"/api/sessions/{sid}/class-photo/confirm", json={"user_ids": [enrolled["pending"]]},
                 headers=enrolled["teacher_h"])
    assert r.status_code == 422                               # not approved -> not on the roster
    closed = _make_session(enrolled, state="scheduled")
    assert _photo(api, enrolled["teacher_h"], closed, people=[1]).status_code == 409


# ------------------------------------------------------------------ connect a camera

@pytest.fixture()
def no_workers(monkeypatch):
    """Record start/stop instead of opening real streams."""
    import app.worker as worker

    running: set = set()
    monkeypatch.setattr(worker.registry, "start", lambda cid, cfg: running.add(cid))
    monkeypatch.setattr(worker.registry, "stop", lambda cid: running.discard(cid) or True)
    monkeypatch.setattr(worker.registry, "is_running", lambda cid: cid in running)
    return running


def test_connect_any_camera_to_a_live_lecture_and_disconnect(api, klass, no_workers):
    cam = api.post("/api/cameras", json={"name": "Spare cam", "room": "Store", "source": "rtsp://10.0.0.9/s1"},
                   headers=klass["admin"]).json()["id"]
    sid = _make_session(klass)
    h = klass["teacher_h"]

    listing = api.get(f"/api/sessions/{sid}/camera", headers=h).json()
    assert listing["connected"] is None and any(c["id"] == cam for c in listing["available"])

    r = api.post(f"/api/sessions/{sid}/camera", json={"camera_id": cam}, headers=h)
    assert r.status_code == 200 and r.json()["connected"]["running"] is True
    assert cam in no_workers

    other = _make_session(klass)
    assert api.post(f"/api/sessions/{other}/camera", json={"camera_id": cam}, headers=h).status_code == 409
    assert api.post(f"/api/sessions/{sid}/camera", json={"camera_id": cam},
                    headers=klass["h"][klass["students"][0]]).status_code == 403

    # The worker serves the connected lecture even though the camera's room differs.
    from app.camera_manager import lecture_for
    from app.models import Camera
    db = _db()
    assert lecture_for(db, db.get(Camera, cam)).id == sid
    db.close()

    assert api.delete(f"/api/sessions/{sid}/camera", headers=h).status_code == 200
    assert cam not in no_workers
    assert api.get(f"/api/sessions/{sid}/camera", headers=h).json()["connected"] is None


def test_face_boxes_are_given_as_fractions_of_the_photo():
    from app.routes.class_photo import _box

    face = SimpleNamespace(bbox=(100, 50, 300, 250))
    assert _box(face, 1000, 500) == [0.1, 0.1, 0.3, 0.5]
    assert _box(SimpleNamespace(), 1000, 500) is None
