"""Face enrollment (student self-service, teacher-approved) and mobile selfie attendance.

Enrollment:
  1. consent  — explicit, recorded with a text version; withdrawing it erases all face data.
  2. guided capture — five poses in a random server-issued order (front first). Each frame is
     checked as it is taken (one face, large enough, sharp, lit, eyes visible) for live guidance.
  3. submit — the server re-checks every frame, verifies the pose sequence (liveness), builds
     one averaged template, refuses a face that already belongs to someone else (and tells the
     class teacher), and stores the template encrypted as PENDING with encrypted face chips for
     the teacher to look at. Raw photos are never stored.
  4. teacher approves (template goes live, chips are wiped) or rejects (both are wiped).

Selfie attendance re-runs the same liveness on three frames and matches the front frame 1:1
against the student's own approved template only.
"""
from __future__ import annotations

import base64
import json
from typing import List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import settings_service
from app.audit import audit
from app.auth import current_user, is_student, require_staff
from app.crypto import decrypt_bytes, decrypt_embedding, encrypt_bytes, encrypt_embedding
from app.db import get_db
from app.gallery_service import get_gallery, match_among, rebuild_index, user_templates
from app.liveness import (
    POSE_TEXT,
    LivenessError,
    Pose,
    consume,
    decode,
    issue,
    pose_of,
    verify_sequence,
)
from app.models import (
    CaptureMethod,
    ClassSession,
    Enrollment,
    FaceReenrollRequest,
    ReviewStatus,
    StudentProfile,
    User,
    utcnow,
)
from app.notify import notify
from app.ratelimit import client_ip, enforce
from app.routes.academic import section_label
from app.runtime import cfg
from app.scope import assert_can_manage_student, responsible_staff, student_scope_clause
from app.selfmark import SelfMarkError, check_code, check_geofence, log_attempt, precheck, remaining_attempts
from app.session_service import record_mark
from app.uploads import MB, read_limited
from occlubio.utils import get_logger, l2_normalize

log = get_logger("app.face")
router = APIRouter(prefix="/api", tags=["face"])

CONSENT_VERSION = "v2-portal"
MAX_FRAME = 4 * MB


def _pipeline():
    from app.pipeline_service import get_pipeline

    try:
        return get_pipeline(cfg)
    except Exception as exc:                          # model not downloaded, etc.
        log.error("face pipeline unavailable: %s", exc)
        raise HTTPException(503, "Face recognition is not available on the server right now. "
                                 "Use the classroom code instead.")


# --------------------------------------------------------------- frame check

class FrameResult:
    def __init__(self, ok: bool, message: str, *, pose: Optional[Pose] = None, chip=None,
                 face=None, img=None, quality: float = 0.0, live: bool = True):
        self.ok, self.message, self.pose, self.chip = ok, message, pose, chip
        self.face, self.img, self.quality, self.live = face, img, quality, live


def analyze(pipeline, data: bytes) -> FrameResult:
    """Detect -> size -> align -> quality, with a reason a student can act on."""
    img = decode(data)
    if img is None:
        return FrameResult(False, "That image could not be read. Try again.")
    faces = pipeline.detect(img)
    if not faces:
        return FrameResult(False, "No face found — centre your face in the outline.")
    if len(faces) > 1:
        return FrameResult(False, f"{len(faces)} faces in view — make sure only you are in frame.")
    face = faces[0]
    w, h = face.wh
    if float(max(w, h)) < float(cfg.detection.min_face) * 2:
        return FrameResult(False, "Move closer — your face is too small.")
    pose = pose_of(face.kps)
    chip = pipeline.align(img, face)
    passed, quality, _occ, spoof = pipeline.assess(chip, face.det_score)
    live = bool(spoof.get("live", True)) if pipeline.antispoof_available else True
    if not passed:
        gray = cv2.cvtColor(chip, cv2.COLOR_BGR2GRAY)
        sharp, bright = float(cv2.Laplacian(gray, cv2.CV_64F).var()), float(gray.mean())
        if sharp < float(cfg.quality.blur_min):
            msg = "Too blurry — hold the phone still."
        elif bright < float(cfg.quality.brightness_min):
            msg = "Too dark — face a light or a window."
        elif bright > float(cfg.quality.brightness_max):
            msg = "Too bright — avoid strong light behind or on you."
        else:
            msg = "Your eyes or face are not clearly visible — remove sunglasses or masks."
        return FrameResult(False, msg, pose=pose, quality=quality)
    return FrameResult(True, "Looks good.", pose=pose, chip=chip, face=face, img=img,
                       quality=quality, live=live)


def _student(db: Session, user: User) -> StudentProfile:
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    if not is_student(user) or prof is None:
        raise HTTPException(403, "Face enrollment is for students.")
    return prof


def _active(db: Session, user_id: int, status: str) -> Optional[Enrollment]:
    return db.scalars(select(Enrollment).where(Enrollment.user_id == user_id,
                                               Enrollment.is_active.is_(True),
                                               Enrollment.status == status)
                      .order_by(Enrollment.created_at.desc())).first()


# -------------------------------------------------------------------- status

@router.get("/me/face")
def face_status(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == actor.id)).first()
    approved = _active(db, actor.id, ReviewStatus.APPROVED.value)
    pending = _active(db, actor.id, ReviewStatus.PENDING.value)
    last_rejected = db.scalars(select(Enrollment).where(
        Enrollment.user_id == actor.id, Enrollment.status == ReviewStatus.REJECTED.value)
        .order_by(Enrollment.created_at.desc())).first()
    req = db.scalars(select(FaceReenrollRequest).where(FaceReenrollRequest.user_id == actor.id)
                     .order_by(FaceReenrollRequest.created_at.desc())).first()
    reenroll_ok = req is not None and req.status == ReviewStatus.APPROVED.value
    can_enroll = (prof is not None and prof.status == "approved" and actor.consent_given
                  and pending is None and (approved is None or reenroll_ok))
    return {
        "consent_given": actor.consent_given, "consent_at": actor.consent_at,
        "consent_version": CONSENT_VERSION,
        "account_approved": prof is not None and prof.status == "approved",
        "enrollment": ("approved" if approved else "pending" if pending else
                       "rejected" if last_rejected else "none"),
        "enrolled_at": approved.created_at if approved else None,
        "rejection_note": last_rejected.review_note if last_rejected and not approved and not pending else None,
        "reenroll_request": {"status": req.status, "reason": req.reason, "remark": req.remark,
                             "created_at": req.created_at} if req else None,
        "can_enroll": can_enroll,
        "antispoof_model": _pipeline_flag(),
    }


def _pipeline_flag() -> bool:
    try:
        from app.pipeline_service import get_pipeline

        return bool(get_pipeline(cfg).antispoof_available)
    except Exception:
        return False


class ConsentIn(BaseModel):
    consent: bool
    version: str = CONSENT_VERSION


@router.post("/me/face/consent")
def set_face_consent(body: ConsentIn, request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(current_user)):
    """Give consent, or withdraw it — which permanently erases every face template and crop."""
    from app import attendance_service as svc

    if body.consent:
        actor.consent_given, actor.consent_at = True, utcnow()
        actor.consent_text_version = body.version
        audit(db, actor, "consent_changed", target_type="user", target_id=actor.id,
              detail={"consent_given": True, "version": body.version}, request=request)
        db.commit()
        return face_status(db, actor)
    result = svc.erase_biometrics(db, actor, cfg, actor)
    for e in db.scalars(select(Enrollment).where(Enrollment.user_id == actor.id)):
        db.delete(e)
    actor.consent_text_version = None
    audit(db, actor, "consent_withdrawn", target_type="user", target_id=actor.id,
          detail=result, request=request)
    db.commit()
    rebuild_index(db, cfg)
    return face_status(db, actor)


# ----------------------------------------------------------------- capture

@router.post("/me/face/check")
async def check_frame(request: Request, frame: UploadFile = File(...),
                      expect: Optional[str] = Form(None), front_pitch: Optional[float] = Form(None),
                      db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """Live guidance while capturing: is this frame usable, and is the pose right?"""
    enforce(request, "face", key=str(actor.id))
    data = await read_limited(frame, MAX_FRAME)
    res = analyze(_pipeline(), data)
    out = {"ok": res.ok, "message": res.message,
           "yaw": round(res.pose.yaw, 3) if res.pose else None,
           "pitch": round(res.pose.pitch, 3) if res.pose else None}
    if res.ok and expect in POSE_TEXT:
        from app.liveness import pose_matches

        front = Pose(0.0, front_pitch) if front_pitch is not None else None
        problem = pose_matches(expect, res.pose, front)
        if problem:
            out.update(ok=False, message=problem)
    return out


class ChallengeIn(BaseModel):
    purpose: str = Field(pattern="^(enroll|attendance)$")
    session_id: Optional[int] = None


@router.post("/me/face/challenge")
def new_challenge(body: ChallengeIn, request: Request, db: Session = Depends(get_db),
                  actor: User = Depends(current_user)):
    enforce(request, "face", key=str(actor.id))
    if body.purpose == "attendance" and body.session_id is None:
        raise HTTPException(422, "session_id is required for attendance.")
    ch = issue(db, actor.id, body.purpose, body.session_id)
    steps = json.loads(ch.steps)
    return {"id": ch.id, "steps": steps, "instructions": [POSE_TEXT[s] for s in steps],
            "expires_at": ch.expires_at}


async def _read_frames(files: List[UploadFile]) -> List[bytes]:
    return [await read_limited(f, MAX_FRAME) for f in files]


def _template_from(results: List[FrameResult], pipeline) -> np.ndarray:
    embs = [pipeline.embed(r.img, r.face, r.chip) for r in results]
    return l2_normalize(np.mean(np.stack(embs), axis=0))


def _duplicate_of(db: Session, template: np.ndarray, user_id: int) -> Optional[tuple]:
    thresh = float(cfg.gallery.dup_threshold)
    for label, score, _m in get_gallery(db, cfg).search(template, top_k=5):
        if str(label) != str(user_id) and score >= thresh:
            return int(label), float(score)
    # Pending templates are not in the live gallery, but two people must not both be waiting
    # with the same face either.
    dim = int(cfg.recognition.embedding_dim)
    for e in db.scalars(select(Enrollment).where(Enrollment.status == ReviewStatus.PENDING.value,
                                                 Enrollment.is_active.is_(True),
                                                 Enrollment.user_id != user_id)):
        try:
            score = float(decrypt_embedding(e.embedding_encrypted, dim) @ template)
        except (RuntimeError, ValueError):
            continue
        if score >= thresh:
            return e.user_id, score
    return None


@router.post("/me/face/enroll", status_code=201)
async def enroll_face(request: Request, challenge_id: int = Form(...),
                      images: List[UploadFile] = File(...), db: Session = Depends(get_db),
                      actor: User = Depends(current_user)):
    enforce(request, "face", key=str(actor.id))
    prof = _student(db, actor)
    if prof.status != "approved":
        raise HTTPException(403, "Your account must be approved before you enroll your face.")
    if not actor.consent_given:
        raise HTTPException(403, "Give consent for face data first.")
    status = face_status(db, actor)
    if not status["can_enroll"]:
        msg = ("Your enrollment is already waiting for your teacher." if status["enrollment"] == "pending"
               else "You are already enrolled. Request re-enrollment first.")
        raise HTTPException(409, msg)

    try:
        steps = consume(db, challenge_id, actor.id, "enroll")
    except LivenessError as exc:
        raise HTTPException(422, detail={"message": exc.message, "kind": "liveness"})
    datas = await _read_frames(images)
    pipeline = _pipeline()
    results = [analyze(pipeline, d) for d in datas]
    bad = [(i, r) for i, r in enumerate(results) if not r.ok]
    if bad:
        i, r = bad[0]
        raise HTTPException(422, detail={"message": f"Photo {i + 1}: {r.message}",
                                         "kind": "quality", "step": i})
    try:
        verify_sequence(steps, [r.pose for r in results])
    except LivenessError as exc:
        raise HTTPException(422, detail={"message": exc.message, "kind": "liveness", "step": exc.step})
    if not all(r.live for r in results):
        raise HTTPException(422, detail={"message": "The anti-spoofing check did not accept these "
                                                    "photos. Use your own live camera, not a photo "
                                                    "or a screen.", "kind": "spoof"})

    template = _template_from(results, pipeline)
    dup = _duplicate_of(db, template, actor.id)
    if dup is not None:
        other_id, score = dup
        notify(db, responsible_staff(db, prof), "face_duplicate",
               "Possible duplicate face enrollment",
               f"{actor.display_name} ({prof.roll_number}) tried to enroll a face that matches "
               f"another student's (similarity {score:.2f}). Check both accounts.",
               link=f"/staff/students/{actor.id}", email=True)
        audit(db, actor, "face_duplicate_refused", target_type="user", target_id=actor.id,
              detail={"matches_user": other_id, "similarity": round(score, 3)}, request=request)
        db.commit()
        raise HTTPException(409, detail={
            "message": "This face already matches another student's account, so it cannot be "
                       "enrolled. Your teacher has been notified to sort it out.",
            "kind": "duplicate"})

    chips = []
    for r in results:
        ok, buf = cv2.imencode(".jpg", r.chip, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            chips.append(base64.b64encode(buf.tobytes()).decode())
    for old in db.scalars(select(Enrollment).where(Enrollment.user_id == actor.id,
                                                   Enrollment.status == ReviewStatus.PENDING.value)):
        db.delete(old)
    qualities = [r.quality for r in results]
    row = Enrollment(user_id=actor.id, embedding_encrypted=encrypt_embedding(template),
                     dim=int(cfg.recognition.embedding_dim), n_images=len(results),
                     mean_quality=float(np.mean(qualities)), min_quality=float(np.min(qualities)),
                     is_active=True, status=ReviewStatus.PENDING.value, liveness_passed=True,
                     samples_encrypted=encrypt_bytes(json.dumps(chips).encode()))
    db.add(row)
    req = db.scalars(select(FaceReenrollRequest).where(
        FaceReenrollRequest.user_id == actor.id,
        FaceReenrollRequest.status == ReviewStatus.APPROVED.value)).first()
    if req is not None:
        req.status = "completed"                       # one approval, one re-enrollment
    db.flush()
    notify(db, responsible_staff(db, prof), "face_enrollment_pending", "Face enrollment to review",
           f"{actor.display_name} ({prof.roll_number}) enrolled their face. Check the photos "
           f"and approve it.", link="/staff/approvals?tab=faces", email=False)
    audit(db, actor, "face_enrolled", target_type="enrollment", target_id=row.id,
          detail={"liveness": True, "mean_quality": round(row.mean_quality, 3)}, request=request)
    db.commit()
    return {"id": row.id, "status": row.status,
            "message": "Face enrolled. Your teacher will review it shortly; you will be notified."}


class ReenrollIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/me/face/reenroll-request", status_code=201)
def request_reenroll(body: ReenrollIn, request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(current_user)):
    prof = _student(db, actor)
    if _active(db, actor.id, ReviewStatus.APPROVED.value) is None:
        raise HTTPException(409, "You have no approved face yet — enroll directly.")
    if db.scalars(select(FaceReenrollRequest).where(
            FaceReenrollRequest.user_id == actor.id,
            FaceReenrollRequest.status.in_([ReviewStatus.PENDING.value, ReviewStatus.APPROVED.value]))).first():
        raise HTTPException(409, "You already have a re-enrollment request open.")
    req = FaceReenrollRequest(user_id=actor.id, reason=body.reason.strip())
    db.add(req)
    db.flush()
    notify(db, responsible_staff(db, prof), "reenroll_request", "Face re-enrollment request",
           f"{actor.display_name} ({prof.roll_number}) asked to re-enroll: {req.reason}",
           link="/staff/approvals?tab=faces")
    audit(db, actor, "reenroll_requested", target_type="face_reenroll_request", target_id=req.id,
          request=request)
    db.commit()
    return {"id": req.id, "status": req.status}


# ------------------------------------------------------------------- review

@router.get("/face-enrollments")
def list_enrollments(db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    rows = db.execute(select(Enrollment, User, StudentProfile)
                      .join(User, User.id == Enrollment.user_id)
                      .join(StudentProfile, StudentProfile.user_id == User.id)
                      .where(Enrollment.status == ReviewStatus.PENDING.value,
                             Enrollment.is_active.is_(True), student_scope_clause(db, actor))
                      .order_by(Enrollment.created_at)).all()
    return [{"id": e.id, "student_id": u.id, "student": u.display_name,
             "roll_number": p.roll_number, "section": section_label(p.section) if p.section else None,
             "photo_url": f"/api/files/{p.photo_file_id}" if p.photo_file_id else None,
             "liveness_passed": e.liveness_passed, "mean_quality": round(e.mean_quality, 3),
             "created_at": e.created_at, "reenrollment": _active(db, u.id, "approved") is not None}
            for e, u, p in rows]


@router.get("/face-enrollments/{enrollment_id}/samples")
def enrollment_samples(enrollment_id: int, db: Session = Depends(get_db),
                       actor: User = Depends(require_staff)):
    """The aligned face chips, decrypted only for the reviewing teacher, never cached."""
    e = db.get(Enrollment, enrollment_id)
    if e is None or e.status != ReviewStatus.PENDING.value:
        raise HTTPException(404, "enrollment not found")
    assert_can_manage_student(db, actor, e.user_id)
    chips = json.loads(decrypt_bytes(e.samples_encrypted).decode()) if e.samples_encrypted else []
    audit(db, actor, "face_samples_viewed", target_type="enrollment", target_id=e.id)
    db.commit()
    return {"images": [f"data:image/jpeg;base64,{c}" for c in chips]}


class DecideIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/face-enrollments/{enrollment_id}/{decision}")
def decide_enrollment(enrollment_id: int, decision: str, body: DecideIn, request: Request,
                      db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "unknown action")
    e = db.get(Enrollment, enrollment_id)
    if e is None or e.status != ReviewStatus.PENDING.value:
        raise HTTPException(404, "enrollment not found or already decided")
    assert_can_manage_student(db, actor, e.user_id)
    note = (body.reason or "").strip() or None
    if decision == "reject" and not note:
        raise HTTPException(422, detail={"field": "reason", "message": "Tell the student why."})
    e.samples_encrypted = None                  # photos are gone either way
    e.reviewed_by_id, e.reviewed_at, e.review_note = actor.id, utcnow(), note
    if decision == "approve":
        for old in db.scalars(select(Enrollment).where(
                Enrollment.user_id == e.user_id, Enrollment.id != e.id,
                Enrollment.status == ReviewStatus.APPROVED.value, Enrollment.is_active.is_(True))):
            old.is_active = False
        e.status = ReviewStatus.APPROVED.value
        msg = "Your face enrollment was approved. You can now mark attendance with a face check."
    else:
        e.status = ReviewStatus.REJECTED.value
        e.is_active = False
        msg = f"Your face enrollment was not approved: {note}. You can enroll again."
    notify(db, [e.user_id], f"face_{e.status}", f"Face enrollment {e.status}", msg,
           link="/student/face", email=True)
    audit(db, actor, f"face_enrollment_{e.status}", target_type="enrollment", target_id=e.id,
          reason=note, request=request)
    db.commit()
    rebuild_index(db, cfg)
    return {"id": e.id, "status": e.status}


@router.get("/reenroll-requests")
def list_reenroll(db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    rows = db.execute(select(FaceReenrollRequest, User, StudentProfile)
                      .join(User, User.id == FaceReenrollRequest.user_id)
                      .join(StudentProfile, StudentProfile.user_id == User.id)
                      .where(FaceReenrollRequest.status == ReviewStatus.PENDING.value,
                             student_scope_clause(db, actor))
                      .order_by(FaceReenrollRequest.created_at)).all()
    return [{"id": r.id, "student_id": u.id, "student": u.display_name,
             "roll_number": p.roll_number, "reason": r.reason, "created_at": r.created_at}
            for r, u, p in rows]


@router.post("/reenroll-requests/{request_id}/{decision}")
def decide_reenroll(request_id: int, decision: str, body: DecideIn, request: Request,
                    db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "unknown action")
    r = db.get(FaceReenrollRequest, request_id)
    if r is None or r.status != ReviewStatus.PENDING.value:
        raise HTTPException(404, "request not found or already decided")
    assert_can_manage_student(db, actor, r.user_id)
    note = (body.reason or "").strip() or None
    if decision == "reject" and not note:
        raise HTTPException(422, detail={"field": "reason", "message": "Tell the student why."})
    r.status = ReviewStatus.APPROVED.value if decision == "approve" else ReviewStatus.REJECTED.value
    r.decided_by_id, r.decided_at, r.remark = actor.id, utcnow(), note
    notify(db, [r.user_id], f"reenroll_{r.status}", f"Re-enrollment {r.status}",
           ("You can now re-enroll your face from the Face page." if decision == "approve"
            else f"Your re-enrollment request was not approved: {note}"),
           link="/student/face", email=True)
    audit(db, actor, f"reenroll_{r.status}", target_type="face_reenroll_request",
          target_id=r.id, reason=note, request=request)
    db.commit()
    return {"id": r.id, "status": r.status}


# ------------------------------------------------------------ selfie marking

@router.post("/attendance/sessions/{session_id}/self-mark")
async def selfie_mark(session_id: int, request: Request, challenge_id: int = Form(...),
                      frames: List[UploadFile] = File(...),
                      lat: Optional[float] = Form(None), lng: Optional[float] = Form(None),
                      accuracy: Optional[float] = Form(None), code: Optional[str] = Form(None),
                      db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """Mark yourself with a live face check. Every condition is verified here, not in the browser."""
    enforce(request, "attendance", key=str(actor.id))
    s = db.get(ClassSession, session_id)
    ip = client_ip(request)
    confidence = None
    distance = None
    try:
        status = precheck(db, s, actor, cfg)
        geo = check_geofence(db, s, cfg, lat, lng, accuracy)
        distance = geo.distance_m
        if not geo.ok:
            raise SelfMarkError(403, geo.reason, kind="geofence")
        check_code(db, s, cfg, code,
                   required=bool(settings_service.get(db, cfg, "require_session_code")))
        templates = user_templates(db, cfg, [actor.id])
        if actor.id not in templates:
            raise SelfMarkError(409, "Your face is not enrolled and approved yet. Use the "
                                     "classroom code instead.", counts=False, kind="no_face")
        try:
            steps = consume(db, challenge_id, actor.id, "attendance", session_id=s.id)
        except LivenessError as exc:
            raise SelfMarkError(422, exc.message, kind="liveness")
        datas = await _read_frames(frames)
        pipeline = _pipeline()
        results = [analyze(pipeline, d) for d in datas]
        bad = next((r for r in results if not r.ok), None)
        if bad is not None:
            raise SelfMarkError(422, f"{bad.message} Try again in better light.", kind="quality")
        try:
            verify_sequence(steps, [r.pose for r in results])
        except LivenessError as exc:
            raise SelfMarkError(422, f"Liveness check failed: {exc.message}", kind="liveness")
        if not all(r.live for r in results):
            raise SelfMarkError(422, "Anti-spoofing rejected the capture. Use your own live "
                                     "camera.", kind="spoof")
        front = results[0]
        emb = pipeline.embed(front.img, front.face, front.chip)
        _uid, confidence = match_among(emb, templates)
        if confidence < float(settings_service.get(db, cfg, "face_match_threshold")):
            raise SelfMarkError(403, "Face did not match your enrolled face. Try again in better "
                                     "light, facing the camera.", kind="mismatch")
    except SelfMarkError as exc:
        if s is not None and exc.counts:
            log_attempt(db, s.id, actor.id, CaptureMethod.MOBILE.value, False, exc.message,
                        ip=ip, distance_m=distance, confidence=confidence)
        left = remaining_attempts(db, s, actor, cfg) if s is not None else None
        raise HTTPException(exc.code, detail={"message": exc.message, "kind": exc.kind,
                                              "attempts_left": left})
    row, created = record_mark(db, s, actor, CaptureMethod.MOBILE.value, cfg, status=status,
                               confidence=confidence,
                               evidence=f"selfie, liveness passed, match {confidence:.3f}"
                                        + (f", {distance:.0f} m" if distance is not None else ""))
    if not created:
        raise HTTPException(409, detail={"message": "You are already marked for this lecture.",
                                         "kind": "already_marked"})
    log_attempt(db, s.id, actor.id, CaptureMethod.MOBILE.value, True, f"marked {status}", ip=ip,
                distance_m=distance, confidence=confidence)
    return {"status": status, "session_id": s.id, "method": "mobile",
            "confidence": round(confidence, 3), "message": f"Marked {status}. Face matched."}
