"""In-app notifications: list, unread counts, mark read, and a personal live stream.

The stream is per user: the bus delivers an event to a personal stream only when the event
names that user, so one student's notifications can never appear in another's browser.
"""
from __future__ import annotations

import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import current_user, is_staff
from app.bus import bus
from app.db import SessionLocal, get_db
from app.models import Notification, User, utcnow
from app.notify import INAPP

router = APIRouter(prefix="/api", tags=["notifications"])


def _out(n: Notification) -> dict:
    return {"id": n.id, "type": n.type, "title": n.title or n.type.replace("_", " "),
            "body": n.body, "link": n.link, "created_at": n.created_at, "read": n.read_at is not None}


@router.get("/notifications")
def list_notifications(unread_only: bool = False, page: int = 1, page_size: int = 30,
                       db: Session = Depends(get_db), actor: User = Depends(current_user)):
    stmt = select(Notification).where(Notification.user_id == actor.id,
                                      Notification.channel == INAPP)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    page_size = max(5, min(100, page_size))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Notification.created_at.desc())
                      .offset((max(1, page) - 1) * page_size).limit(page_size))
    return {"rows": [_out(n) for n in rows],
            "meta": {"page": max(1, page), "total": total,
                     "pages": (total + page_size - 1) // page_size}}


def counts_for(db: Session, actor: User) -> dict:
    from app.routes.messaging import unread_announcements, unread_messages

    out = {
        "notifications": db.scalar(select(func.count()).select_from(Notification).where(
            Notification.user_id == actor.id, Notification.channel == INAPP,
            Notification.read_at.is_(None))) or 0,
        "messages": unread_messages(db, actor),
        "announcements": unread_announcements(db, actor),
    }
    if is_staff(actor):
        from app.models import Issue, LeaveRequest, ReviewItem, StudentProfile
        from app.scope import student_scope_clause

        scope = student_scope_clause(db, actor)
        out["leaves"] = db.scalar(
            select(func.count()).select_from(LeaveRequest)
            .join(StudentProfile, StudentProfile.user_id == LeaveRequest.requester_id)
            .where(LeaveRequest.status == "pending", scope)) or 0
        out["issues"] = db.scalar(
            select(func.count()).select_from(Issue)
            .join(StudentProfile, StudentProfile.user_id == Issue.student_id)
            .where(Issue.status.in_(["open", "in_progress"]), scope)) or 0
        out["review"] = db.scalar(
            select(func.count()).select_from(ReviewItem)
            .join(StudentProfile, StudentProfile.user_id == ReviewItem.user_id)
            .where(ReviewItem.status == "pending", scope)) or 0
    return out


@router.get("/notifications/counts")
def counts(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    return counts_for(db, actor)


class ReadIn(BaseModel):
    ids: Optional[List[int]] = None        # None = all


@router.post("/notifications/read")
def mark_read(body: ReadIn, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    stmt = (update(Notification)
            .where(Notification.user_id == actor.id, Notification.channel == INAPP,
                   Notification.read_at.is_(None))
            .values(read_at=utcnow()))
    if body.ids:
        stmt = stmt.where(Notification.id.in_(body.ids))
    result = db.execute(stmt)
    db.commit()
    return {"marked": result.rowcount}


@router.get("/notifications/stream")
async def stream(request: Request, actor: User = Depends(current_user)):
    """Server-sent events for this user only: new notifications as they happen."""
    queue = bus.subscribe(user_id=actor.id)
    uid = actor.id

    async def gen():
        try:
            yield f"event: hello\ndata: {json.dumps({'user_id': uid})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield ev.to_sse()
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
