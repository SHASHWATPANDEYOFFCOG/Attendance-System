"""The two access codes that gate who may become staff and who may become an administrator.

    authority      needed to register at /authority/register (teacher / HOD accounts)
    administrator  needed for a signed-in authority to unlock the administrator role

Only argon2 hashes are stored (in the `settings` table, under keys no settings form ever
returns), so neither code reaches a browser or sits in the database in readable form. Until an
administrator sets their own, the documented defaults apply; changing a code revokes the old
one immediately. Every guess is rate-limited by the caller.
"""
from __future__ import annotations

import hmac
from typing import Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import hash_password, verify_password
from app.models import Setting, User, utcnow

KINDS = ("administrator", "authority")
DEFAULTS = {"administrator": "occlubio-administrator", "authority": "occlubio-authority"}
MIN_LEN, MAX_LEN = 8, 64


class AccessCodeError(ValueError):
    pass


def _key(kind: str) -> str:
    if kind not in KINDS:
        raise AccessCodeError(f"unknown access code {kind!r}")
    return f"access_code.{kind}"


def _row(db: Session, kind: str) -> Optional[Setting]:
    return db.scalars(select(Setting).where(Setting.key == _key(kind))).first()


def verify(db: Session, kind: str, code: Optional[str]) -> bool:
    candidate = (code or "").strip()
    if not candidate:
        return False
    row = _row(db, kind)
    if row is None:
        return hmac.compare_digest(candidate.encode(), DEFAULTS[kind].encode())
    return verify_password(candidate, row.value)


def change(db: Session, kind: str, new_code: str, actor: User) -> None:
    code = (new_code or "").strip()
    if not MIN_LEN <= len(code) <= MAX_LEN:
        raise AccessCodeError(f"Use {MIN_LEN}-{MAX_LEN} characters.")
    if " " in code:
        raise AccessCodeError("Do not use spaces.")
    other = "authority" if kind == "administrator" else "administrator"
    if verify(db, other, code):
        raise AccessCodeError("The administrator and authority codes must be different.")
    row = _row(db, kind)
    if row is None:
        db.add(Setting(key=_key(kind), value=hash_password(code), updated_by_id=actor.id,
                       updated_at=utcnow()))
    else:
        row.value = hash_password(code)
        row.updated_by_id = actor.id
        row.updated_at = utcnow()
    db.flush()


def status(db: Session) -> Dict[str, dict]:
    out = {}
    for kind in KINDS:
        row = _row(db, kind)
        changed_by = db.get(User, row.updated_by_id) if row and row.updated_by_id else None
        out[kind] = {"is_default": row is None,
                     "changed_at": row.updated_at if row else None,
                     "changed_by": changed_by.display_name if changed_by else None}
    return out
