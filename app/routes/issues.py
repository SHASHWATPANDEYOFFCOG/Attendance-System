"""Issues / queries raised by students, with a comment thread.

Status flow: open -> in_progress -> resolved -> closed. Staff move it along and can assign it;
the student can close a resolved issue or reopen it if the answer did not help. Who may see an
issue: the student who raised it, staff responsible for that student, and whoever it is assigned
to. Every reply and status change notifies the other side.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth import current_user, is_staff, is_student, require_staff
from app.db import get_db
from app.models import (
    Issue,
    IssueCategory,
    IssueComment,
    IssueStatus,
    StoredFile,
    StudentProfile,
    User,
    utcnow,
)
from app.notify import notify
from app.routes.academic import section_label
from app.scope import can_manage_student, responsible_staff, student_scope_clause
from app.uploads import DOCUMENTS, MB, save_upload

router = APIRouter(prefix="/api", tags=["issues"])

CATEGORIES = {
    "attendance_correction": "Attendance correction", "academic": "Academic",
    "technical": "Technical problem", "personal": "Personal", "other": "Other",
}
FLOW = {
    "open": {"in_progress", "resolved", "closed"},
    "in_progress": {"open", "resolved", "closed"},
    "resolved": {"open", "closed", "in_progress"},
    "closed": {"open"},
}


def _file(db: Session, file_id: Optional[int]) -> Optional[dict]:
    if not file_id:
        return None
    f = db.get(StoredFile, file_id)
    return {"url": f"/api/files/{f.id}", "name": f.original_name,
            "content_type": f.content_type} if f else None


def _can_see(db: Session, actor: User, issue: Issue) -> bool:
    return (issue.student_id == actor.id or issue.assigned_to_id == actor.id
            or can_manage_student(db, actor, issue.student_id))


def _out(db: Session, i: Issue, comments: bool = False) -> dict:
    student = db.get(User, i.student_id)
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == i.student_id)).first()
    assignee = db.get(User, i.assigned_to_id) if i.assigned_to_id else None
    out = {
        "id": i.id, "category": i.category, "category_label": CATEGORIES.get(i.category, i.category),
        "title": i.title, "description": i.description, "status": i.status,
        "created_at": i.created_at, "updated_at": i.updated_at, "resolved_at": i.resolved_at,
        "attachment": _file(db, i.attachment_file_id),
        "student": {"id": student.id, "name": student.display_name,
                    "roll_number": (prof.roll_number if prof else None) or student.roll_number,
                    "section": section_label(prof.section) if prof and prof.section else None},
        "assigned_to": {"id": assignee.id, "name": assignee.display_name} if assignee else None,
        "comment_count": db.scalar(select(func.count()).select_from(IssueComment)
                                   .where(IssueComment.issue_id == i.id)) or 0,
    }
    if comments:
        rows = db.scalars(select(IssueComment).where(IssueComment.issue_id == i.id)
                          .order_by(IssueComment.created_at))
        out["comments"] = []
        for c in rows:
            a = db.get(User, c.author_id)
            out["comments"].append({
                "id": c.id, "body": c.body, "created_at": c.created_at,
                "author": {"id": a.id, "name": a.display_name, "staff": is_staff(a)} if a else None,
                "attachment": _file(db, c.attachment_file_id)})
    return out


def _load(db: Session, actor: User, issue_id: int) -> Issue:
    i = db.get(Issue, issue_id)
    if i is None or not _can_see(db, actor, i):
        raise HTTPException(404, "issue not found")
    return i


# ------------------------------------------------------------------ student

@router.get("/me/issues")
def my_issues(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    rows = db.scalars(select(Issue).where(Issue.student_id == actor.id)
                      .order_by(Issue.updated_at.desc()))
    return [_out(db, i) for i in rows]


@router.post("/me/issues", status_code=201)
async def raise_issue(request: Request, category: str = Form(...), title: str = Form(...),
                      description: str = Form(...), attachment: Optional[UploadFile] = File(None),
                      db: Session = Depends(get_db), actor: User = Depends(current_user)):
    if not is_student(actor):
        raise HTTPException(403, "Only students raise issues here.")
    if category not in CATEGORIES:
        raise HTTPException(422, detail={"field": "category", "message": "Choose a category."})
    title, description = title.strip(), description.strip()
    if not 3 <= len(title) <= 160:
        raise HTTPException(422, detail={"field": "title", "message": "Write a title (3–160 characters)."})
    if not 10 <= len(description) <= 5000:
        raise HTTPException(422, detail={"field": "description",
                                         "message": "Describe the issue (at least 10 characters)."})
    issue = Issue(student_id=actor.id, category=category, title=title, description=description)
    db.add(issue)
    db.flush()
    if attachment is not None and attachment.filename:
        f = await save_upload(db, attachment, owner_id=actor.id, purpose="issue",
                              allowed=DOCUMENTS, max_bytes=5 * MB)
        issue.attachment_file_id = f.id
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == actor.id)).first()
    staff = responsible_staff(db, prof) if prof else set()
    notify(db, staff, "issue_submitted", f"New issue: {title}",
           f"{actor.display_name} raised a {CATEGORIES[category].lower()} issue: {title}",
           link=f"/staff/issues/{issue.id}", email=True)
    audit(db, actor, "issue_raised", target_type="issue", target_id=issue.id, request=request)
    db.commit()
    return _out(db, issue)


# ------------------------------------------------------------------- shared

@router.get("/issues/{issue_id}")
def get_issue(issue_id: int, db: Session = Depends(get_db), actor: User = Depends(current_user)):
    return _out(db, _load(db, actor, issue_id), comments=True)


@router.post("/issues/{issue_id}/comments", status_code=201)
async def comment(issue_id: int, request: Request, body: str = Form(...),
                  attachment: Optional[UploadFile] = File(None),
                  db: Session = Depends(get_db), actor: User = Depends(current_user)):
    issue = _load(db, actor, issue_id)
    text = body.strip()
    if not 1 <= len(text) <= 5000:
        raise HTTPException(422, detail={"field": "body", "message": "Write a reply."})
    if issue.status == IssueStatus.CLOSED.value and not is_staff(actor):
        raise HTTPException(409, "This issue is closed. Reopen it to reply.")
    c = IssueComment(issue_id=issue.id, author_id=actor.id, body=text)
    db.add(c)
    db.flush()
    if attachment is not None and attachment.filename:
        f = await save_upload(db, attachment, owner_id=actor.id, purpose="issue",
                              allowed=DOCUMENTS, max_bytes=5 * MB)
        c.attachment_file_id = f.id
    issue.updated_at = utcnow()
    if is_staff(actor):
        if issue.status == IssueStatus.OPEN.value:
            issue.status = IssueStatus.IN_PROGRESS.value
        notify(db, [issue.student_id], "issue_reply", f"Reply on: {issue.title}",
               f"{actor.display_name}: {text[:300]}", link=f"/student/issues/{issue.id}",
               email=True)
    else:
        prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == actor.id)).first()
        targets = {issue.assigned_to_id} if issue.assigned_to_id else (
            responsible_staff(db, prof) if prof else set())
        notify(db, targets, "issue_reply", f"Student replied: {issue.title}",
               f"{actor.display_name}: {text[:300]}", link=f"/staff/issues/{issue.id}")
    db.commit()
    return _out(db, issue, comments=True)


class StatusIn(BaseModel):
    status: str


@router.post("/issues/{issue_id}/status")
def change_status(issue_id: int, body: StatusIn, request: Request,
                  db: Session = Depends(get_db), actor: User = Depends(current_user)):
    issue = _load(db, actor, issue_id)
    new = body.status
    if new not in FLOW:
        raise HTTPException(422, "unknown status")
    if new == issue.status:
        return _out(db, issue, comments=True)
    if new not in FLOW[issue.status]:
        raise HTTPException(409, f"An issue cannot go from {issue.status} to {new}.")
    if not is_staff(actor):
        # The student may close a resolved issue, or reopen one that did not get solved.
        allowed = {("resolved", "closed"), ("resolved", "open"), ("closed", "open")}
        if (issue.status, new) not in allowed:
            raise HTTPException(403, "Only staff can change this status.")
    old = issue.status
    issue.status = new
    issue.updated_at = utcnow()
    issue.resolved_at = utcnow() if new == IssueStatus.RESOLVED.value else issue.resolved_at
    who = actor.display_name
    if is_staff(actor):
        notify(db, [issue.student_id], "issue_status", f"Issue {new.replace('_', ' ')}: {issue.title}",
               f"{who} changed your issue from {old.replace('_', ' ')} to {new.replace('_', ' ')}.",
               link=f"/student/issues/{issue.id}", email=new in ("resolved", "closed"))
    elif issue.assigned_to_id:
        notify(db, [issue.assigned_to_id], "issue_status", f"Issue {new}: {issue.title}",
               f"{who} marked the issue {new}.", link=f"/staff/issues/{issue.id}")
    audit(db, actor, "issue_status_changed", target_type="issue", target_id=issue.id,
          detail={"from": old, "to": new}, request=request)
    db.commit()
    return _out(db, issue, comments=True)


# ---------------------------------------------------------------- authority

@router.get("/issues")
def list_issues(status: Optional[str] = None, category: Optional[str] = None,
                assigned: Optional[str] = None, q: Optional[str] = None,
                page: int = 1, page_size: int = 50,
                db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    stmt = (select(Issue).join(StudentProfile, StudentProfile.user_id == Issue.student_id)
            .join(User, User.id == Issue.student_id)
            .where(or_(student_scope_clause(db, actor), Issue.assigned_to_id == actor.id)))
    if status == "active":
        stmt = stmt.where(Issue.status.in_(["open", "in_progress"]))
    elif status:
        stmt = stmt.where(Issue.status == status)
    if category:
        stmt = stmt.where(Issue.category == category)
    if assigned == "me":
        stmt = stmt.where(Issue.assigned_to_id == actor.id)
    elif assigned == "none":
        stmt = stmt.where(Issue.assigned_to_id.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Issue.title.ilike(like), User.display_name.ilike(like),
                              StudentProfile.roll_number.ilike(like)))
    page_size = max(10, min(200, page_size))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Issue.updated_at.desc())
                      .offset((max(1, page) - 1) * page_size).limit(page_size))
    return {"rows": [_out(db, i) for i in rows],
            "meta": {"page": max(1, page), "page_size": page_size, "total": total,
                     "pages": (total + page_size - 1) // page_size}}


class AssignIn(BaseModel):
    assigned_to_id: Optional[int] = None


@router.post("/issues/{issue_id}/assign")
def assign(issue_id: int, body: AssignIn, request: Request, db: Session = Depends(get_db),
           actor: User = Depends(require_staff)):
    issue = _load(db, actor, issue_id)
    if body.assigned_to_id is not None:
        target = db.get(User, body.assigned_to_id)
        if target is None or not is_staff(target) or target.deleted_at is not None:
            raise HTTPException(404, "staff member not found")
        notify(db, [target.id], "issue_assigned", f"Issue assigned to you: {issue.title}",
               f"{actor.display_name} assigned you an issue from "
               f"{db.get(User, issue.student_id).display_name}.",
               link=f"/staff/issues/{issue.id}", email=True)
    issue.assigned_to_id = body.assigned_to_id
    issue.updated_at = utcnow()
    audit(db, actor, "issue_assigned", target_type="issue", target_id=issue.id,
          detail={"assigned_to": body.assigned_to_id}, request=request)
    db.commit()
    return _out(db, issue, comments=True)
