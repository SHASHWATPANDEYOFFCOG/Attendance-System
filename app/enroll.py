"""Enrollment — the ceiling on everything the system can do afterwards.

Implements the upstream `scripts/enroll.py` behaviour as a service: detect (exactly one face),
align, quality-gate with a *named* reason, embed, average, re-normalise to one template per
person, refuse duplicates, store encrypted, rebuild the index.

Two failures here are unrecoverable later, so both are hard errors rather than warnings:

* **Two people sharing one template** silently destroys attendance for both — one is marked
  present when the other walks in, and neither can be told apart afterwards. Hence the
  duplicate check and HTTP 409.
* **A low-quality template** cannot be fixed by tuning a threshold. Samples below
  `quality.min_score` are dropped with a reason the person can act on, not a generic failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import encrypt_embedding
from app.gallery_service import get_gallery, rebuild_index
from app.models import Enrollment, User
from app.pipeline_service import PipelineService
from occlubio.utils import get_logger, l2_normalize

log = get_logger("app.enroll")

# Yaw proxy: how far the nose sits from the midpoint of the eyes, in inter-eye widths.
_MAX_YAW_RATIO = 0.38


class EnrollmentError(Exception):
    """Raised for conditions the caller should surface verbatim to the user."""

    def __init__(self, message: str, code: int = 400, extra: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.extra = extra or {}


@dataclass
class SampleResult:
    """Per-image outcome, surfaced in the enrollment UI so people can fix a bad photo."""

    filename: str
    accepted: bool
    quality: float = 0.0
    reason: str = ""
    occlusion: str = "clear"

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "accepted": self.accepted,
            "quality": round(self.quality, 4),
            "reason": self.reason,
            "occlusion": self.occlusion,
        }


@dataclass
class EnrollmentOutcome:
    enrollment_id: int
    n_accepted: int
    mean_quality: float
    min_quality: float
    samples: List[SampleResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "enrollment_id": self.enrollment_id,
            "n_accepted": self.n_accepted,
            "mean_quality": round(self.mean_quality, 4),
            "min_quality": round(self.min_quality, 4),
            "samples": [s.as_dict() for s in self.samples],
        }


def _yaw_ratio(kps: np.ndarray) -> float:
    """|offset of the nose from the eye midpoint| / inter-eye distance."""
    left_eye, right_eye, nose = kps[0], kps[1], kps[2]
    eye_mid = (left_eye + right_eye) / 2.0
    eye_dist = float(np.linalg.norm(right_eye - left_eye))
    if eye_dist < 1e-6:
        return 1.0
    return float(abs(nose[0] - eye_mid[0]) / eye_dist)


def _decode(data: bytes) -> Optional[np.ndarray]:
    buf = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def assess_sample(
    pipeline: PipelineService, cfg, data: bytes, filename: str
) -> Tuple[SampleResult, Optional[np.ndarray]]:
    """Run one candidate image through detect -> align -> quality, returning a named verdict."""
    img = _decode(data)
    if img is None:
        return SampleResult(filename, False, reason="not a readable image file"), None

    faces = pipeline.detect(img)
    if not faces:
        return SampleResult(filename, False,
                            reason="no face found — move closer and face the camera"), None
    if len(faces) > 1:
        return SampleResult(filename, False,
                            reason=f"{len(faces)} faces in frame — enroll one person alone"), None

    face = faces[0]
    w, h = face.wh
    longest = float(max(w, h))
    if longest < float(cfg.detection.min_face) * 2:
        return SampleResult(filename, False,
                            reason=f"face too small ({longest:.0f}px) — move closer"), None

    yaw = _yaw_ratio(face.kps)
    if yaw > _MAX_YAW_RATIO:
        return SampleResult(filename, False,
                            reason="face too far off-angle — look towards the camera"), None

    chip = pipeline.align(img, face)
    passed, quality, occ, _spoof = pipeline.assess(chip, face.det_score)
    occ_type = str(occ.get("type", "clear"))

    if not passed:
        gray = cv2.cvtColor(chip, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        bright = float(gray.mean())
        if sharp < float(cfg.quality.blur_min):
            why = f"too blurry (sharpness {sharp:.0f} < {cfg.quality.blur_min:.0f}) — hold still"
        elif bright < float(cfg.quality.brightness_min):
            why = f"too dark (brightness {bright:.0f}) — find better light"
        elif bright > float(cfg.quality.brightness_max):
            why = f"over-exposed (brightness {bright:.0f}) — avoid backlight"
        else:
            why = (f"quality {quality:.2f} below the {cfg.quality.min_score:.2f} floor"
                   + (f" (occlusion: {occ_type})" if occ_type != "clear" else ""))
        return SampleResult(filename, False, quality=quality, reason=why, occlusion=occ_type), None

    return SampleResult(filename, True, quality=quality, reason="accepted",
                        occlusion=occ_type), pipeline.embed(img, face, chip)


def enroll_user(
    db: Session,
    user: User,
    images: Sequence[Tuple[str, bytes]],
    cfg,
    pipeline: PipelineService,
    actor_is_staff: bool = False,
    status: str = "approved",
) -> EnrollmentOutcome:
    """Build and store one averaged face template for `user`.

    Args:
        images: (filename, bytes) pairs — uploads and/or webcam captures.
        actor_is_staff: unused for policy today; kept so an admin-only override path has an
            obvious home rather than being bolted on later.

    Raises:
        EnrollmentError: consent missing, too few usable samples, or a duplicate template (409).
    """
    if bool(cfg.attendance.require_consent) and not user.consent_given:
        raise EnrollmentError(
            "Biometric consent has not been recorded for this account. Enrollment is refused.",
            code=403,
        )

    min_needed = int(cfg.gallery.min_enroll_images)
    results: List[SampleResult] = []
    embeddings: List[np.ndarray] = []

    for filename, data in images:
        res, emb = assess_sample(pipeline, cfg, data, filename)
        results.append(res)
        if emb is not None:
            embeddings.append(emb)

    if len(embeddings) < min_needed:
        raise EnrollmentError(
            f"Only {len(embeddings)} of {len(images)} images passed the quality gate; "
            f"{min_needed} are required. Vary pose and lighting and try again.",
            code=422,
            extra={"samples": [r.as_dict() for r in results]},
        )

    # One template per person: mean of accepted embeddings, re-normalised so the stored vector
    # is unit-length (averaging unit vectors does not preserve the norm).
    template = l2_normalize(np.mean(np.stack(embeddings), axis=0))

    # Duplicate check BEFORE insert, ignoring this user's own existing templates so that
    # re-enrolling yourself is allowed.
    gallery = get_gallery(db, cfg)
    dup_thresh = float(cfg.gallery.dup_threshold)
    for label, score, _meta in gallery.search(template, top_k=5):
        if str(label) == str(user.id):
            continue
        if score >= dup_thresh:
            other = db.get(User, int(label)) if str(label).isdigit() else None
            who = f"{other.display_name} ({other.username})" if other else f"user {label}"
            raise EnrollmentError(
                f"This face already matches an enrolled identity: {who} "
                f"(similarity {score:.3f} >= {dup_thresh:.2f}). Enrollment refused — two people "
                f"sharing one template would break attendance for both.",
                code=409,
                extra={"conflict_user_id": other.id if other else None,
                       "similarity": round(float(score), 4)},
            )

    qualities = [r.quality for r in results if r.accepted]
    if status == "approved":
        for old in db.scalars(select(Enrollment).where(Enrollment.user_id == user.id,
                                                       Enrollment.is_active.is_(True))):
            old.is_active = False           # supersede, keep the row for the audit trail
    else:
        # A self-captured template waits for a teacher; the live one keeps working meanwhile.
        for old in db.scalars(select(Enrollment).where(Enrollment.user_id == user.id,
                                                       Enrollment.status == "pending")):
            db.delete(old)

    row = Enrollment(
        user_id=user.id,
        embedding_encrypted=encrypt_embedding(template),
        dim=int(cfg.recognition.embedding_dim),
        n_images=len(embeddings),
        mean_quality=float(np.mean(qualities)),
        min_quality=float(np.min(qualities)),
        is_active=True,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    rebuild_index(db, cfg)                  # DB is truth; the index follows it immediately
    log.info("enrolled user=%s n=%d mean_q=%.3f", user.username, len(embeddings), row.mean_quality)

    return EnrollmentOutcome(
        enrollment_id=row.id,
        n_accepted=len(embeddings),
        mean_quality=row.mean_quality,
        min_quality=row.min_quality,
        samples=results,
    )
