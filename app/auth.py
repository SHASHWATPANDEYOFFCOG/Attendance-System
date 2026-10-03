"""JWT authentication and role scoping.

Authorization is enforced **server-side, in the query**. The dashboard never receives rows the
signed-in user is not entitled to see; there is no client-side filtering to bypass. A student
token cannot read another student's records and cannot open the live stream at all.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.db import get_db
from app.models import ClassSession, FacultyAssignment, Role, StudentProfile, User

_SECRET_ENV = "ATTENDANCE_JWT_SECRET"
_ENV_ENV = "ATTENDANCE_ENV"
ALGORITHM = "HS256"
ACCESS_TTL = timedelta(minutes=30)
REFRESH_TTL = timedelta(days=7)

_bearer = HTTPBearer(auto_error=False)
_secret_cache: Optional[str] = None


def _secret() -> str:
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    val = os.environ.get(_SECRET_ENV)
    if not val:
        if os.environ.get(_ENV_ENV, "development").lower() == "production":
            raise RuntimeError(f"{_SECRET_ENV} must be set when {_ENV_ENV}=production")
        # Development fallback: stable within a process, so tokens survive reloads in a session
        # but never leak a predictable secret into a real deployment.
        val = os.urandom(32).hex()
        os.environ[_SECRET_ENV] = val
    _secret_cache = val
    return val


def reset_cache() -> None:
    global _secret_cache
    _secret_cache = None


# --------------------------------------------------------------------- tokens

def create_token(user: User, kind: str = "access") -> str:
    ttl = ACCESS_TTL if kind == "access" else REFRESH_TTL
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value if isinstance(user.role, Role) else str(user.role),
        "type": kind,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str, expect: str = "access") -> dict:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    if payload.get("type") != expect:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"expected a {expect} token")
    return payload


# ----------------------------------------------------------------- dependencies

def current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the signed-in user from the Authorization header or an `access_token` query arg.

    EventSource (SSE) cannot set headers, so the live stream endpoint passes the token as a
    query parameter. It is still a real JWT and still fully validated.
    """
    token = creds.credentials if creds else request.query_params.get("access_token")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    payload = decode_token(token)
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or disabled")
    changed = user.password_changed_at
    if changed is not None and int(payload.get("iat", 0)) < int(changed.timestamp()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired; sign in again")
    return user


def require_roles(*roles: Role):
    """Dependency factory: allow only the given roles."""
    allowed = {r.value for r in roles}

    def _dep(user: User = Depends(current_user)) -> User:
        if role_of(user) not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                f"requires role: {' or '.join(sorted(allowed))}")
        return user

    return _dep


require_super_admin = require_roles(Role.SUPER_ADMIN)
require_admin = require_roles(Role.ADMIN, Role.SUPER_ADMIN)
require_staff = require_roles(Role.ADMIN, Role.SUPER_ADMIN, Role.FACULTY)


# ------------------------------------------------------------------- predicates

def role_of(user: User) -> str:
    return user.role.value if isinstance(user.role, Role) else str(user.role)


def is_super_admin(user: User) -> bool:
    return role_of(user) == Role.SUPER_ADMIN.value


def is_admin(user: User) -> bool:
    """True for HOD **and** super admin.

    Deliberately inclusive: every `if is_admin(...)` guard in the API means "may administer",
    and a super admin who failed those checks could not use their own system. Department
    scoping is a separate, narrower question -- see `assert_in_department`.
    """
    return role_of(user) in (Role.ADMIN.value, Role.SUPER_ADMIN.value)


def is_faculty(user: User) -> bool:
    return role_of(user) == Role.FACULTY.value


def is_student(user: User) -> bool:
    return role_of(user) == Role.STUDENT.value


def is_parent(user: User) -> bool:
    return role_of(user) == Role.PARENT.value


def is_staff(user: User) -> bool:
    return role_of(user) in (Role.FACULTY.value, Role.ADMIN.value, Role.SUPER_ADMIN.value)


# ------------------------------------------------------------ department scope

def department_scope(actor: User) -> Optional[int]:
    """The department this actor is confined to, or None for org-wide access.

    A super admin is never confined. An HOD is confined to their own department -- and an HOD
    with no department set is confined to *nothing*, which is the safe direction to fail.
    """
    if is_super_admin(actor):
        return None
    return actor.department_id


def assert_in_department(actor: User, department_id: Optional[int], what: str = "record") -> None:
    """Block an HOD reaching into another department. Super admin passes; students never get here."""
    if is_super_admin(actor):
        return
    scope = department_scope(actor)
    if scope is None:
        # An admin with no department cannot be scoped, so cannot be trusted with a scoped read.
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "your account has no department assigned")
    if department_id is not None and department_id != scope:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"this {what} belongs to another department")


def session_department_id(session: ClassSession) -> Optional[int]:
    """Which department owns a session, resolved through its subject."""
    if session.subject_id and session.subject is not None:
        return session.subject.department_id
    return None


# -------------------------------------------------------------- read authority

def readable_user_ids(actor: User, db: Optional[Session] = None) -> Optional[set[int]]:
    """User ids this actor may read, or None meaning "unrestricted".

    Returning a set (rather than a boolean per row) lets list endpoints filter *in the query*
    instead of fetching everything and hiding rows afterwards.
    """
    if is_staff(actor):
        return None
    db = db or object_session(actor)
    if is_parent(actor):
        if db is None:
            return set()
        linked = db.scalars(
            select(StudentProfile.user_id).where(StudentProfile.parent_id == actor.id)
        ).all()
        return set(linked)
    return {actor.id}


def assert_can_read_user(actor: User, target_user_id: int,
                         db: Optional[Session] = None) -> None:
    """A student reads only themselves; a parent reads only their linked children."""
    allowed = readable_user_ids(actor, db)
    if allowed is None or target_user_id in allowed:
        return
    if is_parent(actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "parents may only access their linked student's records")
    raise HTTPException(status.HTTP_403_FORBIDDEN,
                        "students may only access their own records")


def faculty_is_assigned(actor: User, session: ClassSession,
                        db: Optional[Session] = None) -> bool:
    """Is this faculty member the teacher of record for the session's subject and section?

    Ownership alone is not enough once a timetable exists: a session is generated from a slot,
    and the person entitled to mark it is whoever holds the FacultyAssignment for that
    (subject, section, term).
    """
    if session.subject_id is None or session.section_id is None:
        return False
    db = db or object_session(session)
    if db is None:
        return False
    stmt = select(FacultyAssignment.id).where(
        FacultyAssignment.faculty_id == actor.id,
        FacultyAssignment.subject_id == session.subject_id,
        FacultyAssignment.section_id == session.section_id,
    )
    if session.term_id is not None:
        stmt = stmt.where(FacultyAssignment.term_id == session.term_id)
    return db.scalars(stmt).first() is not None


def assert_owns_session(actor: User, session: ClassSession) -> None:
    """Who may read or administer a session.

    super admin  any session
    HOD          sessions in their own department only
    faculty      sessions they own, or are the assigned teacher of record for
    student      never
    parent       never
    """
    if is_super_admin(actor):
        return

    if is_admin(actor):
        dept = session_department_id(session)
        # An ad-hoc session (no subject, so no department) belongs to no department and is
        # therefore not something a department boundary can protect -- any admin may reach it,
        # as before. Only a session that *is* attached to a department gets scoped, and then an
        # admin without a department of their own is refused rather than waved through.
        if dept is not None:
            assert_in_department(actor, dept, "session")
        return

    if not is_faculty(actor):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "you do not have access to session management")

    if session.owner_id == actor.id or faculty_is_assigned(actor, session):
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "you do not teach this session")


def assert_can_mark_session(actor: User, session: ClassSession) -> None:
    """Stricter than reading: marking requires being the teacher of record, not just an admin
    with visibility. A locked session cannot be marked at all without a correction request."""
    assert_owns_session(actor, session)
    if session.is_locked:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "this session is locked; raise a correction request instead")
