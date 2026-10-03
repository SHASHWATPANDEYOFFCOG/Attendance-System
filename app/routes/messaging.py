"""Direct messages and the notice board.

Messages: one conversation per (staff member, student). Staff start them — to one student, a
selection, a section, a batch, a branch or everyone in their scope — and a bulk send fans out into
each student's own thread, so every student can reply privately. Students reply; they do not
cold-message staff (issues are for that).

Announcements: a notice with an audience (all / branch / batch / section / chosen students),
optional attachment, optional expiry, optional pin, optional email. The audience is resolved at
read time, so a student who joins a section later still sees its current notices.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Set

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth import current_user, is_admin, is_staff, is_student, is_super_admin, require_staff
from app.db import get_db
from app.models import (
    Announcement,
    AnnouncementRead,
    Conversation,
    Message,
    Program,
    Section,
    StoredFile,
    StudentProfile,
    User,
    utcnow,
)
from app.notify import notify
from app.scope import can_manage_student, student_scope_clause
from app.uploads import DOCUMENTS, MB, save_upload

router = APIRouter(prefix="/api", tags=["messaging"])

AUDIENCES = ("all", "department", "batch", "section", "students")


def _file(db: Session, file_id: Optional[int]) -> Optional[dict]:
    if not file_id:
        return None
    f = db.get(StoredFile, file_id)
    return {"url": f"/api/files/{f.id}", "name": f.original_name,
            "content_type": f.content_type} if f else None


# ------------------------------------------------------------- conversations

def _conv_out(db: Session, c: Conversation, me: User) -> dict:
    other_id = c.student_id if me.id == c.staff_id else c.staff_id
    other = db.get(User, other_id)
    last = db.scalars(select(Message).where(Message.conversation_id == c.id)
                      .order_by(Message.created_at.desc())).first()
    unread = db.scalar(select(func.count()).select_from(Message).where(
        Message.conversation_id == c.id, Message.sender_id != me.id,
        Message.read_at.is_(None))) or 0
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == c.student_id)).first()
    return {"id": c.id, "with": {"id": other.id, "name": other.display_name,
                                  "roll_number": prof.roll_number if prof and other_id == c.student_id else None},
            "last_message": {"body": last.body[:140], "at": last.created_at,
                             "mine": last.sender_id == me.id} if last else None,
            "unread": unread, "last_message_at": c.last_message_at}


def _msg_out(db: Session, m: Message, me: User) -> dict:
    sender = db.get(User, m.sender_id)
    return {"id": m.id, "body": m.body, "created_at": m.created_at, "mine": m.sender_id == me.id,
            "sender": sender.display_name if sender else None, "read_at": m.read_at,
            "attachment": _file(db, m.attachment_file_id)}


def _conversation(db: Session, conv_id: int, me: User) -> Conversation:
    c = db.get(Conversation, conv_id)
    if c is None or me.id not in (c.staff_id, c.student_id):
        raise HTTPException(404, "conversation not found")
    return c


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    rows = db.scalars(select(Conversation).where(
        or_(Conversation.staff_id == actor.id, Conversation.student_id == actor.id))
        .order_by(Conversation.last_message_at.desc()))
    return [_conv_out(db, c, actor) for c in rows]


@router.get("/conversations/{conv_id}")
def read_conversation(conv_id: int, db: Session = Depends(get_db),
                      actor: User = Depends(current_user)):
    c = _conversation(db, conv_id, actor)
    msgs = list(db.scalars(select(Message).where(Message.conversation_id == c.id)
                           .order_by(Message.created_at)))
    now = utcnow()
    for m in msgs:
        if m.sender_id != actor.id and m.read_at is None:
            m.read_at = now
    db.commit()
    return {**_conv_out(db, c, actor), "messages": [_msg_out(db, m, actor) for m in msgs]}


def _send(db: Session, c: Conversation, sender: User, body: str,
          attachment_id: Optional[int] = None, email: bool = False) -> Message:
    m = Message(conversation_id=c.id, sender_id=sender.id, body=body,
                attachment_file_id=attachment_id)
    db.add(m)
    c.last_message_at = utcnow()
    to = c.student_id if sender.id == c.staff_id else c.staff_id
    link = (f"/student/messages/{c.id}" if to == c.student_id else f"/staff/messages/{c.id}")
    notify(db, [to], "message", f"New message from {sender.display_name}", body[:300],
           link=link, email=email)
    return m


@router.post("/conversations/{conv_id}/messages", status_code=201)
async def reply(conv_id: int, body: str = Form(...), attachment: Optional[UploadFile] = File(None),
                db: Session = Depends(get_db), actor: User = Depends(current_user)):
    c = _conversation(db, conv_id, actor)
    text = body.strip()
    if not 1 <= len(text) <= 5000:
        raise HTTPException(422, detail={"field": "body", "message": "Write a message."})
    fid = None
    if attachment is not None and attachment.filename:
        f = await save_upload(db, attachment, owner_id=actor.id, purpose="message",
                              allowed=DOCUMENTS, max_bytes=5 * MB)
        fid = f.id
    m = _send(db, c, actor, text, fid)
    db.commit()
    return _msg_out(db, m, actor)


def _get_or_create(db: Session, staff_id: int, student_id: int) -> Conversation:
    c = db.scalars(select(Conversation).where(Conversation.staff_id == staff_id,
                                              Conversation.student_id == student_id)).first()
    if c is None:
        c = Conversation(staff_id=staff_id, student_id=student_id)
        db.add(c)
        db.flush()
    return c


def resolve_students(db: Session, actor: User, audience: str, ids: List[int]) -> Set[int]:
    """Approved, active students for an audience, always intersected with the actor's scope."""
    stmt = (select(StudentProfile.user_id).join(User, User.id == StudentProfile.user_id)
            .where(User.deleted_at.is_(None), User.is_active.is_(True),
                   StudentProfile.status == "approved"))
    if is_staff(actor):
        stmt = stmt.where(student_scope_clause(db, actor))
    if audience == "students":
        stmt = stmt.where(StudentProfile.user_id.in_(ids or [-1]))
    elif audience == "section":
        stmt = stmt.where(StudentProfile.section_id.in_(ids or [-1]))
    elif audience == "batch":
        stmt = stmt.where(StudentProfile.batch_id.in_(ids or [-1]))
    elif audience == "department":
        secs = select(Section.id).join(Program, Program.id == Section.program_id).where(
            Program.department_id.in_(ids or [-1]))
        stmt = stmt.where(or_(StudentProfile.department_id.in_(ids or [-1]),
                              StudentProfile.section_id.in_(secs)))
    elif audience != "all":
        raise HTTPException(422, "unknown audience")
    return set(db.scalars(stmt))


class BroadcastIn(BaseModel):
    audience: str
    ids: List[int] = Field(default_factory=list)
    body: str = Field(min_length=1, max_length=5000)
    email: bool = False


@router.post("/messages/broadcast", status_code=201)
def broadcast(body: BroadcastIn, request: Request, db: Session = Depends(get_db),
              actor: User = Depends(require_staff)):
    if body.audience not in AUDIENCES:
        raise HTTPException(422, detail={"field": "audience", "message": "Choose who to send to."})
    if body.audience == "students":
        outside = [i for i in body.ids if not can_manage_student(db, actor, i)]
        if outside:
            raise HTTPException(403, f"{len(outside)} selected student(s) are not in your classes.")
    recipients = resolve_students(db, actor, body.audience, body.ids)
    if not recipients:
        raise HTTPException(422, "No students match that selection.")
    if len(recipients) > 5000:
        raise HTTPException(413, "That is more than 5000 students; narrow the audience.")
    convs = []
    for sid in sorted(recipients):
        c = _get_or_create(db, actor.id, sid)
        _send(db, c, actor, body.body.strip(), email=body.email)
        convs.append(c.id)
    audit(db, actor, "message_broadcast", target_type="conversation",
          detail={"audience": body.audience, "ids": body.ids[:50], "recipients": len(recipients)},
          request=request)
    db.commit()
    return {"sent": len(recipients), "conversation_ids": convs[:1] if len(convs) == 1 else None}


# ------------------------------------------------------------ announcements

def announcement_visible_to(db: Session, a: Announcement, user: User) -> bool:
    if a.expires_at is not None and a.expires_at < utcnow():
        return False
    if is_staff(user):
        return True
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    if prof is None:
        return a.audience_type == "all"
    ids = set(json.loads(a.audience_ids or "[]"))
    if a.audience_type == "all":
        # "All" from a teacher or HOD means all of *their* students, not the whole college.
        author = db.get(User, a.author_id)
        return author is None or is_super_admin(author) or can_manage_student(db, author, user.id)
    if a.audience_type == "students":
        return user.id in ids
    if a.audience_type == "section":
        return prof.section_id in ids
    if a.audience_type == "batch":
        return prof.batch_id in ids
    if a.audience_type == "department":
        dept = prof.department_id
        if dept is None and prof.section_id:
            sec = db.get(Section, prof.section_id)
            dept = sec.program.department_id if sec and sec.program else None
        return dept in ids
    return False


def _ann_out(db: Session, a: Announcement, me: User) -> dict:
    author = db.get(User, a.author_id)
    read = db.scalars(select(AnnouncementRead).where(AnnouncementRead.announcement_id == a.id,
                                                     AnnouncementRead.user_id == me.id)).first()
    return {"id": a.id, "title": a.title, "body": a.body, "audience_type": a.audience_type,
            "audience_ids": json.loads(a.audience_ids or "[]"), "pinned": a.pinned,
            "expires_at": a.expires_at, "created_at": a.created_at, "send_email": a.send_email,
            "author": author.display_name if author else None, "mine": a.author_id == me.id,
            "attachment": _file(db, a.attachment_file_id), "read": read is not None}


@router.get("/announcements")
def list_announcements(include_expired: bool = False, db: Session = Depends(get_db),
                       actor: User = Depends(current_user)):
    rows = list(db.scalars(select(Announcement).order_by(Announcement.pinned.desc(),
                                                         Announcement.created_at.desc()).limit(300)))
    out = []
    for a in rows:
        if is_staff(actor):
            expired = a.expires_at is not None and a.expires_at < utcnow()
            mine_or_scope = (a.author_id == actor.id or is_super_admin(actor) or is_admin(actor))
            if (expired and not include_expired) or not mine_or_scope:
                continue
            out.append(_ann_out(db, a, actor))
        elif announcement_visible_to(db, a, actor):
            out.append(_ann_out(db, a, actor))
    return out


@router.post("/announcements", status_code=201)
async def create_announcement(
    request: Request, title: str = Form(...), body: str = Form(...),
    audience_type: str = Form("all"), audience_ids: Optional[str] = Form(None),
    pinned: bool = Form(False), send_email: bool = Form(False),
    expires_at: Optional[datetime] = Form(None), attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db), actor: User = Depends(require_staff),
):
    if audience_type not in AUDIENCES:
        raise HTTPException(422, detail={"field": "audience_type", "message": "Choose an audience."})
    title, body = title.strip(), body.strip()
    if not 3 <= len(title) <= 200:
        raise HTTPException(422, detail={"field": "title", "message": "Write a title (3–200 characters)."})
    if not 1 <= len(body) <= 10000:
        raise HTTPException(422, detail={"field": "body", "message": "Write the notice."})
    try:
        ids = [int(x) for x in json.loads(audience_ids or "[]")]
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"field": "audience_ids", "message": "Invalid audience."})
    if audience_type != "all" and not ids:
        raise HTTPException(422, detail={"field": "audience_ids", "message": "Choose who sees it."})
    if expires_at is not None:
        if expires_at.tzinfo is None:
            from datetime import timezone

            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= utcnow():
            raise HTTPException(422, detail={"field": "expires_at",
                                             "message": "The expiry must be in the future."})
    recipients = resolve_students(db, actor, audience_type, ids)
    if not recipients:
        raise HTTPException(422, "No students in your classes match that audience.")
    a = Announcement(author_id=actor.id, title=title, body=body, audience_type=audience_type,
                     audience_ids=json.dumps(ids), pinned=pinned, send_email=send_email,
                     expires_at=expires_at)
    db.add(a)
    db.flush()
    if attachment is not None and attachment.filename:
        f = await save_upload(db, attachment, owner_id=actor.id, purpose="announcement",
                              allowed=DOCUMENTS, max_bytes=5 * MB)
        a.attachment_file_id = f.id
    notify(db, recipients, "announcement", f"Notice: {title}", body[:300],
           link="/student/messages?tab=notices", email=send_email)
    audit(db, actor, "announcement_posted", target_type="announcement", target_id=a.id,
          detail={"audience": audience_type, "recipients": len(recipients), "email": send_email},
          request=request)
    db.commit()
    return {**_ann_out(db, a, actor), "recipients": len(recipients)}


@router.delete("/announcements/{ann_id}")
def delete_announcement(ann_id: int, request: Request, db: Session = Depends(get_db),
                        actor: User = Depends(require_staff)):
    a = db.get(Announcement, ann_id)
    if a is None:
        raise HTTPException(404, "announcement not found")
    if a.author_id != actor.id and not is_admin(actor):
        raise HTTPException(403, "Only the author or an administrator can remove a notice.")
    db.delete(a)
    audit(db, actor, "announcement_deleted", target_type="announcement", target_id=ann_id,
          request=request)
    db.commit()
    return {"deleted": ann_id}


@router.post("/announcements/{ann_id}/read")
def mark_announcement_read(ann_id: int, db: Session = Depends(get_db),
                           actor: User = Depends(current_user)):
    a = db.get(Announcement, ann_id)
    if a is None or not announcement_visible_to(db, a, actor):
        raise HTTPException(404, "announcement not found")
    if db.scalars(select(AnnouncementRead).where(AnnouncementRead.announcement_id == a.id,
                                                 AnnouncementRead.user_id == actor.id)).first() is None:
        db.add(AnnouncementRead(announcement_id=a.id, user_id=actor.id))
        db.commit()
    return {"read": True}


def unread_announcements(db: Session, user: User) -> int:
    if is_staff(user):
        return 0
    n = 0
    read = set(db.scalars(select(AnnouncementRead.announcement_id)
                          .where(AnnouncementRead.user_id == user.id)))
    for a in db.scalars(select(Announcement).order_by(Announcement.created_at.desc()).limit(200)):
        if a.id not in read and announcement_visible_to(db, a, user):
            n += 1
    return n


def unread_messages(db: Session, user: User) -> int:
    return db.scalar(
        select(func.count()).select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(or_(Conversation.staff_id == user.id, Conversation.student_id == user.id),
               Message.sender_id != user.id, Message.read_at.is_(None))) or 0


__all__ = ["router", "announcement_visible_to", "unread_announcements", "unread_messages",
           "is_student"]
