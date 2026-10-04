"""Staff self-registration: the authority "register" form, and the queue that approves it.

Anyone can fill in a form, so a registration grants nothing by itself:

  * the account is created inactive (no sign-in) and must verify its email first;
  * a super admin approves any request; an HOD approves *teachers* of their own branch only;
  * only a super admin can grant HOD (admin) rights — whatever the person asked for;
  * every decision is audited and the person is told by email, with the reason on rejection.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import validation as V
from app.audit import audit
from app.auth import is_super_admin, require_admin
from app.crypto import hash_password
from app.db import get_db
from app.models import Department, ReviewStatus, Role, StaffRegistration, User, utcnow
from app.notify import notify
from app.ratelimit import enforce
from app.routes.accounts import _username_for, check_unique, issue_otp

router = APIRouter(prefix="/api", tags=["staff-signup"])

REQUESTABLE = {"faculty": "Teacher", "admin": "HOD"}


def staff_approvers(db: Session, department_id: Optional[int], requested_role: str) -> List[int]:
    """Who may decide this request: super admins, plus the branch's HODs for a teacher."""
    conds = [User.role == Role.SUPER_ADMIN]
    if requested_role == "faculty" and department_id is not None:
        conds.append((User.role == Role.ADMIN) & (User.department_id == department_id))
    return list(db.scalars(select(User.id).where(or_(*conds), User.is_active.is_(True),
                                                 User.deleted_at.is_(None))))


def registration_for(db: Session, user_id: int) -> Optional[StaffRegistration]:
    return db.scalars(select(StaffRegistration).where(StaffRegistration.user_id == user_id)).first()


# ------------------------------------------------------------------ register

class StaffSignupIn(BaseModel):
    full_name: str
    email: str
    mobile: str
    password: str
    employee_id: str = Field(max_length=48)
    designation: Optional[str] = Field(None, max_length=80)
    department_id: int
    requested_role: str = "faculty"


@router.post("/auth/staff-signup", status_code=201)
def staff_signup(body: StaffSignupIn, request: Request, db: Session = Depends(get_db)):
    enforce(request, "signup")
    try:
        name = V.name(body.full_name)
        email = V.email(body.email)
        phone = V.phone(body.mobile)
        password = V.password(body.password)
        employee_id = V.text(body.employee_id, "employee_id", 48, required=True)
        designation = V.text(body.designation, "designation", 80, required=False)
    except V.Invalid as exc:
        raise HTTPException(422, detail={"field": exc.field, "message": exc.message})
    if body.requested_role not in REQUESTABLE:
        raise HTTPException(422, detail={"field": "requested_role", "message": "Choose Teacher or HOD."})
    if db.get(Department, body.department_id) is None:
        raise HTTPException(422, detail={"field": "department_id", "message": "Choose your branch."})
    check_unique(db, email=email, phone=phone)
    if db.scalars(select(StaffRegistration.id).where(
            func.upper(StaffRegistration.employee_id) == employee_id.upper())).first():
        raise HTTPException(409, detail={"field": "employee_id",
                                         "message": "This employee ID is already registered."})

    user = User(username=_username_for(db, email), display_name=name, email=email, phone=phone,
                role=Role.FACULTY, department_id=body.department_id, is_active=False,
                password_hash=hash_password(password))
    db.add(user)
    db.flush()
    db.add(StaffRegistration(user_id=user.id, requested_role=body.requested_role,
                             department_id=body.department_id, employee_id=employee_id,
                             designation=designation))
    issue_otp(db, user)
    audit(db, user, "staff_signup", target_type="user", target_id=user.id,
          detail={"requested_role": body.requested_role, "department_id": body.department_id,
                  "employee_id": employee_id}, request=request)
    db.commit()
    return {"email": user.email, "otp_sent": True,
            "message": "We emailed you a 6-digit code. Enter it to verify your email."}


def on_email_verified(db: Session, user: User) -> Optional[str]:
    """Called by the email-verification endpoint. Returns the message to show, or None when
    this is not a staff registration.

    With the `staff_registration_approval` setting off, a verified email is enough: the account
    is switched on as a Teacher. Asking for HOD does not grant it; a super admin gives HOD
    rights under Staff & roles.
    """
    from app import settings_service
    from app.runtime import cfg

    reg = registration_for(db, user.id)
    if reg is None or reg.status != ReviewStatus.PENDING.value:
        return None
    dept = db.get(Department, reg.department_id)
    if not settings_service.get(db, cfg, "staff_registration_approval"):
        user.is_active = True
        user.role = Role.FACULTY
        user.department_id = reg.department_id
        reg.status = ReviewStatus.APPROVED.value
        reg.decided_at = utcnow()
        audit(db, user, "staff_registration_auto_approved", target_type="user", target_id=user.id,
              detail={"requested_role": reg.requested_role, "granted_role": "faculty"})
        hod_note = (" They asked for HOD rights; give them under Staff & roles if appropriate."
                    if reg.requested_role == "admin" else "")
        notify(db, staff_approvers(db, reg.department_id, "admin"), "staff_registered",
               "New teacher registered",
               f"{user.display_name} ({reg.employee_id}) registered as a teacher in "
               f"{dept.code if dept else 'a branch'} and can now sign in.{hod_note}",
               link="/staff/admin/users", email=True)
        if reg.requested_role == "admin":
            return ("Email verified. Your teacher account is ready: sign in now. HOD rights are "
                    "given by the administrator.")
        return "Email verified. Your account is ready: sign in now."
    notify(db, staff_approvers(db, reg.department_id, reg.requested_role), "staff_registration",
           "New staff registration",
           f"{user.display_name} ({reg.employee_id}) asked for a {REQUESTABLE[reg.requested_role]} "
           f"account in {dept.code if dept else 'a branch'}.", link="/staff/approvals?tab=staff",
           email=True)
    return "Email verified. An administrator will review your request; you will get an email when it is decided."


# ------------------------------------------------------------------ approve

def _can_decide(actor: User, reg: StaffRegistration) -> bool:
    if is_super_admin(actor):
        return True
    return reg.requested_role == "faculty" and actor.department_id == reg.department_id


def _out(db: Session, reg: StaffRegistration) -> dict:
    u = db.get(User, reg.user_id)
    dept = db.get(Department, reg.department_id)
    return {"id": reg.id, "user_id": reg.user_id, "full_name": u.display_name, "email": u.email,
            "phone": u.phone, "email_verified": u.email_verified_at is not None,
            "employee_id": reg.employee_id, "designation": reg.designation,
            "requested_role": reg.requested_role, "department_id": reg.department_id,
            "department": dept.code if dept else None, "status": reg.status, "reason": reg.reason,
            "created_at": reg.created_at, "decided_at": reg.decided_at}


def scoped_registrations(db: Session, actor: User):
    stmt = select(StaffRegistration)
    if not is_super_admin(actor):
        stmt = stmt.where(StaffRegistration.requested_role == "faculty",
                          StaffRegistration.department_id == actor.department_id)
    return stmt


@router.get("/staff-registrations")
def list_registrations(status: str = "pending", db: Session = Depends(get_db),
                       actor: User = Depends(require_admin)):
    stmt = scoped_registrations(db, actor)
    if status != "all":
        stmt = stmt.where(StaffRegistration.status == status)
    return [_out(db, r) for r in db.scalars(stmt.order_by(StaffRegistration.created_at.desc()))]


class DecideIn(BaseModel):
    approve: bool
    reason: Optional[str] = Field(None, max_length=300)
    role: Optional[str] = None            # super admin only: grant a different role than asked


@router.post("/staff-registrations/{reg_id}/decide")
def decide(reg_id: int, body: DecideIn, request: Request, db: Session = Depends(get_db),
           actor: User = Depends(require_admin)):
    reg = db.get(StaffRegistration, reg_id)
    if reg is None or not _can_decide(actor, reg):
        raise HTTPException(404, "registration not found")
    if reg.status != ReviewStatus.PENDING.value:
        raise HTTPException(409, f"This request was already {reg.status}.")
    user = db.get(User, reg.user_id)

    if body.approve:
        if user.email_verified_at is None:
            raise HTTPException(409, "This person has not verified their email yet.")
        role = body.role or reg.requested_role
        if role not in REQUESTABLE:
            raise HTTPException(422, detail={"field": "role", "message": "Choose Teacher or HOD."})
        if role == "admin" and not is_super_admin(actor):
            raise HTTPException(403, "Only an administrator can grant HOD rights.")
        user.role = Role(role)
        user.department_id = reg.department_id
        user.is_active = True
        reg.status = ReviewStatus.APPROVED.value
        notify(db, [user.id], "staff_approved", "Your staff account is approved",
               f"{actor.display_name} approved your {REQUESTABLE[role]} account. You can now sign "
               f"in at the authority sign in.", link="/authority/login", email=True)
    else:
        reason = (body.reason or "").strip()
        if len(reason) < 3:
            raise HTTPException(422, detail={"field": "reason", "message": "Give a reason for the rejection."})
        reg.status = ReviewStatus.REJECTED.value
        reg.reason = reason
        notify(db, [user.id], "staff_rejected", "Your staff registration was not approved",
               f"Reason: {reason}", email=True, inapp=False)
    reg.decided_by_id = actor.id
    reg.decided_at = utcnow()
    audit(db, actor, "staff_registration_approved" if body.approve else "staff_registration_rejected",
          target_type="user", target_id=user.id,
          detail={"requested_role": reg.requested_role, "granted_role": body.role or reg.requested_role
                  if body.approve else None, "reason": reg.reason}, request=request)
    db.commit()
    return _out(db, reg)
