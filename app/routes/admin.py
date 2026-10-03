"""Administration: staff accounts and roles, runtime settings, and the audit log.

Role changes are the most sensitive writes in the system, so:
  * only a super admin may create or promote to admin/super_admin;
  * an HOD may create and manage teachers inside their own branch only;
  * nobody can demote or disable themselves (no locking the last admin out by accident);
  * every change lands in the audit log with old and new values.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import settings_service
from app import validation as V
from app.audit import audit
from app.auth import is_super_admin, require_admin, require_staff
from app.crypto import hash_password, token_digest
from app.db import get_db
from app.models import AuditLog, Department, PasswordResetToken, Role, User, utcnow
from app.notify import notify
from app.routes.accounts import _username_for, check_unique
from app.runtime import cfg

router = APIRouter(prefix="/api", tags=["admin"])

STAFF = ("faculty", "admin", "super_admin")
INVITE_TTL = timedelta(days=7)


def _role(u: User) -> str:
    return u.role.value if isinstance(u.role, Role) else str(u.role)


def _staff_out(db: Session, u: User) -> dict:
    dept = db.get(Department, u.department_id) if u.department_id else None
    return {"id": u.id, "username": u.username, "full_name": u.display_name, "email": u.email,
            "phone": u.phone, "role": _role(u), "department_id": u.department_id,
            "department": dept.code if dept else None, "is_active": u.is_active,
            "last_login_at": u.last_login_at, "created_at": u.created_at,
            "locked": bool(u.locked_until and u.locked_until > utcnow())}


def _guard_target(actor: User, role: str, department_id: Optional[int]) -> None:
    if is_super_admin(actor):
        return
    if role != "faculty":
        raise HTTPException(403, "Only an administrator can create or promote HODs and admins.")
    if department_id != actor.department_id:
        raise HTTPException(403, "You can only manage teachers in your own branch.")


# ---------------------------------------------------------------- staff users

@router.get("/admin/users")
def list_staff(role: Optional[str] = None, q: Optional[str] = None,
               department_id: Optional[int] = None, include_inactive: bool = False,
               db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Staff directory. Teachers may read it (to pick a colleague when messaging or assigning);
    only admins see inactive accounts."""
    stmt = select(User).where(User.role.in_(STAFF), User.deleted_at.is_(None))
    if role:
        stmt = stmt.where(User.role == role)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), User.email.ilike(like),
                              User.username.ilike(like)))
    if not (include_inactive and _role(actor) in ("admin", "super_admin")):
        stmt = stmt.where(User.is_active.is_(True))
    return [_staff_out(db, u) for u in db.scalars(stmt.order_by(User.display_name))]


class StaffIn(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    role: str = "faculty"
    department_id: Optional[int] = None


@router.post("/admin/users", status_code=201)
def create_staff(body: StaffIn, request: Request, db: Session = Depends(get_db),
                 actor: User = Depends(require_admin)):
    if body.role not in STAFF:
        raise HTTPException(422, detail={"field": "role", "message": "Choose teacher, HOD or admin."})
    try:
        name = V.name(body.full_name)
        email = V.email(body.email)
        phone = V.phone(body.phone, required=False)
    except V.Invalid as exc:
        raise HTTPException(422, detail={"field": exc.field, "message": exc.message})
    dept_id = body.department_id
    if body.role in ("faculty", "admin") and dept_id is None:
        raise HTTPException(422, detail={"field": "department_id",
                                         "message": "Teachers and HODs belong to a branch."})
    if dept_id is not None and db.get(Department, dept_id) is None:
        raise HTTPException(404, "branch not found")
    _guard_target(actor, body.role, dept_id)
    check_unique(db, email=email, phone=phone)

    u = User(username=_username_for(db, email), display_name=name, email=email, phone=phone,
             role=Role(body.role), department_id=dept_id if body.role != "super_admin" else None,
             password_hash=hash_password(secrets.token_urlsafe(24)),
             email_verified_at=None)
    db.add(u)
    db.flush()
    token = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(user_id=u.id, token_hash=token_digest(token),
                              expires_at=utcnow() + INVITE_TTL))
    notify(db, [u.id], "account_invite", "Your attendance portal account",
           f"{actor.display_name} created a {body.role.replace('_', ' ')} account for you. Use "
           f"the link below to set your password (valid for 7 days).",
           link=f"/reset-password?token={token}", email=True, sensitive=True)
    audit(db, actor, "staff_created", target_type="user", target_id=u.id,
          detail={"role": body.role, "department_id": dept_id}, request=request)
    db.commit()
    return _staff_out(db, u)


class StaffUpdateIn(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    department_id: Optional[int] = None
    is_active: Optional[bool] = None


@router.patch("/admin/users/{user_id}")
def update_staff(user_id: int, body: StaffUpdateIn, request: Request,
                 db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None or u.deleted_at is not None or _role(u) not in STAFF:
        raise HTTPException(404, "staff account not found")
    _guard_target(actor, _role(u), u.department_id)
    changes = body.model_dump(exclude_unset=True)
    new_role = changes.get("role", _role(u))
    new_dept = changes.get("department_id", u.department_id)
    if new_role not in STAFF:
        raise HTTPException(422, detail={"field": "role", "message": "Unknown role."})
    _guard_target(actor, new_role, new_dept)
    if u.id == actor.id and (new_role != _role(u) or changes.get("is_active") is False):
        raise HTTPException(409, "You cannot change your own role or disable your own account.")
    if new_role in ("faculty", "admin") and new_dept is None:
        raise HTTPException(422, detail={"field": "department_id",
                                         "message": "Teachers and HODs belong to a branch."})
    if (_role(u) == "super_admin" and new_role != "super_admin") or \
            (_role(u) == "super_admin" and changes.get("is_active") is False):
        others = db.scalar(select(func.count()).select_from(User).where(
            User.role == "super_admin", User.is_active.is_(True), User.id != u.id,
            User.deleted_at.is_(None))) or 0
        if not others:
            raise HTTPException(409, "This is the last active administrator.")

    diff = {}
    if "full_name" in changes:
        try:
            v = V.name(changes["full_name"])
        except V.Invalid as exc:
            raise HTTPException(422, detail={"field": exc.field, "message": exc.message})
        diff["full_name"] = [u.display_name, v]
        u.display_name = v
    if "phone" in changes:
        try:
            v = V.phone(changes["phone"], required=False)
        except V.Invalid as exc:
            raise HTTPException(422, detail={"field": exc.field, "message": exc.message})
        check_unique(db, phone=v, exclude_user=u.id)
        diff["phone"] = [u.phone, v]
        u.phone = v
    if new_role != _role(u):
        diff["role"] = [_role(u), new_role]
        u.role = Role(new_role)
    if new_dept != u.department_id:
        diff["department_id"] = [u.department_id, new_dept]
        u.department_id = new_dept if new_role != "super_admin" else None
    if "is_active" in changes and changes["is_active"] != u.is_active:
        diff["is_active"] = [u.is_active, changes["is_active"]]
        u.is_active = bool(changes["is_active"])
    if diff:
        audit(db, actor, "role_changed" if "role" in diff else "staff_updated",
              target_type="user", target_id=u.id, detail=diff, request=request)
        if "role" in diff:
            notify(db, [u.id], "role_changed", "Your role changed",
                   f"Your role is now {new_role.replace('_', ' ')}.", email=True)
    db.commit()
    return _staff_out(db, u)


@router.post("/admin/users/{user_id}/unlock")
def unlock_user(user_id: int, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "user not found")
    if not is_super_admin(actor) and u.department_id != actor.department_id:
        from app.scope import can_manage_student

        if not can_manage_student(db, actor, u.id):
            raise HTTPException(403, "outside your branch")
    u.locked_until, u.failed_logins = None, 0
    audit(db, actor, "account_unlocked", target_type="user", target_id=u.id, request=request)
    db.commit()
    return {"unlocked": u.id}


# ------------------------------------------------------------------ settings

@router.get("/admin/settings")
def get_settings(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    """Readable by all staff (teachers need the time windows); editable by super admins."""
    from app.mailer import delivery_mode

    return {"values": settings_service.all_settings(db, cfg),
            "fields": settings_service.describe(),
            "email_delivery": delivery_mode()}


@router.patch("/admin/settings")
def update_settings(changes: dict, request: Request, db: Session = Depends(get_db),
                    actor: User = Depends(require_admin)):
    if not is_super_admin(actor):
        raise HTTPException(403, "Only an administrator can change system settings.")
    try:
        diff = settings_service.update(db, cfg, changes, actor.id)
    except settings_service.SettingsError as exc:
        raise HTTPException(422, str(exc))
    if diff:
        audit(db, actor, "settings_changed", target_type="settings",
              detail={k: [old, new] for k, (old, new) in diff.items()}, request=request)
    db.commit()
    settings_service.invalidate()
    return {"values": settings_service.all_settings(db, cfg), "changed": sorted(diff)}


# ----------------------------------------------------------------- audit log

@router.get("/admin/audit")
def audit_log(action: Optional[str] = None, actor_id: Optional[int] = None,
              target_type: Optional[str] = None, target_id: Optional[str] = None,
              date_from: Optional[str] = None, date_to: Optional[str] = None,
              q: Optional[str] = None, page: int = 1, page_size: int = 50,
              db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not is_super_admin(actor):
        raise HTTPException(403, "Only an administrator can read the audit log.")
    stmt = select(AuditLog, User).outerjoin(User, User.id == AuditLog.actor_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if target_id:
        stmt = stmt.where(AuditLog.target_id == target_id)
    try:
        if date_from:
            stmt = stmt.where(AuditLog.at >= datetime.fromisoformat(date_from + "T00:00:00+00:00"))
        if date_to:
            stmt = stmt.where(AuditLog.at <= datetime.fromisoformat(date_to + "T23:59:59+00:00"))
    except ValueError:
        raise HTTPException(422, "Dates must be YYYY-MM-DD.")
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(AuditLog.detail.ilike(like), AuditLog.reason.ilike(like),
                              AuditLog.action.ilike(like)))
    page_size = max(10, min(200, page_size))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(AuditLog.at.desc())
                      .offset((max(1, page) - 1) * page_size).limit(page_size)).all()
    actions = sorted(db.scalars(select(AuditLog.action).distinct()))
    return {
        "rows": [{"id": a.id, "at": a.at, "action": a.action,
                  "actor": u.display_name if u else "system", "actor_id": a.actor_id,
                  "target_type": a.target_type, "target_id": a.target_id,
                  "reason": a.reason, "detail": a.detail, "ip": a.ip} for a, u in rows],
        "meta": {"page": max(1, page), "page_size": page_size, "total": total,
                 "pages": (total + page_size - 1) // page_size},
        "actions": actions,
    }
