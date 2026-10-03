"""FastAPI application: auth, enrollment, cameras, sessions, live SSE, reports, privacy.

Authorization is applied **in the query**, not in the response formatting. `GET /api/dashboard`
builds a different payload per role; a student's token cannot produce another student's rows at
all, rather than producing them and hiding them. There is no "ship everything and filter in CSS"
path anywhere in this file.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import (
    FileResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy import false, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import analytics_service as analytics
from app import attendance_service as svc
from app import marking_service as marking
from app import reports_service as reports
from app.auth import (
    assert_can_mark_session,
    assert_can_read_user,
    assert_in_department,
    assert_owns_session,
    create_token,
    current_user,
    decode_token,
    department_scope,
    is_admin,
    is_parent,
    is_staff,
    is_super_admin,
    readable_user_ids,
    require_admin,
    require_staff,
)
from app.bus import bus, emit
from app.clock import local_today, tz_of
from app.crypto import hash_password, verify_password
from app.db import get_db, init_db
from app.enroll import EnrollmentError, enroll_user
from app.gallery_service import get_gallery, rebuild_index
from app.models import (
    AttendanceRecordRow,
    AuditLog,
    Camera,
    CameraStatus,
    ClassSession,
    CorrectionRequest,
    Enrollment,
    FacultyAssignment,
    Role,
    RosterEntry,
    Sighting,
    Subject,
    TimetableSlot,
    UnknownSighting,
    User,
    utcnow,
)
from app.pipeline_service import get_pipeline
from app.rules import Status
from app.schemas import (
    AssignUnknownIn,
    CameraIn,
    CameraOut,
    MarkBatchIn,
    OpenSessionIn,
    ConsentIn,
    CorrectionIn,
    LoginIn,
    OverrideIn,
    RefreshIn,
    RegisterIn,
    RosterIn,
    SessionIn,
    SessionOut,
    TokenOut,
    UserCreateIn,
    UserOut,
)
from app.worker import clock_warning, registry
from app.runtime import cfg as runtime_cfg
from occlubio.utils import get_logger

log = get_logger("app.api")

cfg = runtime_cfg          # one shared instance with app/routes/*
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    bus.bind_loop(asyncio.get_running_loop())
    db = next(get_db())
    try:
        rebuild_index(db, cfg)          # DB is truth; the index is rebuilt from it on every boot
    finally:
        db.close()
    warn = clock_warning()
    if warn:
        log.warning("CLOCK: %s", warn)
    from app.scheduler import scheduler

    scheduler.start()
    yield
    scheduler.stop()
    registry.stop_all()


app = FastAPI(title="Occlusion-Robust Attendance", version="0.1.0", lifespan=lifespan)


# ------------------------------------------------------------------ helpers

def _user_out(u: User) -> UserOut:
    from sqlalchemy.orm import object_session

    from app.models import StudentProfile

    prof = None
    sess = object_session(u)
    if sess is not None:
        prof = sess.scalars(select(StudentProfile).where(StudentProfile.user_id == u.id)).first()
    return UserOut(
        id=u.id, username=u.username, display_name=u.display_name,
        role=u.role.value if isinstance(u.role, Role) else str(u.role),
        roll_number=u.roll_number, email=u.email,
        consent_given=u.consent_given, has_biometrics=u.has_biometrics,
        phone=u.phone, department_id=u.department_id,
        student_status=prof.status if prof else None,
        rejection_reason=prof.rejection_reason if prof else None,
        email_verified=u.email_verified_at is not None,
    )


def _camera_out(c: Camera) -> CameraOut:
    stale = False
    if c.last_heartbeat is not None:
        age = (utcnow() - c.last_heartbeat).total_seconds()
        stale = age > float(cfg.attendance.camera_offline_after_s)
    status_val = c.status.value if isinstance(c.status, CameraStatus) else str(c.status)
    if stale and status_val == CameraStatus.RUNNING.value:
        status_val = CameraStatus.OFFLINE.value
    return CameraOut(
        id=c.id, name=c.name, room=c.room, source=c.source, mode=c.mode,
        status=status_val, status_detail=c.status_detail, last_heartbeat=c.last_heartbeat,
        measured_fps=c.measured_fps, running=registry.is_running(c.id),
    )


def _session_out(s: ClassSession) -> SessionOut:
    return SessionOut(
        id=s.id, title=s.title, room=s.room, camera_id=s.camera_id, owner_id=s.owner_id,
        scheduled_start=s.scheduled_start, scheduled_end=s.scheduled_end, mode=s.mode,
        grace_minutes=s.grace_minutes, min_presence_seconds=s.min_presence_seconds,
    )


def _record_dict(r: AttendanceRecordRow, u: Optional[User]) -> dict:
    return {
        "id": r.id, "user_id": r.user_id,
        "display_name": u.display_name if u else f"user {r.user_id}",
        "roll_number": u.roll_number if u else None,
        "status": r.status, "effective_status": r.effective_status,
        "first_seen": r.first_seen, "last_seen": r.last_seen,
        "total_visible_s": round(r.total_visible_s, 1),
        "avg_confidence": round(r.avg_confidence, 4),
        "frames_matched": r.frames_matched,
        "needs_review": r.needs_review, "review_reason": r.review_reason,
        "evidence": r.evidence,
        "overridden_status": r.overridden_status, "override_reason": r.override_reason,
        "overridden_at": r.overridden_at,
        "computed_at": r.computed_at,
    }


def _get_session_or_404(db: Session, session_id: int) -> ClassSession:
    s = db.get(ClassSession, session_id)
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return s


# --------------------------------------------------------------------- auth

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)


def _find_login_user(db: Session, identifier: str) -> Optional[User]:
    """Username, email or roll number — whichever the person remembers."""
    ident = identifier.strip()
    if not ident:
        return None
    return db.scalars(
        select(User).where(or_(
            User.username == ident,
            func.lower(User.email) == ident.lower(),
            User.roll_number == ident,
        )).where(User.deleted_at.is_(None))
    ).first()


def _student_status(db: Session, user: User) -> Optional[str]:
    from app.models import StudentProfile

    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    return prof.status if prof is not None else None


@app.post("/api/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    from app.crypto import needs_rehash
    from app.ratelimit import client_ip, enforce

    enforce(request, "login")
    user = _find_login_user(db, body.username)
    now = utcnow()

    if user is not None and user.locked_until is not None and user.locked_until > now:
        mins = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "code": "locked",
            "message": f"Too many failed sign-ins. This account is locked for {mins} more "
                       f"minute(s).",
        })

    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_logins = (user.failed_logins or 0) + 1
            if user.failed_logins >= MAX_FAILED_LOGINS:
                user.locked_until = now + LOCKOUT
                user.failed_logins = 0
                db.add(AuditLog(actor_id=user.id, action="account_locked", target_type="user",
                                target_id=str(user.id), ip=client_ip(request),
                                detail=f"{MAX_FAILED_LOGINS} failed sign-ins"))
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "code": "disabled", "message": "This account has been disabled."})

    student_status = _student_status(db, user)
    # Only accounts that were actually sent a code must use it (the full sign-up flow); the
    # legacy register form has no verification step and relies on staff approval alone.
    from app.models import EmailOtp
    was_sent_code = db.scalars(select(EmailOtp.id).where(EmailOtp.user_id == user.id)).first()
    if student_status == "pending" and user.email_verified_at is None and was_sent_code:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "code": "email_unverified",
            "message": "Verify your email address before signing in.",
            "email": user.email,
        })

    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)   # silent upgrade to argon2id
    db.commit()
    return TokenOut(
        access_token=create_token(user, "access"),
        refresh_token=create_token(user, "refresh"),
        role=user.role.value if isinstance(user.role, Role) else str(user.role),
        user_id=user.id, display_name=user.display_name,
        student_status=student_status,
    )


@app.post("/api/auth/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    payload = decode_token(body.refresh_token, expect="refresh")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found")
    # A password change after this refresh token was minted revokes it.
    changed = user.password_changed_at
    if changed is not None and int(payload.get("iat", 0)) < int(changed.timestamp()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired; sign in again")
    return TokenOut(
        access_token=create_token(user, "access"),
        role=user.role.value if isinstance(user.role, Role) else str(user.role),
        user_id=user.id, display_name=user.display_name,
        student_status=_student_status(db, user),
    )


@app.post("/api/auth/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    """Legacy public self-signup used by web/login.html. Creates STUDENT accounts only.

    The account starts PENDING, exactly like the full sign-up at /api/auth/signup: it can sign
    in and see its status, but cannot be marked or mark attendance until staff approve it.
    """
    from app.models import StudentProfile
    from app.notify import notify
    from app.ratelimit import enforce
    from app.scope import department_heads

    enforce(request, "signup")
    out = _create_user(db, body, Role.STUDENT)
    db.add(StudentProfile(user_id=out.id, status="pending", roll_number=out.roll_number))
    notify(db, department_heads(db, None), "registration_pending", "New student registration",
           f"{out.display_name} registered without choosing a class and is waiting for "
           f"approval.", link="/staff/approvals")
    db.commit()
    return _user_out(db.get(User, out.id))


@app.post("/api/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, db: Session = Depends(get_db),
                _: User = Depends(require_admin)):
    try:
        role = Role(body.role)
    except ValueError:
        raise HTTPException(400, f"unknown role: {body.role}")
    return _create_user(db, body, role)


def _create_user(db: Session, body: RegisterIn, role: Role) -> UserOut:
    user = User(
        username=body.username.strip(),
        display_name=body.display_name.strip(),
        email=(body.email or None),
        roll_number=(body.roll_number or None),
        role=role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "username, email or roll number already registered")
    db.refresh(user)
    return _user_out(user)


@app.get("/api/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return _user_out(user)


@app.post("/api/me/consent", response_model=UserOut)
def set_consent(body: ConsentIn, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    """Record or withdraw biometric consent. Enrollment is refused while this is false."""
    if not body.consent_given and user.consent_given:
        svc.erase_biometrics(db, user, cfg, user)        # withdrawal deletes the face data
    user.consent_given = bool(body.consent_given)
    user.consent_at = utcnow() if body.consent_given else None
    user.consent_text_version = body.consent_text_version if body.consent_given else None
    db.add(AuditLog(actor_id=user.id, action="consent_changed", target_type="user",
                    target_id=str(user.id),
                    detail=f"consent_given={user.consent_given} version={body.consent_text_version}"))
    db.commit()
    return _user_out(user)


# --------------------------------------------------------------- enrollment

@app.post("/api/users/{user_id}/enroll")
async def enroll(
    user_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
):
    """Build one averaged face template. Quality-gated, duplicate-checked, consent-gated."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    if not is_staff(actor) and actor.id != user_id:
        raise HTTPException(403, "you may only enroll your own face")

    images = [(f.filename or f"upload_{i}.jpg", await f.read()) for i, f in enumerate(files)]
    try:
        outcome = enroll_user(db, target, images, cfg, get_pipeline(cfg),
                              actor_is_staff=is_staff(actor),
                              status="approved" if is_staff(actor) else "pending")
    except EnrollmentError as exc:
        raise HTTPException(exc.code, detail={"message": exc.message, **exc.extra})

    db.add(AuditLog(actor_id=actor.id, action="enroll", target_type="user",
                    target_id=str(user_id),
                    detail=f"n_images={outcome.n_accepted} mean_quality={outcome.mean_quality:.3f}"))
    db.commit()
    return outcome.as_dict()


@app.delete("/api/users/{user_id}/biometrics")
def delete_biometrics(user_id: int, db: Session = Depends(get_db),
                      actor: User = Depends(current_user)):
    """Erase face templates and crops. Attendance history is retained, anonymised of imagery."""
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "user not found")
    if not is_staff(actor) and actor.id != user_id:
        raise HTTPException(403, "you may only erase your own biometrics")
    return svc.erase_biometrics(db, target, cfg, actor)


@app.get("/api/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_staff),
               q: Optional[str] = None):
    stmt = select(User)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(User.display_name.like(like) | User.username.like(like)
                          | User.roll_number.like(like))
    return [_user_out(u) for u in db.scalars(stmt.limit(500))]


# ------------------------------------------------------------------ cameras

@app.post("/api/cameras", response_model=CameraOut, status_code=201)
def create_camera(body: CameraIn, db: Session = Depends(get_db),
                  _: User = Depends(require_admin)):
    cam = Camera(name=body.name, room=body.room, source=body.source, mode=body.mode)
    db.add(cam)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "a camera with that name already exists")
    db.refresh(cam)
    return _camera_out(cam)


@app.get("/api/cameras", response_model=List[CameraOut])
def list_cameras(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    """Staff only. A student token never sees a camera, by design."""
    return [_camera_out(c) for c in db.scalars(select(Camera))]


@app.post("/api/cameras/{camera_id}/start")
def start_camera(camera_id: int, db: Session = Depends(get_db),
                 actor: User = Depends(require_staff)):
    """Spawn the worker thread. The capture loop never runs inside a request handler."""
    cam = db.get(Camera, camera_id)
    if cam is None:
        raise HTTPException(404, "camera not found")
    worker = registry.start(camera_id, cfg)
    db.add(AuditLog(actor_id=actor.id, action="camera_start", target_type="camera",
                    target_id=str(camera_id)))
    db.commit()
    return {"camera_id": camera_id, "started": worker.is_alive(),
            "antispoof_mode": str(cfg.attendance.antispoof_mode),
            "antispoof_available": get_pipeline(cfg).antispoof_available}


@app.post("/api/cameras/{camera_id}/stop")
def stop_camera(camera_id: int, db: Session = Depends(get_db),
                actor: User = Depends(require_staff)):
    stopped = registry.stop(camera_id)
    cam = db.get(Camera, camera_id)
    if cam is not None:
        cam.status = CameraStatus.STOPPED
        cam.status_detail = "stopped by operator"
    db.add(AuditLog(actor_id=actor.id, action="camera_stop", target_type="camera",
                    target_id=str(camera_id)))
    db.commit()
    return {"camera_id": camera_id, "stopped": stopped}


# ----------------------------------------------------------------- sessions

@app.post("/api/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_db),
                   actor: User = Depends(require_staff)):
    if body.scheduled_end <= body.scheduled_start:
        raise HTTPException(400, "scheduled_end must be after scheduled_start")
    s = ClassSession(
        title=body.title, room=body.room, camera_id=body.camera_id, owner_id=actor.id,
        scheduled_start=body.scheduled_start.astimezone(timezone.utc),
        scheduled_end=body.scheduled_end.astimezone(timezone.utc),
        mode=body.mode or str(cfg.attendance.default_camera_mode),
        grace_minutes=body.grace_minutes if body.grace_minutes is not None
        else int(cfg.attendance.grace_minutes),
        min_presence_seconds=body.min_presence_seconds if body.min_presence_seconds is not None
        else int(cfg.attendance.min_presence_seconds),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return _session_out(s)


def scope_sessions(stmt, actor: User, db: Session):
    """Restrict a ClassSession query to what `actor` may actually open.

    Listing and opening must agree. When they do not, the API hands a user rows and then 403s
    on every one of them -- which is what happened when this list was unscoped while
    `assert_owns_session` enforced a department boundary.
    """
    visible = readable_user_ids(actor, db)
    if visible is not None:
        # Student or parent: only sessions the people they may read are rostered into.
        return stmt.join(RosterEntry, RosterEntry.session_id == ClassSession.id) \
                   .where(RosterEntry.user_id.in_(visible))

    if is_super_admin(actor):
        return stmt

    if is_admin(actor):
        dept = department_scope(actor)
        if dept is None:
            return stmt.where(false())          # an unscoped admin can be shown nothing scoped
        # Sessions in this department, plus ad-hoc ones with no subject (no department to own
        # them) -- mirrors assert_owns_session exactly.
        return stmt.outerjoin(Subject, Subject.id == ClassSession.subject_id) \
                   .where(or_(ClassSession.subject_id.is_(None),
                              Subject.department_id == dept))

    # Faculty: sessions they own, or are the assigned teacher of record for.
    assigned = select(FacultyAssignment.subject_id, FacultyAssignment.section_id) \
        .where(FacultyAssignment.faculty_id == actor.id).subquery()
    return stmt.where(or_(
        ClassSession.owner_id == actor.id,
        tuple_(ClassSession.subject_id, ClassSession.section_id).in_(select(assigned)),
    ))


@app.get("/api/sessions", response_model=List[SessionOut])
def list_sessions(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    stmt = scope_sessions(
        select(ClassSession).order_by(ClassSession.scheduled_start.desc()), actor, db)
    return [_session_out(s) for s in db.scalars(stmt.limit(300))]


@app.post("/api/sessions/{session_id}/roster")
def set_roster(session_id: int, body: RosterIn, db: Session = Depends(get_db),
               actor: User = Depends(require_staff)):
    s = _get_session_or_404(db, session_id)
    assert_owns_session(actor, s)
    db.query(RosterEntry).filter(RosterEntry.session_id == session_id).delete()
    for uid in dict.fromkeys(body.user_ids):
        db.add(RosterEntry(session_id=session_id, user_id=uid))
    db.commit()
    return {"session_id": session_id, "roster_size": len(set(body.user_ids))}


@app.get("/api/sessions/{session_id}/attendance")
def session_attendance(session_id: int, db: Session = Depends(get_db),
                       actor: User = Depends(current_user)):
    s = _get_session_or_404(db, session_id)
    visible = readable_user_ids(actor, db)
    if visible is not None:
        # Non-staff: rows are filtered to the people this actor may read, and they must
        # actually be on the roster -- otherwise the session is not theirs to see at all.
        rostered = db.scalars(select(RosterEntry).where(
            RosterEntry.session_id == session_id,
            RosterEntry.user_id.in_(visible))).first()
        if rostered is None:
            raise HTTPException(403, "you are not rostered into this session")
        records = [r for r in svc.ensure_records(db, s, cfg) if r.user_id in visible]
    else:
        assert_owns_session(actor, s)
        records = svc.ensure_records(db, s, cfg)

    users = {u.id: u for u in db.scalars(select(User))}
    payload = [_record_dict(r, users.get(r.user_id)) for r in records]
    return {
        "session": _session_out(s),
        "records": payload,
        "review_queue": [p for p in payload
                         if p["needs_review"] or p["effective_status"] == Status.NEEDS_REVIEW.value],
        "summary": svc.session_summary(records, cfg) if is_staff(actor) else None,
    }


@app.post("/api/sessions/{session_id}/recompute")
def recompute(session_id: int, db: Session = Depends(get_db),
              actor: User = Depends(require_staff)):
    s = _get_session_or_404(db, session_id)
    assert_owns_session(actor, s)
    rows = svc.recompute_session(db, s, cfg, actor)
    return {"session_id": session_id, "records": len(rows),
            "summary": svc.session_summary(rows, cfg)}


# ------------------------------------------------------------------ marking
#
# Kept above the parameterised `/api/attendance/{record_id}` for readability. Starlette does
# not actually require it — it collects partial (path-matched, method-mismatched) routes and
# keeps searching, returning 405 only when nothing fully matches — but grouping the literal
# paths first makes the shadowing question obvious to the next reader.

@app.post("/api/attendance/sessions", status_code=201)
def open_marking_session(body: OpenSessionIn, db: Session = Depends(get_db),
                         actor: User = Depends(require_staff)):
    """Open (or re-open) the dated session for a timetable slot. Idempotent."""
    from datetime import date as _date

    slot = db.get(TimetableSlot, body.slot_id)
    if slot is None:
        raise HTTPException(404, "timetable slot not found")

    # Authorisation is on the SLOT, because no session exists yet to check ownership against.
    if not is_super_admin(actor):
        if is_admin(actor):
            subject = db.get(Subject, slot.subject_id)
            assert_in_department(actor, subject.department_id if subject else None, "slot")
        elif slot.faculty_id != actor.id:
            raise HTTPException(403, "you do not teach this period")

    on = _date.fromisoformat(body.date) if body.date else local_today(tz_of(cfg))
    try:
        session = marking.open_session(db, slot, on, actor, cfg)
    except marking.MarkingError as exc:
        raise HTTPException(exc.code, detail={"message": exc.message, **exc.extra})
    return marking.roster_view(db, session)


@app.get("/api/attendance/sessions/{session_id}/roster")
def marking_roster(session_id: int, db: Session = Depends(get_db),
                   actor: User = Depends(require_staff)):
    """Students plus any mark already recorded — one request, everything the screen needs."""
    s = _get_session_or_404(db, session_id)
    assert_owns_session(actor, s)
    return marking.roster_view(db, s)


@app.post("/api/attendance/sessions/{session_id}/records")
def save_marking(session_id: int, body: MarkBatchIn, db: Session = Depends(get_db),
                 actor: User = Depends(require_staff)):
    """Bulk upsert, transactional. All marks land or none do."""
    s = _get_session_or_404(db, session_id)
    assert_can_mark_session(actor, s)
    try:
        result = marking.save_marks(db, s, [m.model_dump() for m in body.marks], actor, cfg,
                                    reason=body.reason)
    except marking.MarkingError as exc:
        raise HTTPException(exc.code, detail={"message": exc.message, **exc.extra})

    emit("attendance_marked", {"session_id": s.id, "by": actor.display_name,
                               "at": result["marked_at"].isoformat()}, session_id=s.id)
    return result


@app.patch("/api/attendance/{record_id}")
def override_record(record_id: int, body: OverrideIn, db: Session = Depends(get_db),
                    actor: User = Depends(require_staff)):
    """Override a derived status. `reason` is mandatory and is written to the audit log."""
    row = db.get(AttendanceRecordRow, record_id)
    if row is None:
        raise HTTPException(404, "record not found")
    s = _get_session_or_404(db, row.session_id)
    assert_owns_session(actor, s)
    if body.status not in marking.MARKABLE:
        raise HTTPException(400, f"unknown status: {body.status}")

    new_status = body.status
    before = row.effective_status
    row.overridden_status = new_status
    row.override_reason = body.reason
    row.overridden_by_id = actor.id
    row.overridden_at = utcnow()
    row.needs_review = False
    db.add(AuditLog(actor_id=actor.id, action="attendance_override",
                    target_type="attendance_record", target_id=str(record_id),
                    reason=body.reason, detail=f"{before} -> {new_status}"))
    if before != new_status:
        from app.notify import notify

        notify(db, [row.user_id], "attendance_changed", "Attendance changed by your teacher",
               f"{s.title}: {before.replace('_', ' ')} to {new_status.replace('_', ' ')}. "
               f"Reason: {body.reason}.", link="/student/history", email=True)
    db.commit()

    emit("record_overridden", {"record_id": record_id, "user_id": row.user_id,
                               "status": new_status, "by": actor.display_name,
                               "reason": body.reason},
         session_id=row.session_id, threadsafe=False)
    return _record_dict(row, db.get(User, row.user_id))


# ----------------------------------------------------------------- unknowns

@app.get("/api/sessions/{session_id}/unknowns")
def list_unknowns(session_id: int, db: Session = Depends(get_db),
                  actor: User = Depends(require_staff)):
    s = _get_session_or_404(db, session_id)
    assert_owns_session(actor, s)
    rows = db.scalars(select(UnknownSighting).where(UnknownSighting.session_id == session_id))
    return [{"id": u.id, "track_id": u.track_id, "first_seen": u.first_seen,
             "last_seen": u.last_seen, "best_score": round(u.best_score, 4), "frames": u.frames,
             "thumbnail": bool(u.thumbnail_path), "resolved_user_id": u.resolved_user_id}
            for u in rows]


@app.post("/api/sessions/{session_id}/unknowns/{unknown_id}/assign")
def assign_unknown(session_id: int, unknown_id: int, body: AssignUnknownIn,
                   db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Attach an unknown face to a person. Always a human decision, never automatic."""
    s = _get_session_or_404(db, session_id)
    assert_owns_session(actor, s)
    u = db.get(UnknownSighting, unknown_id)
    if u is None or u.session_id != session_id:
        raise HTTPException(404, "unknown sighting not found in this session")
    target = db.get(User, body.user_id)
    if target is None:
        raise HTTPException(404, "user not found")

    u.resolved_user_id = target.id
    u.resolved_by_id = actor.id
    u.resolved_at = utcnow()
    db.add(Sighting(
        session_id=session_id, camera_id=u.camera_id, user_id=target.id, track_id=u.track_id,
        first_seen=u.first_seen, last_seen=u.last_seen, frames_matched=u.frames,
        median_confidence=u.best_score, max_confidence=u.best_score,
        confirmed=True, antispoof_result="not_evaluated", needs_review=False,
        review_reason=f"manually assigned by {actor.username}: {body.reason}",
    ))
    db.add(AuditLog(actor_id=actor.id, action="assign_unknown", target_type="unknown_sighting",
                    target_id=str(unknown_id), reason=body.reason,
                    detail=f"assigned to user {target.id}"))
    db.commit()
    svc.recompute_session(db, s, cfg, actor)
    return {"unknown_id": unknown_id, "assigned_to": target.id}


# --------------------------------------------------------------------- self

@app.get("/api/me/attendance")
def my_attendance(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """A student's own history. Scoped by user id in the query — no other rows are loaded."""
    rows = list(db.scalars(select(AttendanceRecordRow)
                           .where(AttendanceRecordRow.user_id == actor.id)))
    sessions = {s.id: s for s in db.scalars(select(ClassSession))}
    counted = sum(1 for r in rows if r.effective_status in (Status.PRESENT.value, Status.LATE.value))
    pct = 100.0 * counted / len(rows) if rows else 0.0
    return {
        "user": _user_out(actor),
        "records": [{**_record_dict(r, actor),
                     "session_title": sessions[r.session_id].title if r.session_id in sessions else "",
                     "session_start": sessions[r.session_id].scheduled_start
                     if r.session_id in sessions else None}
                    for r in rows],
        "attendance_pct": round(pct, 1),
        "minimum_pct": float(cfg.attendance.minimum_attendance_pct),
        "meets_minimum": pct >= float(cfg.attendance.minimum_attendance_pct),
    }


@app.get("/api/me/summary")
def my_summary(user_id: Optional[int] = None, db: Session = Depends(get_db),
               actor: User = Depends(current_user)):
    """Percentage, per-subject breakdown, calendar and the can-miss counter.

    `user_id` lets a parent read their linked student and staff read any student; everyone else
    is pinned to themselves by `assert_can_read_user`.
    """
    target = actor
    if user_id is not None and user_id != actor.id:
        assert_can_read_user(actor, user_id, db)
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, "user not found")
    elif is_parent(actor):
        linked = sorted(readable_user_ids(actor, db) or set())
        if not linked:
            raise HTTPException(404, "no student is linked to this account")
        target = db.get(User, linked[0])

    summary = analytics.student_summary(db, target, threshold=_threshold(),
                                        tz=tz_of(cfg))
    summary["calendar"] = analytics.attendance_calendar(db, target.id)
    summary["student"] = {"id": target.id, "display_name": target.display_name,
                          "roll_number": target.roll_number}
    return summary


@app.post("/api/me/corrections", status_code=201)
def request_correction(body: CorrectionIn, db: Session = Depends(get_db),
                       actor: User = Depends(current_user)):
    """Dispute your own record. Never edits attendance — it opens a request for a human."""
    _get_session_or_404(db, body.session_id)
    cr = CorrectionRequest(user_id=actor.id, session_id=body.session_id, message=body.message)
    db.add(cr)
    db.add(AuditLog(actor_id=actor.id, action="correction_requested", target_type="session",
                    target_id=str(body.session_id)))
    db.commit()
    db.refresh(cr)
    return {"id": cr.id, "status": cr.status}


@app.post("/api/admin/lock-stale-sessions")
def lock_stale(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    """Lock every session past the edit window. Safe to run on a schedule."""
    n = marking.lock_stale_sessions(db, cfg)
    db.add(AuditLog(actor_id=actor.id, action="lock_stale_sessions", detail=f"locked={n}"))
    db.commit()
    return {"locked": n}


# ---------------------------------------------------------------- analytics
#
# Every route here resolves its own department scope from the actor. A super admin may pass
# ?department_id= to narrow; an HOD is pinned to theirs and cannot widen it by passing another.

def _scope_or_403(actor: User, requested: Optional[int]) -> Optional[int]:
    own = department_scope(actor)
    if own is None:                       # super admin: may narrow to any department, or none
        return requested
    if requested is not None and requested != own:
        raise HTTPException(403, "you may only report on your own department")
    return own


def _threshold() -> float:
    return float(getattr(cfg.attendance, "min_attendance_pct", 75.0))


@app.get("/api/timetable/today")
def timetable_today(on: Optional[str] = None, db: Session = Depends(get_db),
                    actor: User = Depends(require_staff)):
    """The periods this user is responsible for today, each with its marked status."""
    from datetime import date as _date

    when = _date.fromisoformat(on) if on else None
    return {
        "date": (when or local_today(tz_of(cfg))).isoformat(),
        "periods": analytics.todays_periods(db, actor, on=when,
                                            department_id=department_scope(actor),
                                            tz=tz_of(cfg)),
    }


@app.get("/api/reports/defaulters")
def report_defaulters(threshold: Optional[float] = None, department_id: Optional[int] = None,
                      section_id: Optional[int] = None, limit: int = 500,
                      db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Students below the minimum. Computed in SQL and returned worst-first."""
    scope = _scope_or_403(actor, department_id)
    rows = analytics.defaulters(db, threshold=threshold or _threshold(),
                                department_id=scope, section_id=section_id, limit=limit)
    return {"threshold_pct": threshold or _threshold(), "count": len(rows), "defaulters": rows}


def _filters_from_query(
    date_from: Optional[str], date_to: Optional[str], department_id: Optional[int],
    section_id: Optional[int], subject_id: Optional[int], faculty_id: Optional[int],
    student_id: Optional[int], status: Optional[str], search: Optional[str],
) -> reports.ReportFilters:
    from datetime import date as _date

    def parse(v: Optional[str]) -> Optional[_date]:
        if not v:
            return None
        try:
            return _date.fromisoformat(v)
        except ValueError:
            raise HTTPException(422, f"not a date: {v!r} (expected YYYY-MM-DD)")

    return reports.ReportFilters(
        date_from=parse(date_from), date_to=parse(date_to), department_id=department_id,
        section_id=section_id, subject_id=subject_id, faculty_id=faculty_id,
        student_id=student_id, status=status, search=search,
    )


@app.get("/api/reports/attendance")
def report_attendance(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    department_id: Optional[int] = None, section_id: Optional[int] = None,
    subject_id: Optional[int] = None, faculty_id: Optional[int] = None,
    student_id: Optional[int] = None, status: Optional[str] = None,
    search: Optional[str] = None, page: int = 1, page_size: int = 50,
    db: Session = Depends(get_db), actor: User = Depends(require_staff),
):
    """The filter-builder report. Paginated in SQL — never ships the whole term to a browser."""
    scope = _scope_or_403(actor, department_id)
    filters = _filters_from_query(date_from, date_to, department_id, section_id, subject_id,
                                  faculty_id, student_id, status, search)
    total = reports.count_records(db, filters, scope)
    rows = reports.query_records(db, filters, scope, page=page, page_size=page_size,
                                 tz=str(cfg.attendance.timezone))
    size = max(1, min(reports.MAX_PAGE_SIZE, page_size))
    return {
        "rows": rows,
        "meta": {"page": max(1, page), "page_size": size, "total": total,
                 "pages": (total + size - 1) // size},
    }


@app.get("/api/reports/options")
def report_options(db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Values for the filter builder, scoped exactly like the report they filter.

    An HOD must not be offered another department's sections in a dropdown — an option they
    cannot use is a bug report waiting to happen.
    """
    from app.models import AttendanceStatus, Department, Program, Section, Subject

    scope = department_scope(actor)

    dept_stmt = select(Department).order_by(Department.code)
    if scope is not None:
        dept_stmt = dept_stmt.where(Department.id == scope)
    departments = list(db.scalars(dept_stmt))

    subj_stmt = select(Subject).order_by(Subject.code)
    if scope is not None:
        subj_stmt = subj_stmt.where(Subject.department_id == scope)
    subjects = list(db.scalars(subj_stmt))

    sec_stmt = select(Section, Program).join(Program, Program.id == Section.program_id)
    if scope is not None:
        sec_stmt = sec_stmt.where(Program.department_id == scope)
    sections = [
        {"id": s.id, "label": f"{p.name} Y{s.year}S{s.semester}-{s.name}"}
        for s, p in db.execute(sec_stmt).all()
    ]
    sections.sort(key=lambda x: x["label"])

    return {
        "departments": [{"id": d.id, "label": f"{d.code} — {d.name}"} for d in departments],
        "subjects": [{"id": s.id, "label": f"{s.code} — {s.name}"} for s in subjects],
        "sections": sections,
        "statuses": [s.value for s in AttendanceStatus],
    }


@app.get("/api/reports/daily-absentees")
def report_daily_absentees(date: Optional[str] = None, section_id: Optional[int] = None,
                           db: Session = Depends(get_db),
                           actor: User = Depends(require_staff)):
    """One row per absent student, with the periods they missed."""
    from datetime import date as _date

    on = _date.fromisoformat(date) if date else local_today(tz_of(cfg))
    scope = department_scope(actor)
    rows = reports.daily_absentees(db, on, scope, section_id=section_id,
                                   tz=str(cfg.attendance.timezone))
    return {"date": on.isoformat(), "count": len(rows), "absentees": rows}


@app.get("/api/reports/export")
def export_report(
    format: str = "csv",
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    department_id: Optional[int] = None, section_id: Optional[int] = None,
    subject_id: Optional[int] = None, faculty_id: Optional[int] = None,
    student_id: Optional[int] = None, status: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db), actor: User = Depends(require_staff),
):
    """Export the CURRENT filter set as CSV, XLSX or PDF.

    Built from the same query as the on-screen table, so an export can never disagree with what
    the user was looking at when they clicked it.
    """
    fmt = format.lower()
    if fmt not in reports.EXPORTERS:
        raise HTTPException(422, f"unknown format {format!r}; expected csv, xlsx or pdf")

    scope = _scope_or_403(actor, department_id)
    filters = _filters_from_query(date_from, date_to, department_id, section_id, subject_id,
                                  faculty_id, student_id, status, search)

    total = reports.count_records(db, filters, scope)
    limit = reports.EXPORT_ROW_LIMITS[fmt]
    if total > limit:
        hint = ("narrow the filters, or export XLSX/CSV which have no practical row limit"
                if fmt == "pdf"
                else "narrow the filters (a date range is usually enough)")
        raise HTTPException(413, detail={
            "message": f"{total:,} rows exceeds the {limit:,}-row limit for {fmt.upper()}; {hint}",
            "total": total, "limit": limit, "format": fmt,
        })

    rows = reports.query_records(db, filters, scope, limit=limit,
                                 tz=str(cfg.attendance.timezone))
    render, media_type, ext = reports.EXPORTERS[fmt]
    org = str(getattr(cfg.attendance, "organisation", "Attendance Register"))
    payload = render(rows, org, filters, total, str(cfg.attendance.timezone))

    db.add(AuditLog(actor_id=actor.id, action="export_report", target_type="report",
                    detail=f"format={fmt} rows={len(rows)} filters={filters.describe()}",
                    ip=None))
    db.commit()

    stamp = utcnow().strftime("%Y%m%d-%H%M")
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="attendance-{stamp}.{ext}"'},
    )


@app.get("/api/analytics/summary")
def analytics_summary(department_id: Optional[int] = None, db: Session = Depends(get_db),
                      actor: User = Depends(require_staff)):
    scope = _scope_or_403(actor, department_id)
    return analytics.org_summary(db, department_id=scope, threshold=_threshold())


@app.get("/api/analytics/trend")
def analytics_trend(days: int = 30, department_id: Optional[int] = None,
                    db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """One aligned series per department, for the trend chart."""
    scope = _scope_or_403(actor, department_id)
    ids = [scope] if scope is not None else None
    return analytics.trend_by_department(db, days=days, department_ids=ids)


@app.get("/api/analytics/weekday")
def analytics_weekday(days: int = 90, department_id: Optional[int] = None,
                      db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    scope = _scope_or_403(actor, department_id)
    return {"days": days, "profile": analytics.weekday_profile(db, days=days,
                                                               department_id=scope)}


# ---------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db), actor: User = Depends(current_user),
              session_id: Optional[int] = None):
    """Role-scoped payload. The role decides what is *fetched*, not what is displayed."""
    role = actor.role.value if isinstance(actor.role, Role) else str(actor.role)
    now = utcnow()
    base = {"role": role, "user": _user_out(actor).model_dump(),
            "server_time_utc": now, "timezone": str(cfg.attendance.timezone),
            "system": system_status(db)}

    # Allow-list: anyone who is not staff gets the self-scoped payload. A parent sees their
    # linked student; a student sees themselves. Neither ever receives camera data.
    if not is_staff(actor):
        subject = actor
        if is_parent(actor):
            linked = sorted(readable_user_ids(actor, db) or set())
            if not linked:
                return {**base, "scope": "self", "attendance_pct": 0.0,
                        "meets_minimum": False, "records": [], "cameras": [],
                        "linked_students": []}
            subject = db.get(User, linked[0])
            base["linked_students"] = [
                {"id": u.id, "display_name": u.display_name, "roll_number": u.roll_number}
                for u in db.scalars(select(User).where(User.id.in_(linked)))
            ]
            base["viewing_student_id"] = subject.id

        mine = my_attendance(db, subject)
        base.update({
            "scope": "self",
            "attendance_pct": mine["attendance_pct"],
            "meets_minimum": mine["meets_minimum"],
            "records": mine["records"][-50:],
            "cameras": [],          # a student or parent never receives camera data
        })
        return base

    stmt = scope_sessions(
        select(ClassSession).order_by(ClassSession.scheduled_start.desc()), actor, db)
    sessions = list(db.scalars(stmt.limit(50)))

    live = [s for s in sessions
            if s.scheduled_start - timedelta(minutes=int(cfg.attendance.early_checkin_minutes))
            <= now <= s.scheduled_end + timedelta(minutes=int(cfg.attendance.late_checkin_minutes))]
    target = db.get(ClassSession, session_id) if session_id else (live[0] if live else
                                                                  (sessions[0] if sessions else None))

    payload = {"scope": "staff", "sessions": [_session_out(s).model_dump() for s in sessions],
               "live_session_ids": [s.id for s in live],
               "cameras": [_camera_out(c).model_dump() for c in db.scalars(select(Camera))]}
    if target is not None:
        assert_owns_session(actor, target)
        records = svc.ensure_records(db, target, cfg)
        users = {u.id: u for u in db.scalars(select(User))}
        rows = [_record_dict(r, users.get(r.user_id)) for r in records]
        payload.update({
            "session": _session_out(target).model_dump(),
            "records": rows,
            "summary": svc.session_summary(records, cfg),
            "review_queue": [r for r in rows if r["needs_review"]
                             or r["effective_status"] == Status.NEEDS_REVIEW.value],
            "unknown_count": db.scalar(select(func.count()).select_from(UnknownSighting)
                                       .where(UnknownSighting.session_id == target.id)) or 0,
        })
    base.update(payload)
    return base


def system_status(db: Session) -> dict:
    """Conditions the operator must see: missing PAD weights, clock drift, unvalidated thresholds."""
    pipeline_ready = False
    antispoof = False
    try:
        p = get_pipeline(cfg)
        pipeline_ready = True
        antispoof = p.antispoof_available
    except Exception as exc:                 # model not downloaded yet, etc.
        log.warning("pipeline unavailable: %s", exc)

    warnings: List[str] = []
    if not antispoof:
        warnings.append(
            "ANTI-SPOOFING DISABLED — no PAD weights loaded. A printed photo or a phone screen "
            "can be stamped present. Set antispoof.onnx_path in configs/default.yaml."
        )
    clock = clock_warning()
    if clock:
        warnings.append(f"CLOCK: {clock}")
    warnings.append(
        "THRESHOLDS UNVALIDATED — match/review/dup thresholds are the spec's placeholder values, "
        "not values derived from a ROC curve on enrolled faces. Run tools/roc.py."
    )
    return {
        "pipeline_ready": pipeline_ready,
        "antispoof_available": antispoof,
        "antispoof_mode": str(cfg.attendance.antispoof_mode),
        "gallery_size": len(get_gallery(db, cfg)),
        "warnings": warnings,
        "thresholds": {
            "match_threshold": float(cfg.gallery.match_threshold),
            "review_threshold": float(cfg.gallery.review_threshold),
            "dup_threshold": float(cfg.gallery.dup_threshold),
            "min_quality": float(cfg.quality.min_score),
            "confirm_frames": int(cfg.attendance.confirm_frames),
        },
    }


@app.get("/api/system/status")
def system_status_endpoint(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return system_status(db)


@app.get("/api/audit")
def audit(db: Session = Depends(get_db), _: User = Depends(require_admin), limit: int = 200):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(limit))
    return [{"id": a.id, "actor_id": a.actor_id, "action": a.action,
             "target_type": a.target_type, "target_id": a.target_id,
             "reason": a.reason, "detail": a.detail, "at": a.at} for a in rows]


@app.post("/api/admin/retention")
def retention(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return svc.run_retention(db, cfg, actor)


# ------------------------------------------------------------------ reports

@app.get("/api/reports/attendance.csv")
def attendance_csv(session_id: int = Query(...), db: Session = Depends(get_db),
                   actor: User = Depends(require_staff)):
    s = _get_session_or_404(db, session_id)
    assert_owns_session(actor, s)
    records = svc.ensure_records(db, s, cfg)
    body = svc.records_csv(db, s, records)
    db.add(AuditLog(actor_id=actor.id, action="export_csv", target_type="session",
                    target_id=str(session_id), detail=f"{len(records)} record(s)"))
    db.commit()
    return PlainTextResponse(
        body, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="attendance_session_{session_id}.csv"'},
    )


# ---------------------------------------------------------------- live SSE

@app.get("/api/live/stream")
async def live_stream(request: Request, session_id: Optional[int] = None,
                      actor: User = Depends(current_user)):
    """Server-sent events. Staff only.

    Written as an allow-list, not `if is_student(...)`. A deny-one-role check silently grants
    the stream to every role added to the enum afterwards -- which is exactly how PARENT ended
    up able to watch every classroom camera.
    """
    if not is_staff(actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "only staff may open the live camera stream")

    queue = bus.subscribe(session_id)

    async def gen():
        try:
            hello = json.dumps({"session_id": session_id, "resync": True,
                                "note": "re-fetch /api/sessions/{id}/attendance on connect; "
                                        "a missed event never means a missed record"})
            yield f"event: hello\ndata: {hello}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield ev.to_sse()
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ portal routers

from app.routes import academic as _academic  # noqa: E402
from app.routes import accounts as _accounts  # noqa: E402
from app.routes import admin as _admin  # noqa: E402
from app.routes import files as _files  # noqa: E402
from app.routes import face as _face  # noqa: E402
from app.routes import issues as _issues  # noqa: E402
from app.routes import leaves as _leaves  # noqa: E402
from app.routes import messaging as _messaging  # noqa: E402
from app.routes import notifications as _notifications  # noqa: E402
from app.routes import sessions as _sessions  # noqa: E402
from app.routes import students as _students  # noqa: E402

for _r in (_academic.router, _accounts.router, _students.router, _files.router, _admin.router,
           _sessions.router, _leaves.router, _issues.router, _messaging.router,
           _notifications.router, _face.router):
    app.include_router(_r)


# ------------------------------------------------------------------ static

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return RedirectResponse("/static/login.html")
