"""Classroom attendance from the authority side: a tablet photo, or a camera connected by hand.

Tablet photo
    The teacher photographs the class (one or several photos). The server finds every face,
    matches each ONLY against this lecture's approved roster, and returns proposals — nothing is
    written. The teacher ticks who is really there and confirms; only then are records made
    (method "photo", marked_by = the teacher). Photos are processed in memory and never stored;
    faces that match nobody are not identified or kept.

Connect a camera
    Any registered camera can be attached to a running lecture regardless of its room (a spare
    camera, a camera moved for an exam hall). The worker then serves that lecture, and stops when
    the lecture ends like an auto-started camera.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_service
from app.audit import audit
from app.auth import assert_owns_session, require_staff
from app.db import get_db
from app.gallery_service import match_among, user_templates
from app.models import (
    AttendanceRecordRow,
    AttendanceStatus,
    Camera,
    CaptureMethod,
    ClassSession,
    SessionState,
    StudentProfile,
    User,
    utcnow,
)
from app.runtime import cfg
from app.session_service import approved_roster, record_mark, window_status
from app.uploads import MB, read_limited

router = APIRouter(prefix="/api", tags=["class-photo"])

MAX_PHOTO = 15 * MB
MAX_SIDE = 2400          # larger photos are scaled down: detection does not need more, CPU does


def _live_session(db: Session, actor: User, session_id: int) -> ClassSession:
    s = db.get(ClassSession, session_id)
    if s is None or s.deleted_at is not None:
        raise HTTPException(404, "session not found")
    assert_owns_session(actor, s)
    if s.state != SessionState.ACTIVE.value:
        raise HTTPException(409, "Start the lecture first. Attendance can only be taken while it is live.")
    return s


# ------------------------------------------------------------------ analyse

def _box(face, w: int, h: int) -> Optional[List[float]]:
    bbox = getattr(face, "bbox", None)
    if bbox is None or not w or not h:
        return None
    x1, y1, x2, y2 = [float(v) for v in bbox]
    return [round(max(0.0, x1 / w), 4), round(max(0.0, y1 / h), 4),
            round(min(1.0, x2 / w), 4), round(min(1.0, y2 / h), 4)]


def analyse_photo(db: Session, session: ClassSession, img, pipeline) -> dict:
    roster = approved_roster(db, session)
    templates = user_templates(db, cfg, roster)
    match_thr = float(settings_service.get(db, cfg, "face_match_threshold"))
    review_thr = float(settings_service.get(db, cfg, "face_review_threshold"))
    h, w = (img.shape[:2] if isinstance(img, np.ndarray) else (0, 0))

    faces = []
    for face in pipeline.detect(img):
        entry: Dict = {"box": _box(face, w, h), "verdict": "unknown", "score": None}
        chip = pipeline.align(img, face)
        passed, _q, _occ, _spoof = pipeline.assess(chip, face.det_score)
        if not passed:
            entry["verdict"] = "unclear"           # blurred / turned away: retake or mark by hand
            faces.append(entry)
            continue
        uid, score = match_among(pipeline.embed(img, face, chip), templates)
        entry["score"] = round(score, 3)
        if uid is not None and score >= match_thr:
            entry.update(verdict="match", user_id=uid)
        elif uid is not None and score >= review_thr:
            entry.update(verdict="maybe", user_id=uid)
        faces.append(entry)

    # One person, one face: if two faces matched the same student keep the stronger and
    # demote the other — something is off (a poster, a reflection), the teacher decides.
    best: Dict[int, Dict] = {}
    for f in faces:
        uid = f.get("user_id")
        if uid is None:
            continue
        if uid in best and best[uid]["score"] >= f["score"]:
            f["verdict"], f["duplicate"] = "duplicate", True
            continue
        if uid in best:
            best[uid]["verdict"], best[uid]["duplicate"] = "duplicate", True
        best[uid] = f

    marked = {r.user_id: r.effective_status for r in db.scalars(select(AttendanceRecordRow).where(
        AttendanceRecordRow.session_id == session.id))}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(list(best) or [-1])))}
    profiles = {p.user_id: p for p in db.scalars(select(StudentProfile).where(
        StudentProfile.user_id.in_(list(best) or [-1])))}
    for f in faces:
        uid = f.get("user_id")
        if uid is None:
            # Unknown or unclear: no identity is attached, and not even the closest score —
            # a near-miss must not hint at who the face resembles.
            f.pop("score", None)
            continue
        u, p = users.get(uid), profiles.get(uid)
        f.update(name=u.display_name if u else None,
                 roll_number=(p.roll_number if p else None) or (u.roll_number if u else None),
                 photo_url=f"/api/files/{p.photo_file_id}" if p and p.photo_file_id else None,
                 already=marked.get(uid))
    return {
        "faces": faces,
        "roster_size": len(roster),
        "enrolled": len(templates),
        "counts": {v: sum(1 for f in faces if f["verdict"] == v)
                   for v in ("match", "maybe", "duplicate", "unclear", "unknown")},
        "thresholds": {"match": match_thr, "review": review_thr},
    }


@router.post("/sessions/{session_id}/class-photo")
async def class_photo(session_id: int, request: Request, photo: UploadFile = File(...),
                      db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    s = _live_session(db, actor, session_id)
    from app.routes import face as face_mod                 # decode/pipeline shared with selfies

    data = await read_limited(photo, MAX_PHOTO)
    img = face_mod.decode(data)
    if img is None:
        raise HTTPException(422, "That photo could not be read. Take it again.")
    if isinstance(img, np.ndarray) and max(img.shape[:2]) > MAX_SIDE:
        scale = MAX_SIDE / max(img.shape[:2])
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    result = analyse_photo(db, s, img, face_mod._pipeline())
    audit(db, actor, "class_photo_analysed", target_type="session", target_id=s.id,
          detail=result["counts"], request=request)
    db.commit()
    return result


class ConfirmIn(BaseModel):
    user_ids: List[int] = Field(min_length=1, max_length=500)
    scores: Dict[int, float] = {}


@router.post("/sessions/{session_id}/class-photo/confirm")
def confirm_class_photo(session_id: int, body: ConfirmIn, request: Request,
                        db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Mark the students the teacher confirmed from the photo. Present / late follow the time
    windows; after the late window a student the teacher saw in class is marked late."""
    s = _live_session(db, actor, session_id)
    roster = set(approved_roster(db, s))
    outside = [u for u in body.user_ids if u not in roster]
    if outside:
        raise HTTPException(422, f"{len(outside)} selected student(s) are not on this lecture's roster.")
    status = window_status(s, utcnow(), db, cfg) or AttendanceStatus.LATE.value
    marked, already = [], []
    for uid in dict.fromkeys(body.user_ids):
        user = db.get(User, uid)
        score = body.scores.get(uid)
        _row, created = record_mark(
            db, s, user, CaptureMethod.PHOTO.value, cfg, status=status,
            confidence=score, marked_by=actor,
            evidence="class photo" + (f", match {score:.3f}" if score is not None else "")
                     + f", confirmed by {actor.display_name}")
        (marked if created else already).append(uid)
    audit(db, actor, "class_photo_confirmed", target_type="session", target_id=s.id,
          detail={"marked": len(marked), "already": len(already), "status": status}, request=request)
    db.commit()
    return {"marked": len(marked), "already": len(already), "status": status}


# ------------------------------------------------------------ connect a camera

def _camera_out(cam: Optional[Camera]) -> Optional[dict]:
    if cam is None:
        return None
    from app.worker import registry

    return {"id": cam.id, "name": cam.name, "room": cam.room,
            "status": getattr(cam.status, "value", cam.status), "detail": cam.status_detail,
            "running": registry.is_running(cam.id), "last_heartbeat": cam.last_heartbeat}


@router.get("/sessions/{session_id}/camera")
def session_camera(session_id: int, db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    s = db.get(ClassSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    assert_owns_session(actor, s)
    linked = db.get(Camera, s.camera_id) if s.camera_id else None
    in_room = [c for c in db.scalars(select(Camera).where(Camera.room == s.room, Camera.enabled.is_(True)))]
    return {"connected": _camera_out(linked),
            "in_room": [_camera_out(c) for c in in_room],
            "available": [_camera_out(c) for c in db.scalars(
                select(Camera).where(Camera.enabled.is_(True)).order_by(Camera.name))]}


class ConnectIn(BaseModel):
    camera_id: int


@router.post("/sessions/{session_id}/camera")
def connect_camera(session_id: int, body: ConnectIn, request: Request,
                   db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    from app import camera_manager
    from app.worker import registry

    s = _live_session(db, actor, session_id)
    cam = db.get(Camera, body.camera_id)
    if cam is None or not cam.enabled:
        raise HTTPException(404, "That camera does not exist or is switched off in CCTV cameras.")
    other = db.scalars(select(ClassSession).where(
        ClassSession.camera_id == cam.id, ClassSession.id != s.id,
        ClassSession.state == SessionState.ACTIVE.value)).first()
    if other is not None:
        raise HTTPException(409, f"{cam.name} is connected to another live lecture ({other.title}). "
                                 f"Disconnect it there first.")
    s.camera_id = cam.id
    db.commit()
    if not registry.is_running(cam.id):
        registry.start(cam.id, cfg)
    camera_manager.mark_managed(cam.id)                     # stops with the lecture
    audit(db, actor, "camera_connected", target_type="session", target_id=s.id,
          detail={"camera_id": cam.id, "camera": cam.name}, request=request)
    db.commit()
    return {"connected": _camera_out(cam)}


@router.delete("/sessions/{session_id}/camera")
def disconnect_camera(session_id: int, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_staff)):
    from app import camera_manager
    from app.worker import registry

    s = db.get(ClassSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    assert_owns_session(actor, s)
    cam = db.get(Camera, s.camera_id) if s.camera_id else None
    if cam is None:
        raise HTTPException(409, "No camera is connected to this lecture.")
    s.camera_id = None
    db.commit()
    # Keep it running only if a live lecture in its own room still needs it.
    if camera_manager.lecture_for(db, cam) is None and registry.is_running(cam.id):
        registry.stop(cam.id)
        camera_manager.forget(cam.id)
    audit(db, actor, "camera_disconnected", target_type="session", target_id=s.id,
          detail={"camera_id": cam.id}, request=request)
    db.commit()
    return {"connected": None}


@router.get("/sessions/{session_id}/camera/preview")
def camera_preview(session_id: int, db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """One frame from the lecture's camera, so the teacher can check what it sees. Not stored."""
    from app.cctv import grab_frame, jpeg_data_url, stream_url

    s = db.get(ClassSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    assert_owns_session(actor, s)
    cam = db.get(Camera, s.camera_id) if s.camera_id else None
    if cam is None:
        raise HTTPException(409, "No camera is connected to this lecture.")
    frame, error = grab_frame(stream_url(cam))
    if frame is None:
        return {"ok": False, "error": error}
    return {"ok": True, "preview": jpeg_data_url(frame)}
