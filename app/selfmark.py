"""Student self-marking (QR scan, and the mobile selfie in phase 6) — the shared gate.

Order of checks is deliberate: cheap, explanatory refusals first (not approved, no active
lecture, not your class, already marked, out of attempts, too late), then location, then the
rotating code, then — for a selfie — liveness and the face match. Every refusal is logged as a
`SelfMarkAttempt`, counts toward the retry limit, and comes back with a message the student can
act on ("You are outside campus", "Face did not match, try again in better light").
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import settings_service
from app.auth import is_student
from app.geo import GeoResult, check_location
from app.models import (
    AttendanceRecordRow,
    ClassSession,
    Room,
    SelfMarkAttempt,
    SessionState,
    StudentProfile,
    User,
)
from app.session_code import verify as verify_code
from app.session_service import approved_roster, window_status


class SelfMarkError(Exception):
    """A refusal to show the student. `counts` = whether it uses up one of their attempts."""

    def __init__(self, code: int, message: str, *, counts: bool = True, kind: str = "refused"):
        super().__init__(message)
        self.code = code
        self.message = message
        self.counts = counts
        self.kind = kind


def failed_attempts(db: Session, session_id: int, user_id: int) -> int:
    return db.scalar(select(func.count()).select_from(SelfMarkAttempt).where(
        SelfMarkAttempt.session_id == session_id, SelfMarkAttempt.user_id == user_id,
        SelfMarkAttempt.success.is_(False))) or 0


def log_attempt(db: Session, session_id: int, user_id: int, method: str, success: bool,
                reason: str, *, ip: Optional[str] = None, distance_m: Optional[float] = None,
                confidence: Optional[float] = None) -> None:
    db.add(SelfMarkAttempt(session_id=session_id, user_id=user_id, method=method,
                           success=success, reason=reason[:300], ip=ip, distance_m=distance_m,
                           confidence=confidence))
    db.commit()


def precheck(db: Session, session: Optional[ClassSession], user: User, cfg) -> str:
    """Everything that does not depend on the evidence. Returns the status a mark would get."""
    if not is_student(user):
        raise SelfMarkError(403, "Only students mark their own attendance.", counts=False)
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    if prof is None or prof.status != "approved":
        raise SelfMarkError(403, "Your account is awaiting approval by your teacher, so you "
                                 "cannot mark attendance yet.", counts=False, kind="not_approved")
    if session is None or session.deleted_at is not None:
        raise SelfMarkError(404, "That lecture was not found.", counts=False)
    if session.state != SessionState.ACTIVE.value:
        msg = ("This lecture has ended." if session.state == SessionState.CLOSED.value
               else "Attendance for this lecture has not started yet.")
        raise SelfMarkError(409, msg, counts=False, kind="not_active")
    if user.id not in approved_roster(db, session):
        raise SelfMarkError(403, "You are not enrolled in this class.", counts=False)
    existing = db.scalars(select(AttendanceRecordRow).where(
        AttendanceRecordRow.session_id == session.id,
        AttendanceRecordRow.user_id == user.id)).first()
    if existing is not None:
        raise SelfMarkError(409, f"You are already marked {existing.effective_status.replace('_', ' ')} "
                                 f"for this lecture.", counts=False, kind="already_marked")
    limit = int(settings_service.get(db, cfg, "selfmark_retry_limit"))
    if failed_attempts(db, session.id, user.id) >= limit:
        raise SelfMarkError(429, f"You have used all {limit} attempts for this lecture. Ask "
                                 f"your teacher to mark you.", counts=False, kind="no_attempts")
    from app.models import utcnow

    status = window_status(session, utcnow(), db, cfg)
    if status is None:
        s = settings_service.all_settings(db, cfg)
        raise SelfMarkError(409, f"The attendance window has closed (marking is allowed up to "
                                 f"{s['late_window_min']} minutes after the start).",
                            counts=False, kind="too_late")
    return status


def check_geofence(db: Session, session: ClassSession, cfg, lat: Optional[float],
                   lng: Optional[float], accuracy: Optional[float]) -> GeoResult:
    s = settings_service.all_settings(db, cfg)
    room = db.scalars(select(Room).where(Room.name == session.room)).first()
    use_room = room is not None and room.latitude is not None and room.longitude is not None
    return check_location(
        enabled=bool(s["geofence_enabled"]),
        center_lat=room.latitude if use_room else s["campus_lat"],
        center_lng=room.longitude if use_room else s["campus_lng"],
        radius_m=float(room.radius_m or s["geofence_radius_m"]) if use_room
        else float(s["geofence_radius_m"]),
        max_accuracy_m=float(s["geo_max_accuracy_m"]),
        lat=lat, lng=lng, accuracy_m=accuracy)


def check_code(db: Session, session: ClassSession, cfg, code: Optional[str],
               required: bool) -> None:
    if not required and not code:
        return
    rotation = int(settings_service.get(db, cfg, "session_code_rotation_s"))
    if not code:
        raise SelfMarkError(422, "Enter the code shown on the classroom screen.", kind="code")
    if not verify_code(session.code_secret, code, rotation):
        raise SelfMarkError(422, "That session code is wrong or has expired. Use the code "
                                 "currently on the screen.", kind="code")


def remaining_attempts(db: Session, session: ClassSession, user: User, cfg) -> int:
    limit = int(settings_service.get(db, cfg, "selfmark_retry_limit"))
    return max(0, limit - failed_attempts(db, session.id, user.id))
