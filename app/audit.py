"""One way to write the audit log, so every sensitive action records the same facts:
who, what, which record, why, and from where."""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User
from app.ratelimit import client_ip


def audit(db: Session, actor: Optional[User], action: str, *, target_type: Optional[str] = None,
          target_id: Any = None, reason: Optional[str] = None, detail: Any = None,
          request: Optional[Request] = None) -> None:
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, default=str, sort_keys=True)
    db.add(AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        reason=(reason or None) and reason[:300],
        detail=detail,
        ip=client_ip(request) if request is not None else None,
    ))
