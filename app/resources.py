"""Who may use which workspace, camera and tablet. The single source of truth, used by every
endpoint that touches them (the UI only mirrors it).

    administrator (super admin)  everything
    authority (teacher / HOD)    the workspaces they are a member of, the cameras in those
                                 workspaces, and the tablets registered to those workspaces
    tablet                       a request that carries a paired device token is additionally
                                 limited to the cameras assigned to that tablet

A camera with no workspace is administrator-only.
"""
from __future__ import annotations

from typing import Optional, Set

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import is_super_admin
from app.crypto import token_digest
from app.models import Camera, Tablet, TabletCamera, User, Workspace, WorkspaceMember, utcnow

DEVICE_HEADER = "X-Device-Token"


def workspace_ids(db: Session, user: User) -> Optional[Set[int]]:
    """Workspaces the user may use; None means all (administrator). Inactive ones are excluded."""
    if is_super_admin(user):
        return None
    return set(db.scalars(
        select(WorkspaceMember.workspace_id)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user.id, Workspace.is_active.is_(True))))


def can_use_workspace(db: Session, user: User, workspace_id: Optional[int]) -> bool:
    if workspace_id is None:
        return is_super_admin(user)
    allowed = workspace_ids(db, user)
    return allowed is None or workspace_id in allowed


def assert_workspace(db: Session, user: User, workspace_id: Optional[int]) -> Workspace:
    ws = db.get(Workspace, workspace_id) if workspace_id else None
    if ws is None or not can_use_workspace(db, user, ws.id):
        raise HTTPException(404, "workspace not found")
    return ws


# ------------------------------------------------------------------ tablets

def current_tablet(request: Request, db: Session) -> Optional[Tablet]:
    """The paired tablet this request comes from (device token header), if any and active."""
    token = request.headers.get(DEVICE_HEADER)
    if not token:
        return None
    tab = db.scalars(select(Tablet).where(Tablet.device_token_hash == token_digest(token))).first()
    if tab is None or tab.status != "active":
        return None
    tab.last_seen_at = utcnow()
    return tab


def tablet_camera_ids(db: Session, tablet: Tablet) -> Set[int]:
    return set(db.scalars(select(TabletCamera.camera_id).where(TabletCamera.tablet_id == tablet.id)))


def tablet_usable_by(db: Session, user: User, tablet: Tablet) -> bool:
    return tablet.status == "active" and can_use_workspace(db, user, tablet.workspace_id)


# ------------------------------------------------------------------ cameras

def camera_visible(db: Session, user: User, cam: Camera, tablet: Optional[Tablet] = None) -> bool:
    if not can_use_workspace(db, user, cam.workspace_id):
        return False
    if tablet is not None and not is_super_admin(user):
        return cam.id in tablet_camera_ids(db, tablet)
    return True


def visible_cameras_stmt(db: Session, user: User):
    stmt = select(Camera)
    allowed = workspace_ids(db, user)
    if allowed is not None:
        stmt = stmt.where(Camera.workspace_id.in_(allowed or {-1}))
    return stmt
