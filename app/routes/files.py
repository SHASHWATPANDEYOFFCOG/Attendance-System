"""Authorised file download.

A file is served only to someone who may see the record it is attached to. The check walks the
references (profile photo, leave, issue, message, announcement) instead of trusting the file's
owner field alone, so a teacher can open a student's medical certificate for a leave they
review, but not another class's.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import current_user, is_staff
from app.db import get_db
from app.models import (
    Announcement,
    Conversation,
    Issue,
    IssueComment,
    LeaveRequest,
    Message,
    StoredFile,
    StudentProfile,
    User,
)
from app.scope import can_manage_student, can_read_student
from app.uploads import file_path

router = APIRouter(prefix="/api", tags=["files"])


def can_access_file(db: Session, actor: User, f: StoredFile) -> bool:
    if f.owner_id == actor.id:
        return True

    prof = db.scalars(select(StudentProfile).where(StudentProfile.photo_file_id == f.id)).first()
    if prof is not None and can_read_student(db, actor, prof.user_id):
        return True

    leave = db.scalars(select(LeaveRequest).where(LeaveRequest.attachment_file_id == f.id)).first()
    if leave is not None and can_manage_student(db, actor, leave.requester_id):
        return True

    issue = db.scalars(select(Issue).where(Issue.attachment_file_id == f.id)).first()
    if issue is None:
        c = db.scalars(select(IssueComment).where(IssueComment.attachment_file_id == f.id)).first()
        issue = db.get(Issue, c.issue_id) if c else None
    if issue is not None and (issue.student_id == actor.id or issue.assigned_to_id == actor.id
                              or can_manage_student(db, actor, issue.student_id)):
        return True

    msg = db.scalars(select(Message).where(Message.attachment_file_id == f.id)).first()
    if msg is not None:
        conv = db.get(Conversation, msg.conversation_id)
        if conv is not None and actor.id in (conv.staff_id, conv.student_id):
            return True

    ann = db.scalars(select(Announcement).where(Announcement.attachment_file_id == f.id)).first()
    if ann is not None:
        from app.routes.messaging import announcement_visible_to   # avoids an import cycle

        if is_staff(actor) or announcement_visible_to(db, ann, actor):
            return True
    return False


@router.get("/files/{file_id}")
def get_file(file_id: int, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    f = db.get(StoredFile, file_id)
    # 404 rather than 403 for files you may not see: do not confirm they exist.
    if f is None or not can_access_file(db, actor, f):
        raise HTTPException(404, "file not found")
    path = file_path(f)
    if not path.exists():
        raise HTTPException(410, "This file is no longer stored.")
    inline = f.content_type.startswith("image/") or f.content_type == "application/pdf"
    return FileResponse(
        path, media_type=f.content_type, filename=f.original_name,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "private, max-age=300",
                 "X-Content-Type-Options": "nosniff",
                 "Content-Security-Policy": "default-src 'none'; img-src 'self'; "
                                            "style-src 'unsafe-inline'; sandbox"},
    )
