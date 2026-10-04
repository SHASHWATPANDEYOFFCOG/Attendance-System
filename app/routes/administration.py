"""Administration: access codes, workspaces, tablets, and the overview numbers.

Access rules live in app/resources.py (workspaces, cameras, tablets) and app/access_codes.py;
this module only exposes them. Every change is audited.
"""
from __future__ import annotations

import re
import secrets
from datetime import timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import access_codes
from app.audit import audit
from app.auth import is_super_admin, require_staff, require_super_admin
from app.crypto import token_digest
from app.db import get_db
from app.models import (
    Camera,
    CameraStatus,
    Role,
    StudentProfile,
    Tablet,
    TabletCamera,
    User,
    Workspace,
    WorkspaceMember,
    utcnow,
)
from app.notify import notify
from app.ratelimit import enforce
from app.resources import (
    assert_workspace,
    can_use_workspace,
    current_tablet,
    tablet_camera_ids,
    visible_cameras_stmt,
    workspace_ids,
)
from app.scope import student_scope_clause

router = APIRouter(prefix="/api", tags=["administration"])

STAFF_ROLES = ("faculty", "admin", "super_admin")
PAIRING_TTL = timedelta(minutes=15)
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: read off one screen, typed on another


def _role(u: User) -> str:
    return u.role.value if isinstance(u.role, Role) else str(u.role)


def _next_code(db: Session, model, prefix: str) -> str:
    n = (db.scalar(select(func.max(model.id))) or 0) + 1
    while db.scalars(select(model.id).where(model.code == f"{prefix}-{n:04d}")).first() is not None:
        n += 1
    return f"{prefix}-{n:04d}"


def _clean_code(raw: Optional[str], field: str) -> Optional[str]:
    code = (raw or "").strip().upper()
    if not code:
        return None
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{1,31}", code):
        raise HTTPException(422, detail={"field": field, "message": "Use letters, digits, - and _ (2-32 characters)."})
    return code


def _commit(db: Session, conflict: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, conflict)


# ================================================================ access codes

class CodeIn(BaseModel):
    code: str = Field(max_length=64)
    confirm: str = Field(max_length=64)


@router.get("/admin/access-codes")
def access_code_status(db: Session = Depends(get_db), _: User = Depends(require_super_admin)):
    return access_codes.status(db)


@router.put("/admin/access-codes/{kind}")
def change_access_code(kind: str, body: CodeIn, request: Request, db: Session = Depends(get_db),
                       actor: User = Depends(require_super_admin)):
    if kind not in access_codes.KINDS:
        raise HTTPException(404, "unknown access code")
    if body.code.strip() != body.confirm.strip():
        raise HTTPException(422, detail={"field": "confirm", "message": "The two entries do not match."})
    try:
        access_codes.change(db, kind, body.code, actor)
    except access_codes.AccessCodeError as exc:
        raise HTTPException(422, detail={"field": "code", "message": str(exc)})
    audit(db, actor, "access_code_changed", target_type="access_code", target_id=kind, request=request)
    db.commit()
    return access_codes.status(db)


class UnlockIn(BaseModel):
    code: str = Field(max_length=64)


@router.post("/access/administrator")
def unlock_administrator(body: UnlockIn, request: Request, db: Session = Depends(get_db),
                         actor: User = Depends(require_staff)):
    """A signed-in authority who knows the administrator code becomes an administrator."""
    enforce(request, "access_code", key=str(actor.id))
    if is_super_admin(actor):
        return {"role": "super_admin", "message": "You are already an administrator."}
    if not access_codes.verify(db, "administrator", body.code):
        audit(db, actor, "administrator_unlock_failed", target_type="user", target_id=actor.id, request=request)
        db.commit()
        raise HTTPException(403, detail={"field": "code", "message": "That administrator code is not valid."})
    previous = _role(actor)
    actor.role = Role.SUPER_ADMIN
    others = [u for u in db.scalars(select(User.id).where(
        User.role == Role.SUPER_ADMIN, User.id != actor.id, User.is_active.is_(True)))]
    notify(db, others, "administrator_added", "New administrator",
           f"{actor.display_name} became an administrator using the administrator code. If this was not "
           f"expected, change the code under Settings → Access codes and change their role under Staff & roles.",
           link="/staff/admin/users", email=True)
    audit(db, actor, "administrator_unlocked", target_type="user", target_id=actor.id,
          detail={"from": previous, "to": "super_admin"}, request=request)
    db.commit()
    return {"role": "super_admin", "message": "You are now an administrator."}


# ================================================================== workspaces

class WorkspaceIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    code: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = Field(None, max_length=300)
    location: Optional[str] = Field(None, max_length=120)
    is_active: bool = True
    member_ids: Optional[List[int]] = None


class WorkspaceUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    code: Optional[str] = Field(None, max_length=32)
    description: Optional[str] = Field(None, max_length=300)
    location: Optional[str] = Field(None, max_length=120)
    is_active: Optional[bool] = None
    member_ids: Optional[List[int]] = None


def _workspace_out(db: Session, ws: Workspace) -> dict:
    members = list(db.scalars(select(User).join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                              .where(WorkspaceMember.workspace_id == ws.id).order_by(User.display_name)))
    cams = list(db.scalars(select(Camera).where(Camera.workspace_id == ws.id).order_by(Camera.name)))
    tabs = db.scalar(select(func.count()).select_from(Tablet).where(Tablet.workspace_id == ws.id)) or 0
    return {"id": ws.id, "code": ws.code, "name": ws.name, "description": ws.description,
            "location": ws.location, "is_active": ws.is_active, "created_at": ws.created_at,
            "members": [{"id": u.id, "name": u.display_name, "email": u.email, "role": _role(u)} for u in members],
            "cameras": [{"id": c.id, "name": c.name, "code": c.code, "room": c.room} for c in cams],
            "tablets": tabs}


def _set_members(db: Session, ws: Workspace, user_ids: List[int]) -> None:
    wanted = set(user_ids)
    staff = set(db.scalars(select(User.id).where(User.id.in_(wanted or {-1}), User.role.in_(STAFF_ROLES),
                                                 User.deleted_at.is_(None))))
    if wanted - staff:
        raise HTTPException(422, detail={"field": "member_ids", "message": "Only staff accounts can be workspace members."})
    current = {m.user_id: m for m in db.scalars(select(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id))}
    for uid, m in current.items():
        if uid not in wanted:
            db.delete(m)
    for uid in wanted - set(current):
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=uid))


@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    allowed = workspace_ids(db, actor)
    stmt = select(Workspace).order_by(Workspace.name)
    if allowed is not None:
        stmt = stmt.where(Workspace.id.in_(allowed or {-1}))
    return [_workspace_out(db, w) for w in db.scalars(stmt)]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(require_super_admin)):
    ws = Workspace(name=body.name.strip(), code=_clean_code(body.code, "code") or _next_code(db, Workspace, "WS"),
                   description=(body.description or "").strip() or None,
                   location=(body.location or "").strip() or None, is_active=body.is_active)
    db.add(ws)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A workspace with that name or ID already exists.")
    if body.member_ids:
        _set_members(db, ws, body.member_ids)
    audit(db, actor, "workspace_created", target_type="workspace", target_id=ws.id,
          detail={"name": ws.name, "members": body.member_ids or []}, request=request)
    _commit(db, "A workspace with that name or ID already exists.")
    return _workspace_out(db, ws)


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: int, body: WorkspaceUpdateIn, request: Request,
                     db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Members may edit the details; only an administrator changes the ID, status or members."""
    ws = assert_workspace(db, actor, workspace_id)
    changes = body.model_dump(exclude_unset=True)
    admin_only = {"code", "is_active", "member_ids"} & set(changes)
    if admin_only and not is_super_admin(actor):
        raise HTTPException(403, "Only an administrator can change a workspace's ID, status or members.")
    if body.name is not None:
        ws.name = body.name.strip()
    if "description" in changes:
        ws.description = (body.description or "").strip() or None
    if "location" in changes:
        ws.location = (body.location or "").strip() or None
    if body.code is not None:
        ws.code = _clean_code(body.code, "code") or ws.code
    if body.is_active is not None:
        ws.is_active = body.is_active
    if body.member_ids is not None:
        _set_members(db, ws, body.member_ids)
    audit(db, actor, "workspace_updated", target_type="workspace", target_id=ws.id, detail=changes, request=request)
    _commit(db, "A workspace with that name or ID already exists.")
    return _workspace_out(db, ws)


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: int, request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(require_super_admin)):
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "workspace not found")
    tablets = db.scalar(select(func.count()).select_from(Tablet).where(Tablet.workspace_id == ws.id)) or 0
    if tablets:
        raise HTTPException(409, f"{ws.name} still has {tablets} tablet(s). Remove or move them first.")
    for cam in db.scalars(select(Camera).where(Camera.workspace_id == ws.id)):
        cam.workspace_id = None                       # cameras fall back to administrator-only
    name = ws.name
    db.delete(ws)
    audit(db, actor, "workspace_deleted", target_type="workspace", target_id=workspace_id,
          detail={"name": name}, request=request)
    db.commit()
    return {"deleted": workspace_id}


# ===================================================================== tablets

class TabletIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    workspace_id: int
    code: Optional[str] = Field(None, max_length=32)
    camera_ids: List[int] = []


class TabletUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=80)
    workspace_id: Optional[int] = None
    status: Optional[str] = None          # active | disabled (revoke has its own endpoint)


def _tablet_out(db: Session, t: Tablet) -> dict:
    ws = db.get(Workspace, t.workspace_id)
    owner = db.get(User, t.owner_id)
    cams = list(db.scalars(select(Camera).join(TabletCamera, TabletCamera.camera_id == Camera.id)
                           .where(TabletCamera.tablet_id == t.id).order_by(Camera.name)))
    return {"id": t.id, "code": t.code, "name": t.name, "status": t.status,
            "workspace_id": t.workspace_id, "workspace": ws.name if ws else None,
            "owner": owner.display_name if owner else None, "owner_id": t.owner_id,
            "paired": t.device_token_hash is not None, "device_info": t.device_info,
            "paired_at": t.paired_at, "last_seen_at": t.last_seen_at, "created_at": t.created_at,
            "pairing_pending": bool(t.pairing_code_hash and t.pairing_expires_at and t.pairing_expires_at > utcnow()),
            "cameras": [{"id": c.id, "name": c.name, "code": c.code} for c in cams]}


def _tablet(db: Session, actor: User, tablet_id: int) -> Tablet:
    t = db.get(Tablet, tablet_id)
    if t is None or not can_use_workspace(db, actor, t.workspace_id):
        raise HTTPException(404, "tablet not found")
    return t


def _set_tablet_cameras(db: Session, t: Tablet, camera_ids: List[int]) -> None:
    wanted = set(camera_ids)
    ok = set(db.scalars(select(Camera.id).where(Camera.id.in_(wanted or {-1}), Camera.workspace_id == t.workspace_id)))
    if wanted - ok:
        raise HTTPException(422, detail={"field": "camera_ids",
                                         "message": "A tablet can only use cameras of its own workspace."})
    for link in db.scalars(select(TabletCamera).where(TabletCamera.tablet_id == t.id)):
        if link.camera_id not in wanted:
            db.delete(link)
    have = tablet_camera_ids(db, t)
    for cid in wanted - have:
        db.add(TabletCamera(tablet_id=t.id, camera_id=cid))


def _issue_pairing(t: Tablet) -> str:
    code = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(8))
    t.pairing_code_hash = token_digest(code)
    t.pairing_expires_at = utcnow() + PAIRING_TTL
    return code


@router.get("/tablets")
def list_tablets(db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    allowed = workspace_ids(db, actor)
    stmt = select(Tablet).order_by(Tablet.name)
    if allowed is not None:
        stmt = stmt.where(Tablet.workspace_id.in_(allowed or {-1}))
    return [_tablet_out(db, t) for t in db.scalars(stmt)]


@router.post("/tablets", status_code=201)
def create_tablet(body: TabletIn, request: Request, db: Session = Depends(get_db),
                  actor: User = Depends(require_staff)):
    ws = assert_workspace(db, actor, body.workspace_id)
    if not ws.is_active:
        raise HTTPException(409, f"{ws.name} is deactivated.")
    t = Tablet(name=body.name.strip(), workspace_id=ws.id, owner_id=actor.id, status="pending",
               code=_clean_code(body.code, "code") or _next_code(db, Tablet, "TAB"))
    db.add(t)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A tablet with that ID already exists.")
    _set_tablet_cameras(db, t, body.camera_ids)
    pairing = _issue_pairing(t)
    audit(db, actor, "tablet_registered", target_type="tablet", target_id=t.id,
          detail={"name": t.name, "workspace_id": ws.id, "cameras": body.camera_ids}, request=request)
    _commit(db, "A tablet with that ID already exists.")
    return {**_tablet_out(db, t), "pairing_code": pairing, "pairing_expires_at": t.pairing_expires_at}


@router.patch("/tablets/{tablet_id}")
def update_tablet(tablet_id: int, body: TabletUpdateIn, request: Request, db: Session = Depends(get_db),
                  actor: User = Depends(require_staff)):
    t = _tablet(db, actor, tablet_id)
    changes = body.model_dump(exclude_unset=True)
    if body.name is not None:
        t.name = body.name.strip()
    if body.workspace_id is not None and body.workspace_id != t.workspace_id:
        assert_workspace(db, actor, body.workspace_id)
        t.workspace_id = body.workspace_id
        _set_tablet_cameras(db, t, [])               # cameras belong to the old workspace
    if body.status is not None:
        if body.status not in ("active", "disabled"):
            raise HTTPException(422, detail={"field": "status", "message": "Choose enabled or disabled."})
        if t.status == "revoked":
            raise HTTPException(409, "This tablet was revoked. Issue a new pairing code to use it again.")
        if body.status == "active" and t.device_token_hash is None:
            raise HTTPException(409, "Pair the tablet first (enter its pairing code on the device).")
        t.status = body.status
    audit(db, actor, "tablet_updated", target_type="tablet", target_id=t.id, detail=changes, request=request)
    db.commit()
    return _tablet_out(db, t)


class CameraIdsIn(BaseModel):
    camera_ids: List[int]


@router.put("/tablets/{tablet_id}/cameras")
def set_tablet_cameras(tablet_id: int, body: CameraIdsIn, request: Request, db: Session = Depends(get_db),
                       actor: User = Depends(require_staff)):
    t = _tablet(db, actor, tablet_id)
    _set_tablet_cameras(db, t, body.camera_ids)
    audit(db, actor, "tablet_cameras_changed", target_type="tablet", target_id=t.id,
          detail={"cameras": body.camera_ids}, request=request)
    db.commit()
    return _tablet_out(db, t)


@router.post("/tablets/{tablet_id}/pairing-code")
def new_pairing_code(tablet_id: int, request: Request, db: Session = Depends(get_db),
                     actor: User = Depends(require_staff)):
    """A fresh one-time code. Re-pairing replaces the device: the old one stops working."""
    t = _tablet(db, actor, tablet_id)
    code = _issue_pairing(t)
    t.device_token_hash = None
    t.status = "pending"
    audit(db, actor, "tablet_pairing_code_issued", target_type="tablet", target_id=t.id, request=request)
    db.commit()
    return {**_tablet_out(db, t), "pairing_code": code, "pairing_expires_at": t.pairing_expires_at}


@router.post("/tablets/{tablet_id}/revoke")
def revoke_tablet(tablet_id: int, request: Request, db: Session = Depends(get_db),
                  actor: User = Depends(require_staff)):
    t = _tablet(db, actor, tablet_id)
    t.status = "revoked"
    t.device_token_hash = None
    t.pairing_code_hash = None
    audit(db, actor, "tablet_revoked", target_type="tablet", target_id=t.id, request=request)
    db.commit()
    return _tablet_out(db, t)


@router.delete("/tablets/{tablet_id}")
def delete_tablet(tablet_id: int, request: Request, db: Session = Depends(get_db),
                  actor: User = Depends(require_staff)):
    t = _tablet(db, actor, tablet_id)
    name = t.name
    db.delete(t)
    audit(db, actor, "tablet_removed", target_type="tablet", target_id=tablet_id, detail={"name": name}, request=request)
    db.commit()
    return {"deleted": tablet_id}


class PairIn(BaseModel):
    pairing_code: str = Field(max_length=16)
    device_info: Optional[str] = Field(None, max_length=200)


@router.post("/tablets/pair")
def pair_tablet(body: PairIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_staff)):
    """Called from the tablet itself, by a signed-in authority of the tablet's workspace."""
    enforce(request, "access_code", key=str(actor.id))
    code = re.sub(r"[\s-]", "", body.pairing_code).upper()
    t = db.scalars(select(Tablet).where(Tablet.pairing_code_hash == token_digest(code))).first()
    if t is None or t.pairing_expires_at is None or t.pairing_expires_at < utcnow():
        raise HTTPException(400, detail={"field": "pairing_code",
                                         "message": "That pairing code is wrong or has expired. Issue a new one."})
    if not can_use_workspace(db, actor, t.workspace_id):
        raise HTTPException(403, "You are not a member of this tablet's workspace.")
    token = secrets.token_urlsafe(32)
    t.device_token_hash = token_digest(token)
    t.pairing_code_hash = None
    t.pairing_expires_at = None
    t.status = "active"
    t.paired_at = t.last_seen_at = utcnow()
    t.device_info = (body.device_info or "")[:200] or None
    audit(db, actor, "tablet_paired", target_type="tablet", target_id=t.id, request=request)
    db.commit()
    return {"device_token": token, "tablet": _tablet_out(db, t)}


@router.get("/tablets/this-device")
def this_device(request: Request, db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    t = current_tablet(request, db)
    db.commit()
    if t is None:
        return {"paired": False}
    return {"paired": True, "usable": can_use_workspace(db, actor, t.workspace_id), "tablet": _tablet_out(db, t)}


# ==================================================================== overview

@router.get("/admin/overview")
def overview(db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    """Dashboard numbers: everything for an administrator, own workspaces and students otherwise."""
    from app.worker import registry

    cams = list(db.scalars(visible_cameras_stmt(db, actor)))

    def state(c: Camera) -> str:
        if not c.enabled:
            return "disabled"
        st = c.status.value if isinstance(c.status, CameraStatus) else str(c.status)
        if st == "starting":
            return "connecting"
        if st in ("offline", "error"):
            return "offline"
        return "online" if registry.is_running(c.id) else "idle"

    states = [state(c) for c in cams]
    allowed = workspace_ids(db, actor)
    tab_stmt = select(Tablet)
    ws_stmt = select(Workspace).where(Workspace.is_active.is_(True))
    if allowed is not None:
        tab_stmt = tab_stmt.where(Tablet.workspace_id.in_(allowed or {-1}))
        ws_stmt = ws_stmt.where(Workspace.id.in_(allowed or {-1}))
    tablets = list(db.scalars(tab_stmt))
    students = dict(db.execute(
        select(StudentProfile.status, func.count()).join(User, User.id == StudentProfile.user_id)
        .where(User.deleted_at.is_(None), student_scope_clause(db, actor))
        .group_by(StudentProfile.status)).all())
    out = {
        "cameras": {"total": len(cams), **{k: states.count(k) for k in ("online", "offline", "connecting", "idle", "disabled")}},
        "tablets": {"total": len(tablets), "active": sum(t.status == "active" for t in tablets)},
        "workspaces": len(list(db.scalars(ws_stmt))),
        "students": {k: students.get(k, 0) for k in ("pending", "approved", "rejected", "revoked")},
        "is_administrator": is_super_admin(actor),
    }
    if is_super_admin(actor):
        staff = list(db.scalars(select(User).where(User.role.in_(STAFF_ROLES), User.deleted_at.is_(None))))
        out["authorities"] = {"total": len(staff), "active": sum(u.is_active for u in staff)}
    return out
