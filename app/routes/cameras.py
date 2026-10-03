"""Camera management beyond create/list/start/stop (which live in app/api.py), and the CCTV
review queue.

* Editing never echoes credentials back; leaving the password field empty keeps the stored one.
* "Test connection" opens the stream with the real credentials, grabs one frame, and returns it
  as a preview image — kept in memory only, never written to disk.
* Review queue: near-threshold or late CCTV matches. The teacher sees the encrypted face crop
  (decrypted on request) and accepts (the student is marked) or rejects. Crops are deleted on
  decision, and by the retention job after `review_retention_days` if nobody decides.
"""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth import assert_owns_session, require_admin, require_staff
from app.cctv import (
    delete_review_crop,
    grab_frame,
    jpeg_data_url,
    load_review_crop,
    mask_source,
    stream_url,
)
from app.crypto import encrypt_text
from app.db import get_db
from app.models import (
    AttendanceRecordRow,
    CaptureMethod,
    Camera,
    ClassSession,
    ReviewItem,
    Room,
    User,
    utcnow,
)
from app.runtime import cfg
from app.scope import student_scope_clause
from app.models import StudentProfile

router = APIRouter(prefix="/api", tags=["cameras"])


class CameraUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    room: Optional[str] = Field(None, min_length=1, max_length=80)
    source: Optional[str] = Field(None, min_length=1, max_length=512)
    username: Optional[str] = Field(None, max_length=120)
    password: Optional[str] = Field(None, max_length=200)
    clear_credentials: bool = False
    enabled: Optional[bool] = None
    auto_start: Optional[bool] = None
    mode: Optional[str] = None


def _cam(db: Session, camera_id: int) -> Camera:
    c = db.get(Camera, camera_id)
    if c is None:
        raise HTTPException(404, "camera not found")
    return c


@router.patch("/cameras/{camera_id}")
def update_camera(camera_id: int, body: CameraUpdateIn, request: Request,
                  db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    from app.api import _camera_out

    c = _cam(db, camera_id)
    changes = body.model_dump(exclude_unset=True)
    if "source" in changes and mask_source(changes["source"]) != changes["source"]:
        raise HTTPException(422, "Put the username and password in their own fields.")
    for k in ("name", "room", "source", "enabled", "auto_start", "mode"):
        if k in changes and changes[k] is not None:
            setattr(c, k, changes[k].strip() if isinstance(changes[k], str) else changes[k])
    if body.clear_credentials:
        c.username_encrypted = c.password_encrypted = None
    if body.username:
        c.username_encrypted = encrypt_text(body.username)
    if body.password:
        c.password_encrypted = encrypt_text(body.password)
    if c.room and db.scalars(select(Room).limit(1)).first() is not None and \
            db.scalars(select(Room).where(Room.name == c.room)).first() is None:
        raise HTTPException(422, f"Room {c.room} does not exist. Add it under Setup → Rooms.")
    audit(db, actor, "camera_updated", target_type="camera", target_id=c.id,
          detail={k: ("***" if k in ("username", "password") else v)
                  for k, v in changes.items()}, request=request)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "a camera with that name already exists")
    return _camera_out(c)


@router.delete("/cameras/{camera_id}")
def delete_camera(camera_id: int, request: Request, db: Session = Depends(get_db),
                  actor: User = Depends(require_admin)):
    from app.worker import registry

    c = _cam(db, camera_id)
    registry.stop(camera_id)
    for s in db.scalars(select(ClassSession).where(ClassSession.camera_id == camera_id)):
        s.camera_id = None
    db.delete(c)
    audit(db, actor, "camera_deleted", target_type="camera", target_id=camera_id,
          detail={"name": c.name}, request=request)
    db.commit()
    return {"deleted": camera_id}


@router.post("/cameras/{camera_id}/test")
def test_camera(camera_id: int, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    """Open the stream and return one frame. The image is never stored."""
    c = _cam(db, camera_id)
    t0 = time.perf_counter()
    frame, error = grab_frame(stream_url(c))
    took = round((time.perf_counter() - t0) * 1000)
    audit(db, actor, "camera_tested", target_type="camera", target_id=c.id,
          detail={"ok": frame is not None, "ms": took}, request=request)
    db.commit()
    if frame is None:
        return {"ok": False, "error": error, "ms": took, "source": mask_source(c.source)}
    h, w = frame.shape[:2]
    return {"ok": True, "ms": took, "width": w, "height": h, "preview": jpeg_data_url(frame),
            "source": mask_source(c.source)}


# ------------------------------------------------------------------- review

def _item_out(db: Session, r: ReviewItem, with_image: bool) -> dict:
    u = db.get(User, r.user_id)
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == r.user_id)).first()
    cam = db.get(Camera, r.camera_id) if r.camera_id else None
    s = db.get(ClassSession, r.session_id)
    out = {"id": r.id, "session_id": r.session_id, "session_title": s.title if s else None,
           "user_id": r.user_id, "student": u.display_name if u else None,
           "roll_number": (prof.roll_number if prof else None) or (u.roll_number if u else None),
           "photo_url": f"/api/files/{prof.photo_file_id}" if prof and prof.photo_file_id else None,
           "camera": cam.name if cam else None, "score": round(r.score, 3), "frames": r.frames,
           "seen_at": r.seen_at, "reason": r.reason, "status": r.status,
           "has_snapshot": bool(r.snapshot_path)}
    if with_image:
        out["snapshot"] = load_review_crop(r.snapshot_path)
    return out


@router.get("/review-queue")
def review_queue(session_id: Optional[int] = None, db: Session = Depends(get_db),
                 actor: User = Depends(require_staff)):
    stmt = (select(ReviewItem).join(StudentProfile, StudentProfile.user_id == ReviewItem.user_id,
                                    isouter=True)
            .where(ReviewItem.status == "pending"))
    if session_id is not None:
        s = db.get(ClassSession, session_id)
        if s is None:
            raise HTTPException(404, "session not found")
        assert_owns_session(actor, s)
        stmt = stmt.where(ReviewItem.session_id == session_id)
    else:
        stmt = stmt.where(student_scope_clause(db, actor))
    rows = list(db.scalars(stmt.order_by(ReviewItem.created_at.desc()).limit(200)))
    return [_item_out(db, r, with_image=True) for r in rows]


class ReviewDecisionIn(BaseModel):
    status: Optional[str] = None          # override present/late on accept


@router.post("/review-queue/{item_id}/{decision}")
def decide_review(item_id: int, decision: str, body: ReviewDecisionIn, request: Request,
                  db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    from app.session_service import record_mark, window_status

    if decision not in ("accept", "reject"):
        raise HTTPException(404, "unknown action")
    r = db.get(ReviewItem, item_id)
    if r is None or r.status != "pending":
        raise HTTPException(404, "review item not found or already decided")
    s = db.get(ClassSession, r.session_id)
    assert_owns_session(actor, s)
    result = None
    if decision == "accept":
        user = db.get(User, r.user_id)
        status = body.status if body.status in ("present", "late") else (
            window_status(s, r.seen_at, db, cfg) or "late")
        row, created = record_mark(db, s, user, CaptureMethod.CCTV.value, cfg, status=status,
                                   confidence=r.score, marked_by=actor,
                                   evidence=f"camera near-match confirmed by {actor.display_name}")
        if not created and row is not None and row.effective_status != status:
            # Closed sessions filled this student as absent: the teacher's acceptance corrects it.
            row.overridden_status, row.overridden_by_id = status, actor.id
            row.overridden_at, row.override_reason = utcnow(), "camera sighting accepted in review"
        result = status
    r.status = "approved" if decision == "accept" else "rejected"
    r.decided_by_id, r.decided_at = actor.id, utcnow()
    delete_review_crop(r.snapshot_path)
    r.snapshot_path = None
    audit(db, actor, f"review_{r.status}", target_type="review_item", target_id=r.id,
          detail={"user_id": r.user_id, "session_id": r.session_id, "marked": result},
          request=request)
    db.commit()
    return {"id": r.id, "status": r.status, "marked": result}


def purge_review_snapshots(db: Session, days: int) -> int:
    """Retention: crops older than `days` are deleted whether or not anyone decided."""
    cutoff = utcnow() - timedelta(days=days)
    n = 0
    for r in db.scalars(select(ReviewItem).where(ReviewItem.created_at < cutoff,
                                                 ReviewItem.snapshot_path.is_not(None))):
        delete_review_crop(r.snapshot_path)
        r.snapshot_path = None
        if r.status == "pending":
            r.status = "expired"
        n += 1
    db.commit()
    return n
