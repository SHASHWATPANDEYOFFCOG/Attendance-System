"""Student self-registration, email verification, password reset, and the student's own profile.

Flow:  sign up -> OTP emailed -> verify -> status PENDING -> a teacher of the class approves or
rejects (with a reason) -> APPROVED students can mark attendance.

After approval the identity fields (roll number, enrollment number, branch, batch, year, section,
name) are locked; changing them needs an edit request a teacher approves.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import timedelta
from typing import Dict, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import validation as V
from app.audit import audit
from app.auth import current_user
from app.crypto import hash_password, otp_digest, token_digest, verify_password
from app.db import get_db
from app.models import (
    Batch,
    Department,
    EmailOtp,
    PasswordResetToken,
    ProfileEditRequest,
    ReviewStatus,
    Role,
    Section,
    StudentProfile,
    StudentStatus,
    User,
    utcnow,
)
from app.notify import notify
from app.ratelimit import enforce
from app.routes.academic import section_label
from app.runtime import public_base_url
from app.scope import responsible_staff
from app.uploads import IMAGES, MB, delete_file, save_upload

router = APIRouter(prefix="/api", tags=["accounts"])

OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
RESET_TTL = timedelta(minutes=30)

#: Fields a student may change themselves once approved.
SELF_EDITABLE = ("phone", "address", "guardian_name", "guardian_phone", "guardian_email",
                 "gender", "dob")
#: Fields locked by approval; changing them needs a teacher-approved edit request.
LOCKED = ("full_name", "roll_number", "enrollment_no", "department_id", "batch_id", "year",
          "section_id")


def _invalid(exc: V.Invalid) -> HTTPException:
    return HTTPException(422, detail={"message": exc.message, "field": exc.field})


def _profile(db: Session, user_id: int) -> Optional[StudentProfile]:
    return db.scalars(select(StudentProfile).where(StudentProfile.user_id == user_id)).first()


# ----------------------------------------------------------- uniqueness rules

def check_unique(db: Session, *, email: Optional[str] = None, phone: Optional[str] = None,
                 roll: Optional[str] = None, department_id: Optional[int] = None,
                 batch_id: Optional[int] = None, exclude_user: Optional[int] = None) -> None:
    def other(stmt):
        if exclude_user is not None:
            stmt = stmt.where(User.id != exclude_user)
        return db.scalars(stmt).first()

    if email and other(select(User).where(func.lower(User.email) == email.lower())):
        raise HTTPException(409, detail={"field": "email",
                                         "message": "This email is already registered. Sign in "
                                                    "or reset your password instead."})
    if phone and other(select(User).where(User.phone == phone)):
        raise HTTPException(409, detail={"field": "mobile",
                                         "message": "This mobile number is already registered."})
    if roll:
        stmt = select(StudentProfile).join(User, User.id == StudentProfile.user_id).where(
            func.upper(StudentProfile.roll_number) == roll.upper(),
            StudentProfile.department_id == department_id, StudentProfile.batch_id == batch_id,
            User.deleted_at.is_(None))
        if exclude_user is not None:
            stmt = stmt.where(StudentProfile.user_id != exclude_user)
        clash = db.scalars(stmt).first()
        if clash:
            dept = db.get(Department, department_id) if department_id else None
            batch = db.get(Batch, batch_id) if batch_id else None
            where = " ".join(x for x in (dept.code if dept else "", batch.label if batch else "") if x)
            raise HTTPException(409, detail={
                "field": "roll_number",
                "message": f"Roll number {roll} is already registered in {where or 'this class'}."})
        if other(select(User).where(func.upper(User.roll_number) == roll.upper())):
            raise HTTPException(409, detail={
                "field": "roll_number",
                "message": f"Roll number {roll} is already in use by another account."})


def resolve_class(db: Session, department_id: int, batch_id: int, year: int,
                  section_id: int) -> Section:
    """The section must actually be the chosen branch + batch + year."""
    dept = db.get(Department, department_id)
    batch = db.get(Batch, batch_id)
    sec = db.get(Section, section_id)
    if dept is None:
        raise HTTPException(422, detail={"field": "department_id", "message": "Choose your branch."})
    if batch is None:
        raise HTTPException(422, detail={"field": "batch_id", "message": "Choose your batch."})
    if sec is None:
        raise HTTPException(422, detail={"field": "section_id", "message": "Choose your section."})
    if sec.program.department_id != dept.id or sec.year != year or \
            (sec.batch_id is not None and sec.batch_id != batch.id):
        raise HTTPException(422, detail={
            "field": "section_id",
            "message": "That section does not belong to the branch, batch and year you chose."})
    return sec


def _username_for(db: Session, email: str) -> str:
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:48] or "student"
    candidate, n = base, 1
    while db.scalars(select(User.id).where(User.username == candidate)).first() is not None:
        n += 1
        candidate = f"{base}{n}"
    return candidate


# ---------------------------------------------------------------------- OTP

def issue_otp(db: Session, user: User) -> None:
    code = f"{secrets.randbelow(10**6):06d}"
    salt = secrets.token_hex(8)
    for old in db.scalars(select(EmailOtp).where(EmailOtp.user_id == user.id,
                                                 EmailOtp.consumed_at.is_(None))):
        old.consumed_at = utcnow()          # only the newest code is valid
    db.add(EmailOtp(user_id=user.id, purpose="verify_email",
                    code_hash=f"{salt}${otp_digest(code, salt)}",
                    expires_at=utcnow() + OTP_TTL))
    notify(db, [user.id], "verify_email", "Your verification code",
           f"Your attendance portal verification code is {code}. It expires in 10 minutes. "
           f"If you did not sign up, ignore this email.", email=True, sensitive=True)


# ------------------------------------------------------------------ sign-up

@router.post("/auth/signup", status_code=201)
async def signup(
    request: Request,
    full_name: str = Form(...), email: str = Form(...), mobile: str = Form(...),
    password: str = Form(...), roll_number: str = Form(...), enrollment_no: str = Form(...),
    department_id: int = Form(...), year: int = Form(...), batch_id: int = Form(...),
    section_id: int = Form(...), dob: str = Form(...), gender: str = Form(...),
    guardian_name: str = Form(...), guardian_phone: str = Form(...),
    guardian_email: Optional[str] = Form(None), address: str = Form(...),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    enforce(request, "signup")
    try:
        data = {
            "full_name": V.name(full_name),
            "email": V.email(email),
            "phone": V.phone(mobile),
            "password": V.password(password),
            "roll_number": V.roll(roll_number),
            "enrollment_no": V.text(enrollment_no, "enrollment_no", 48, required=True),
            "dob": V.dob(dob),
            "gender": V.gender(gender),
            "guardian_name": V.name(guardian_name, "guardian_name"),
            "guardian_phone": V.phone(guardian_phone, "guardian_phone"),
            "guardian_email": V.email(guardian_email, "guardian_email", required=False),
            "address": V.text(address, "address", 500, required=True, min_len=5),
        }
    except V.Invalid as exc:
        raise _invalid(exc)
    if data["phone"] == data["guardian_phone"]:
        raise HTTPException(422, detail={"field": "guardian_phone",
                                         "message": "Give a guardian's number, not your own."})

    sec = resolve_class(db, department_id, batch_id, year, section_id)
    check_unique(db, email=data["email"], phone=data["phone"], roll=data["roll_number"],
                 department_id=department_id, batch_id=batch_id)
    if db.scalars(select(StudentProfile.id).where(
            StudentProfile.enrollment_no == data["enrollment_no"])).first():
        raise HTTPException(409, detail={"field": "enrollment_no",
                                         "message": "This enrollment number is already registered."})

    user = User(username=_username_for(db, data["email"]), display_name=data["full_name"],
                email=data["email"], phone=data["phone"], roll_number=data["roll_number"],
                role=Role.STUDENT, password_hash=hash_password(data["password"]),
                department_id=None)
    db.add(user)
    db.flush()
    pic = await save_upload(db, photo, owner_id=user.id, purpose="profile_photo",
                            allowed=IMAGES, max_bytes=3 * MB)
    db.add(StudentProfile(
        user_id=user.id, section_id=sec.id, department_id=department_id, batch_id=batch_id,
        year=year, roll_number=data["roll_number"], enrollment_no=data["enrollment_no"],
        dob=data["dob"], gender=data["gender"], guardian_name=data["guardian_name"],
        guardian_phone=data["guardian_phone"], guardian_email=data["guardian_email"],
        address=data["address"], photo_file_id=pic.id, status=StudentStatus.PENDING.value,
        admission_year=db.get(Batch, batch_id).start_year,
    ))
    issue_otp(db, user)
    audit(db, user, "student_signup", target_type="user", target_id=user.id,
          detail={"section_id": sec.id, "roll": data["roll_number"]}, request=request)
    db.commit()
    return {"email": user.email, "otp_sent": True,
            "message": "We emailed you a 6-digit code. Enter it to verify your email."}


class VerifyIn(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


@router.post("/auth/verify-email")
def verify_email(body: VerifyIn, request: Request, db: Session = Depends(get_db)):
    enforce(request, "otp")
    bad = HTTPException(400, detail={"field": "code",
                                     "message": "That code is wrong or has expired."})
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.strip().lower(),
                                         User.deleted_at.is_(None))).first()
    if user is None:
        raise bad
    if user.email_verified_at is not None:
        return {"verified": True, "message": "Your email is already verified. Sign in."}
    otp = db.scalars(select(EmailOtp).where(EmailOtp.user_id == user.id,
                                            EmailOtp.consumed_at.is_(None))
                     .order_by(EmailOtp.created_at.desc())).first()
    if otp is None or otp.expires_at < utcnow() or otp.attempts >= OTP_MAX_ATTEMPTS:
        raise bad
    otp.attempts += 1
    salt, digest = otp.code_hash.split("$", 1)
    if not secrets.compare_digest(digest, otp_digest(body.code.strip(), salt)):
        db.commit()
        left = OTP_MAX_ATTEMPTS - otp.attempts
        raise HTTPException(400, detail={
            "field": "code",
            "message": f"That code is wrong. {left} attempt(s) left." if left else
                       "Too many wrong codes. Request a new one."})
    otp.consumed_at = utcnow()
    user.email_verified_at = utcnow()

    from app.routes.staff_signup import on_email_verified

    staff_message = on_email_verified(db, user)
    prof = _profile(db, user.id)
    if prof is not None and prof.status == StudentStatus.PENDING.value:
        notify(db, responsible_staff(db, prof), "registration_pending",
               "New student registration",
               f"{user.display_name} ({prof.roll_number}) registered for "
               f"{section_label(prof.section) if prof.section else 'your class'} and is waiting "
               f"for approval.", link="/staff/approvals", email=True)
    audit(db, user, "email_verified", target_type="user", target_id=user.id, request=request)
    db.commit()
    if staff_message:
        return {"verified": True, "portal": "authority", "message": staff_message}
    return {"verified": True,
            "message": "Email verified. You can sign in; a teacher will approve your account."}


class EmailIn(BaseModel):
    email: str


@router.post("/auth/resend-otp")
def resend_otp(body: EmailIn, request: Request, db: Session = Depends(get_db)):
    enforce(request, "otp")
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.strip().lower(),
                                         User.deleted_at.is_(None))).first()
    # Same answer whether or not the address exists: no account enumeration.
    generic = {"sent": True, "message": "If that address is waiting for verification, a new "
                                        "code is on its way."}
    if user is None or user.email_verified_at is not None:
        return generic
    last = db.scalars(select(EmailOtp).where(EmailOtp.user_id == user.id)
                      .order_by(EmailOtp.created_at.desc())).first()
    if last is not None and utcnow() - last.created_at < OTP_RESEND_COOLDOWN:
        wait = int((OTP_RESEND_COOLDOWN - (utcnow() - last.created_at)).total_seconds()) + 1
        raise HTTPException(429, f"Wait {wait} seconds before requesting another code.")
    issue_otp(db, user)
    db.commit()
    return generic


# ---------------------------------------------------------------- passwords

@router.post("/auth/forgot-password")
def forgot_password(body: EmailIn, request: Request, db: Session = Depends(get_db)):
    enforce(request, "password_reset")
    user = db.scalars(select(User).where(func.lower(User.email) == body.email.strip().lower(),
                                         User.deleted_at.is_(None),
                                         User.is_active.is_(True))).first()
    if user is not None:
        token = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(user_id=user.id, token_hash=token_digest(token),
                                  expires_at=utcnow() + RESET_TTL))
        link = f"/reset-password?token={token}"
        notify(db, [user.id], "password_reset", "Reset your password",
               "Someone (hopefully you) asked to reset your attendance portal password. "
               "The link below works once, for 30 minutes. If it was not you, ignore this email.",
               link=link, email=True, sensitive=True)
        audit(db, user, "password_reset_requested", target_type="user", target_id=user.id,
              request=request)
        db.commit()
    return {"sent": True, "message": "If that email is registered, a reset link is on its way."}


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str


@router.post("/auth/reset-password")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    enforce(request, "password_reset")
    row = db.scalars(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_digest(body.token))).first()
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        raise HTTPException(400, detail={"field": "token",
                                         "message": "This reset link is invalid or has expired. "
                                                    "Request a new one."})
    try:
        pw = V.password(body.password)
    except V.Invalid as exc:
        raise _invalid(exc)
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(pw)
    user.password_changed_at = utcnow()
    user.failed_logins, user.locked_until = 0, None
    row.used_at = utcnow()
    for other in db.scalars(select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))):
        other.used_at = utcnow()
    # Proving control of the inbox also proves the email address.
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    notify(db, [user.id], "password_changed", "Your password was changed",
           "Your password was reset. If this was not you, contact the administrator now.",
           email=True)
    audit(db, user, "password_reset", target_type="user", target_id=user.id, request=request)
    db.commit()
    return {"reset": True, "message": "Password updated. Sign in with your new password."}


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/me/password")
def change_password(body: ChangePasswordIn, request: Request, db: Session = Depends(get_db),
                    actor: User = Depends(current_user)):
    enforce(request, "login", key=str(actor.id))
    if not verify_password(body.current_password, actor.password_hash):
        raise HTTPException(400, detail={"field": "current_password",
                                         "message": "Your current password is not correct."})
    try:
        pw = V.password(body.new_password, "new_password")
    except V.Invalid as exc:
        raise _invalid(exc)
    if verify_password(pw, actor.password_hash):
        raise HTTPException(422, detail={"field": "new_password",
                                         "message": "Choose a password different from the current one."})
    actor.password_hash = hash_password(pw)
    actor.password_changed_at = utcnow()
    notify(db, [actor.id], "password_changed", "Your password was changed",
           "Your password was changed from your profile. Other devices have been signed out.",
           email=True)
    audit(db, actor, "password_changed", target_type="user", target_id=actor.id, request=request)
    db.commit()
    return {"changed": True, "message": "Password changed. Sign in again on your other devices."}


# ------------------------------------------------------------------ profile

def profile_out(db: Session, user: User, prof: Optional[StudentProfile]) -> dict:
    pending = None
    if prof is not None:
        req = db.scalars(select(ProfileEditRequest).where(
            ProfileEditRequest.user_id == user.id,
            ProfileEditRequest.status == ReviewStatus.PENDING.value)).first()
        if req is not None:
            pending = {"id": req.id, "changes": json.loads(req.changes), "reason": req.reason,
                       "created_at": req.created_at}
    sec = prof.section if prof else None
    return {
        "id": user.id, "username": user.username, "full_name": user.display_name,
        "email": user.email, "email_verified": user.email_verified_at is not None,
        "phone": user.phone, "role": user.role.value if isinstance(user.role, Role) else user.role,
        "consent_given": user.consent_given, "has_biometrics": user.has_biometrics,
        "created_at": user.created_at,
        "student": None if prof is None else {
            "status": prof.status, "rejection_reason": prof.rejection_reason,
            "roll_number": prof.roll_number or user.roll_number,
            "enrollment_no": prof.enrollment_no,
            "department_id": prof.department_id or (sec.program.department_id if sec else None),
            "department": prof.department.code if prof.department else
            (sec.program.department.code if sec else None),
            "batch_id": prof.batch_id, "batch": prof.batch.label if prof.batch else None,
            "year": prof.year or (sec.year if sec else None),
            "section_id": prof.section_id, "section": section_label(sec) if sec else None,
            "dob": prof.dob.isoformat() if prof.dob else None, "gender": prof.gender,
            "guardian_name": prof.guardian_name, "guardian_phone": prof.guardian_phone,
            "guardian_email": prof.guardian_email, "address": prof.address,
            "photo_url": f"/api/files/{prof.photo_file_id}" if prof.photo_file_id else None,
            "locked_fields": list(LOCKED) if prof.status == StudentStatus.APPROVED.value else [],
            "pending_edit_request": pending,
        },
    }


@router.get("/me/profile")
def my_profile(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    return profile_out(db, actor, _profile(db, actor.id))


class ProfileIn(BaseModel):
    phone: Optional[str] = None
    address: Optional[str] = None
    guardian_name: Optional[str] = None
    guardian_phone: Optional[str] = None
    guardian_email: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[str] = None
    # Editable only before approval (or after a rejection, to fix and resubmit).
    full_name: Optional[str] = None
    roll_number: Optional[str] = None
    enrollment_no: Optional[str] = None
    department_id: Optional[int] = None
    batch_id: Optional[int] = None
    year: Optional[int] = None
    section_id: Optional[int] = None


def _clean_self(changes: dict) -> dict:
    out: Dict[str, object] = {}
    try:
        if "phone" in changes:
            out["phone"] = V.phone(changes["phone"])
        if "address" in changes:
            out["address"] = V.text(changes["address"], "address", 500, required=True, min_len=5)
        if "guardian_name" in changes:
            out["guardian_name"] = V.name(changes["guardian_name"], "guardian_name")
        if "guardian_phone" in changes:
            out["guardian_phone"] = V.phone(changes["guardian_phone"], "guardian_phone")
        if "guardian_email" in changes:
            out["guardian_email"] = V.email(changes["guardian_email"], "guardian_email",
                                            required=False)
        if "gender" in changes:
            out["gender"] = V.gender(changes["gender"])
        if "dob" in changes:
            out["dob"] = V.dob(changes["dob"])
        if "full_name" in changes:
            out["full_name"] = V.name(changes["full_name"])
        if "roll_number" in changes:
            out["roll_number"] = V.roll(changes["roll_number"])
        if "enrollment_no" in changes:
            out["enrollment_no"] = V.text(changes["enrollment_no"], "enrollment_no", 48,
                                          required=True)
    except V.Invalid as exc:
        raise _invalid(exc)
    for k in ("department_id", "batch_id", "year", "section_id"):
        if k in changes:
            out[k] = int(changes[k])
    return out


def apply_profile_changes(db: Session, user: User, prof: StudentProfile, clean: dict) -> dict:
    """Write validated changes, re-checking uniqueness and class consistency. Returns a diff."""
    dept = clean.get("department_id", prof.department_id)
    batch = clean.get("batch_id", prof.batch_id)
    year = clean.get("year", prof.year)
    section = clean.get("section_id", prof.section_id)
    if any(k in clean for k in ("department_id", "batch_id", "year", "section_id")):
        resolve_class(db, dept, batch, year, section)
    check_unique(db, phone=clean.get("phone"), roll=clean.get("roll_number",
                 prof.roll_number) if any(k in clean for k in ("roll_number", "department_id",
                                                              "batch_id")) else None,
                 department_id=dept, batch_id=batch, exclude_user=user.id)
    diff = {}
    for k, v in clean.items():
        if k == "full_name":
            old, user.display_name = user.display_name, v
        elif k == "phone":
            old, user.phone = user.phone, v
        elif k == "roll_number":
            old = prof.roll_number
            prof.roll_number = user.roll_number = v
        else:
            old = getattr(prof, k)
            setattr(prof, k, v)
        if old != v:
            diff[k] = [str(old) if old is not None else None, str(v) if v is not None else None]
    return diff


@router.patch("/me/profile")
def update_my_profile(body: ProfileIn, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(current_user)):
    prof = _profile(db, actor.id)
    changes = body.model_dump(exclude_unset=True)
    if prof is None:
        # Staff: only their own contact number.
        if set(changes) - {"phone"}:
            raise HTTPException(403, "Staff profiles are managed by an administrator.")
        clean = _clean_self(changes)
        check_unique(db, phone=clean.get("phone"), exclude_user=actor.id)
        actor.phone = clean.get("phone", actor.phone)
        db.commit()
        return profile_out(db, actor, None)

    locked = [k for k in changes if k in LOCKED]
    if locked and prof.status == StudentStatus.APPROVED.value:
        raise HTTPException(403, detail={
            "field": locked[0],
            "message": "These details are locked after approval. Submit an edit request "
                       "instead and a teacher will review it."})
    clean = _clean_self(changes)
    diff = apply_profile_changes(db, actor, prof, clean)
    if diff:
        audit(db, actor, "profile_updated", target_type="user", target_id=actor.id,
              detail=diff, request=request)
    db.commit()
    return profile_out(db, actor, prof)


@router.post("/me/photo")
async def update_photo(request: Request, photo: UploadFile = File(...),
                       db: Session = Depends(get_db), actor: User = Depends(current_user)):
    prof = _profile(db, actor.id)
    if prof is None:
        raise HTTPException(403, "Only students have a profile photo here.")
    pic = await save_upload(db, photo, owner_id=actor.id, purpose="profile_photo",
                            allowed=IMAGES, max_bytes=3 * MB)
    if prof.photo_file_id:
        from app.models import StoredFile
        delete_file(db, db.get(StoredFile, prof.photo_file_id))
    prof.photo_file_id = pic.id
    audit(db, actor, "profile_photo_changed", target_type="user", target_id=actor.id,
          request=request)
    db.commit()
    return profile_out(db, actor, prof)


@router.post("/me/resubmit")
def resubmit(request: Request, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    """A rejected student who has fixed their details asks for another review."""
    prof = _profile(db, actor.id)
    if prof is None or prof.status != StudentStatus.REJECTED.value:
        raise HTTPException(409, "Only a rejected registration can be resubmitted.")
    prof.status = StudentStatus.PENDING.value
    prof.rejection_reason = None
    notify(db, responsible_staff(db, prof), "registration_pending", "Registration resubmitted",
           f"{actor.display_name} ({prof.roll_number}) updated their details and resubmitted "
           f"their registration.", link="/staff/approvals", email=True)
    audit(db, actor, "registration_resubmitted", target_type="user", target_id=actor.id,
          request=request)
    db.commit()
    return profile_out(db, actor, prof)


# ------------------------------------------------------------ edit requests

class EditRequestIn(BaseModel):
    changes: Dict[str, object]
    reason: str = Field(min_length=5, max_length=500)


@router.post("/me/edit-requests", status_code=201)
def create_edit_request(body: EditRequestIn, request: Request, db: Session = Depends(get_db),
                        actor: User = Depends(current_user)):
    prof = _profile(db, actor.id)
    if prof is None:
        raise HTTPException(403, "Only students can request profile changes.")
    if prof.status != StudentStatus.APPROVED.value:
        raise HTTPException(409, "Your details are not locked yet — edit them directly.")
    unknown = set(body.changes) - set(LOCKED)
    if unknown:
        raise HTTPException(422, f"These fields can be edited directly: {', '.join(sorted(unknown))}")
    if not body.changes:
        raise HTTPException(422, "Say what should change.")
    if db.scalars(select(ProfileEditRequest).where(
            ProfileEditRequest.user_id == actor.id,
            ProfileEditRequest.status == ReviewStatus.PENDING.value)).first():
        raise HTTPException(409, "You already have an edit request waiting for review.")
    clean = _clean_self(body.changes)
    # Validate now so a teacher is never asked to approve something that cannot be applied.
    dept = clean.get("department_id", prof.department_id)
    batch = clean.get("batch_id", prof.batch_id)
    if any(k in clean for k in ("department_id", "batch_id", "year", "section_id")):
        resolve_class(db, dept, batch, clean.get("year", prof.year),
                      clean.get("section_id", prof.section_id))
    if any(k in clean for k in ("roll_number", "department_id", "batch_id")):
        check_unique(db, roll=clean.get("roll_number", prof.roll_number), department_id=dept,
                     batch_id=batch, exclude_user=actor.id)
    req = ProfileEditRequest(user_id=actor.id, changes=json.dumps(clean, default=str),
                             reason=body.reason.strip())
    db.add(req)
    db.flush()
    notify(db, responsible_staff(db, prof), "edit_request", "Profile edit request",
           f"{actor.display_name} ({prof.roll_number}) asked to change "
           f"{', '.join(sorted(clean))}.", link="/staff/approvals", email=False)
    audit(db, actor, "edit_request_created", target_type="profile_edit_request",
          target_id=req.id, detail=clean, request=request)
    db.commit()
    return {"id": req.id, "status": req.status}


@router.get("/me/edit-requests")
def my_edit_requests(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    rows = db.scalars(select(ProfileEditRequest).where(ProfileEditRequest.user_id == actor.id)
                      .order_by(ProfileEditRequest.created_at.desc()))
    return [{"id": r.id, "changes": json.loads(r.changes), "reason": r.reason,
             "status": r.status, "remark": r.remark, "created_at": r.created_at,
             "decided_at": r.decided_at} for r in rows]


@router.delete("/me/edit-requests/{request_id}")
def cancel_edit_request(request_id: int, db: Session = Depends(get_db),
                        actor: User = Depends(current_user)):
    r = db.get(ProfileEditRequest, request_id)
    if r is None or r.user_id != actor.id:
        raise HTTPException(404, "request not found")
    if r.status != ReviewStatus.PENDING.value:
        raise HTTPException(409, "Only a pending request can be withdrawn.")
    db.delete(r)
    db.commit()
    return {"deleted": request_id}
