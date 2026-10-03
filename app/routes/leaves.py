"""Leave applications.

Student: apply (whole days or specific lectures), attach a certificate, edit or cancel while
pending, see every decision with the teacher's remark. Past dates are allowed back to the
admin's limit, so a student can explain an absence after the fact.

Teacher / HOD: list in scope, open attachments, approve or reject with a remark, bulk approve.
Approving immediately rewrites already-closed sessions in the range from ABSENT to ON LEAVE;
sessions still to come pick the leave up when they close.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import settings_service
from app.audit import audit
from app.auth import current_user, is_student, require_staff
from app.clock import local_today, tz_of
from app.db import get_db
from app.models import (
    AttendanceRecordRow,
    ClassSession,
    LeaveRequest,
    LeaveStatus,
    RosterEntry,
    StoredFile,
    StudentProfile,
    Subject,
    User,
    utcnow,
)
from app.notify import notify
from app.routes.academic import section_label
from app.runtime import cfg
from app.scope import assert_can_manage_student, responsible_staff, student_scope_clause
from app.session_service import apply_leave, local_dt, session_local_date
from app.uploads import DOCUMENTS, MB, delete_file, save_upload

router = APIRouter(prefix="/api", tags=["leaves"])

TYPES = {
    "medical": "Medical", "personal": "Personal", "family_emergency": "Family emergency",
    "on_duty": "Duty / event", "other": "Other", "casual": "Casual",
}
SUBMITTABLE = ("medical", "personal", "family_emergency", "on_duty", "other")
MAX_DAYS = 30
MAX_AHEAD_DAYS = 90


def _out(db: Session, l: LeaveRequest, with_student: bool = False) -> dict:
    out = {
        "id": l.id, "type": l.type, "type_label": TYPES.get(l.type, l.type),
        "from_date": l.from_date.isoformat(), "to_date": l.to_date.isoformat(),
        "session_ids": json.loads(l.session_ids) if l.session_ids else None,
        "reason": l.reason, "explanation": l.explanation, "status": l.status,
        "remark": l.comment, "decided_at": l.decided_at, "created_at": l.created_at,
        "updated_at": l.updated_at,
        "attachment": None,
    }
    if l.attachment_file_id:
        f = db.get(StoredFile, l.attachment_file_id)
        if f:
            out["attachment"] = {"url": f"/api/files/{f.id}", "name": f.original_name,
                                 "content_type": f.content_type, "size": f.size}
    if l.approver_id:
        a = db.get(User, l.approver_id)
        out["decided_by"] = a.display_name if a else None
    if with_student:
        u = db.get(User, l.requester_id)
        prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == l.requester_id)).first()
        out["student"] = {"id": u.id, "name": u.display_name,
                          "roll_number": (prof.roll_number if prof else None) or u.roll_number,
                          "section": section_label(prof.section) if prof and prof.section else None}
    if out["session_ids"]:
        lectures = []
        for sid in out["session_ids"]:
            s = db.get(ClassSession, sid)
            if s:
                subj = db.get(Subject, s.subject_id) if s.subject_id else None
                lectures.append({"id": s.id, "date": session_local_date(s, cfg).isoformat(),
                                 "subject": subj.code if subj else s.title})
        out["lectures"] = lectures
    return out


def _validate(db: Session, student: User, *, type_: str, from_date: date, to_date: date,
              reason: str, explanation: Optional[str], session_ids: Optional[List[int]],
              exclude_id: Optional[int] = None) -> None:
    def bad(field: str, message: str):
        raise HTTPException(422, detail={"field": field, "message": message})

    if type_ not in SUBMITTABLE:
        bad("type", "Choose a leave type.")
    if to_date < from_date:
        bad("to_date", "The end date cannot be before the start date.")
    if (to_date - from_date).days + 1 > MAX_DAYS:
        bad("to_date", f"A single application can cover at most {MAX_DAYS} days.")
    today = local_today(tz_of(cfg))
    back = int(settings_service.get(db, cfg, "leave_backdate_days"))
    if from_date < today - timedelta(days=back):
        bad("from_date", f"Leave can be applied for at most {back} day(s) in the past.")
    if to_date > today + timedelta(days=MAX_AHEAD_DAYS):
        bad("to_date", f"Leave can be applied at most {MAX_AHEAD_DAYS} days ahead.")
    if len(reason.strip()) < 3:
        bad("reason", "Give a short reason.")
    if len(reason) > 200:
        bad("reason", "Keep the reason under 200 characters; use the explanation for detail.")
    if explanation and len(explanation) > 4000:
        bad("explanation", "Keep the explanation under 4000 characters.")
    if session_ids:
        owned = set(db.scalars(select(RosterEntry.session_id).where(
            RosterEntry.user_id == student.id, RosterEntry.session_id.in_(session_ids))))
        if set(session_ids) - owned:
            bad("session_ids", "Some of the chosen lectures are not yours.")
        for sid in session_ids:
            s = db.get(ClassSession, sid)
            if not (from_date <= session_local_date(s, cfg) <= to_date):
                bad("session_ids", "Chosen lectures must fall within the leave dates.")
    clash = select(LeaveRequest).where(
        LeaveRequest.requester_id == student.id,
        LeaveRequest.status.in_([LeaveStatus.PENDING.value, LeaveStatus.APPROVED.value]),
        LeaveRequest.from_date <= to_date, LeaveRequest.to_date >= from_date)
    if exclude_id:
        clash = clash.where(LeaveRequest.id != exclude_id)
    other = db.scalars(clash).first()
    if other is not None and not (other.session_ids and session_ids):
        bad("from_date", f"You already have a {other.status} leave from {other.from_date} to "
                         f"{other.to_date} overlapping these dates.")


def _parse_ids(raw: Optional[str]) -> Optional[List[int]]:
    if not raw:
        return None
    try:
        ids = [int(x) for x in json.loads(raw)]
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"field": "session_ids", "message": "Invalid lectures."})
    return sorted(set(ids)) or None


def _require_student(db: Session, user: User) -> StudentProfile:
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == user.id)).first()
    if not is_student(user) or prof is None:
        raise HTTPException(403, "Only students apply for leave.")
    if prof.status != "approved":
        raise HTTPException(403, "Your account must be approved before you can apply for leave.")
    return prof


# ------------------------------------------------------------------ student

@router.get("/me/leaves")
def my_leaves(db: Session = Depends(get_db), actor: User = Depends(current_user)):
    rows = db.scalars(select(LeaveRequest).where(LeaveRequest.requester_id == actor.id)
                      .order_by(LeaveRequest.created_at.desc()))
    return [_out(db, l) for l in rows]


@router.get("/me/leaves/lectures")
def my_lectures(from_date: date, to_date: date, db: Session = Depends(get_db),
                actor: User = Depends(current_user)):
    """Lectures in a date range, for choosing "specific lectures" on the form."""
    if (to_date - from_date).days > MAX_DAYS:
        raise HTTPException(422, f"Choose at most {MAX_DAYS} days.")
    rows = db.execute(
        select(ClassSession, Subject).join(RosterEntry, RosterEntry.session_id == ClassSession.id)
        .outerjoin(Subject, Subject.id == ClassSession.subject_id)
        .where(RosterEntry.user_id == actor.id, ClassSession.deleted_at.is_(None),
               ClassSession.scheduled_start >= local_dt(from_date, 0, cfg),
               ClassSession.scheduled_start < local_dt(to_date + timedelta(days=1), 0, cfg))
        .order_by(ClassSession.scheduled_start)).all()
    out = []
    for s, subj in rows:
        rec = db.scalars(select(AttendanceRecordRow).where(
            AttendanceRecordRow.session_id == s.id, AttendanceRecordRow.user_id == actor.id)).first()
        out.append({"id": s.id, "date": session_local_date(s, cfg).isoformat(),
                    "start": s.scheduled_start, "subject": subj.code if subj else s.title,
                    "status": rec.effective_status if rec else None})
    return out


@router.post("/me/leaves", status_code=201)
async def apply_for_leave(
    request: Request,
    type: str = Form(...), from_date: date = Form(...), to_date: date = Form(...),
    reason: str = Form(...), explanation: Optional[str] = Form(None),
    session_ids: Optional[str] = Form(None), attachment: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db), actor: User = Depends(current_user),
):
    prof = _require_student(db, actor)
    ids = _parse_ids(session_ids)
    _validate(db, actor, type_=type, from_date=from_date, to_date=to_date, reason=reason,
              explanation=explanation, session_ids=ids)
    leave = LeaveRequest(requester_id=actor.id, type=type, from_date=from_date, to_date=to_date,
                         reason=reason.strip(), explanation=(explanation or "").strip() or None,
                         session_ids=json.dumps(ids) if ids else None)
    db.add(leave)
    db.flush()
    if attachment is not None and attachment.filename:
        f = await save_upload(db, attachment, owner_id=actor.id, purpose="leave",
                              allowed=DOCUMENTS, max_bytes=5 * MB)
        leave.attachment_file_id = f.id
    span = (f"{from_date}" if from_date == to_date else f"{from_date} to {to_date}")
    notify(db, responsible_staff(db, prof), "leave_submitted", "New leave application",
           f"{actor.display_name} ({prof.roll_number}) applied for {TYPES[type].lower()} leave "
           f"({span}): {reason.strip()}", link="/staff/leaves", email=True)
    audit(db, actor, "leave_applied_for", target_type="leave_request", target_id=leave.id,
          detail={"type": type, "from": from_date, "to": to_date}, request=request)
    db.commit()
    return _out(db, leave)


@router.post("/me/leaves/{leave_id}")
async def edit_leave(
    leave_id: int, request: Request,
    type: str = Form(...), from_date: date = Form(...), to_date: date = Form(...),
    reason: str = Form(...), explanation: Optional[str] = Form(None),
    session_ids: Optional[str] = Form(None), attachment: Optional[UploadFile] = File(None),
    remove_attachment: bool = Form(False),
    db: Session = Depends(get_db), actor: User = Depends(current_user),
):
    """Edit while pending (multipart so the attachment can be replaced)."""
    leave = db.get(LeaveRequest, leave_id)
    if leave is None or leave.requester_id != actor.id:
        raise HTTPException(404, "leave not found")
    if leave.status != LeaveStatus.PENDING.value:
        raise HTTPException(409, "Only a pending application can be edited.")
    ids = _parse_ids(session_ids)
    _validate(db, actor, type_=type, from_date=from_date, to_date=to_date, reason=reason,
              explanation=explanation, session_ids=ids, exclude_id=leave.id)
    leave.type, leave.from_date, leave.to_date = type, from_date, to_date
    leave.reason, leave.explanation = reason.strip(), (explanation or "").strip() or None
    leave.session_ids = json.dumps(ids) if ids else None
    leave.updated_at = utcnow()
    if remove_attachment and leave.attachment_file_id:
        delete_file(db, db.get(StoredFile, leave.attachment_file_id))
        leave.attachment_file_id = None
    if attachment is not None and attachment.filename:
        f = await save_upload(db, attachment, owner_id=actor.id, purpose="leave",
                              allowed=DOCUMENTS, max_bytes=5 * MB)
        if leave.attachment_file_id:
            delete_file(db, db.get(StoredFile, leave.attachment_file_id))
        leave.attachment_file_id = f.id
    audit(db, actor, "leave_edited", target_type="leave_request", target_id=leave.id,
          request=request)
    db.commit()
    return _out(db, leave)


@router.delete("/me/leaves/{leave_id}")
def cancel_leave(leave_id: int, request: Request, db: Session = Depends(get_db),
                 actor: User = Depends(current_user)):
    leave = db.get(LeaveRequest, leave_id)
    if leave is None or leave.requester_id != actor.id:
        raise HTTPException(404, "leave not found")
    if leave.status != LeaveStatus.PENDING.value:
        raise HTTPException(409, "Only a pending application can be cancelled.")
    leave.status = LeaveStatus.CANCELLED.value
    leave.updated_at = utcnow()
    audit(db, actor, "leave_cancelled", target_type="leave_request", target_id=leave.id,
          request=request)
    db.commit()
    return _out(db, leave)


# ---------------------------------------------------------------- authority

@router.get("/leaves")
def list_leaves(status: Optional[str] = "pending", q: Optional[str] = None,
                type: Optional[str] = None, section_id: Optional[int] = None,
                date_from: Optional[date] = None, date_to: Optional[date] = None,
                page: int = 1, page_size: int = 50,
                db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    stmt = (select(LeaveRequest)
            .join(StudentProfile, StudentProfile.user_id == LeaveRequest.requester_id)
            .join(User, User.id == LeaveRequest.requester_id)
            .where(student_scope_clause(db, actor)))
    if status:
        stmt = stmt.where(LeaveRequest.status == status)
    if type:
        stmt = stmt.where(LeaveRequest.type == type)
    if section_id:
        stmt = stmt.where(StudentProfile.section_id == section_id)
    if date_from:
        stmt = stmt.where(LeaveRequest.to_date >= date_from)
    if date_to:
        stmt = stmt.where(LeaveRequest.from_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.display_name.ilike(like), StudentProfile.roll_number.ilike(like),
                              LeaveRequest.reason.ilike(like)))
    page_size = max(10, min(200, page_size))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(LeaveRequest.created_at.desc())
                      .offset((max(1, page) - 1) * page_size).limit(page_size))
    return {"rows": [_out(db, l, with_student=True) for l in rows],
            "meta": {"page": max(1, page), "page_size": page_size, "total": total,
                     "pages": (total + page_size - 1) // page_size}}


class DecisionIn(BaseModel):
    remark: Optional[str] = Field(None, max_length=400)


def _decide(db: Session, leave: LeaveRequest, actor: User, approve: bool,
            remark: Optional[str], request: Optional[Request]) -> int:
    if leave.status != LeaveStatus.PENDING.value:
        raise HTTPException(409, f"This application is already {leave.status}.")
    assert_can_manage_student(db, actor, leave.requester_id)
    if not approve and not (remark and len(remark.strip()) >= 3):
        raise HTTPException(422, detail={"field": "remark",
                                         "message": "Give the student a reason for the rejection."})
    leave.status = LeaveStatus.APPROVED.value if approve else LeaveStatus.REJECTED.value
    leave.approver_id = actor.id
    leave.decided_at = utcnow()
    leave.comment = (remark or "").strip() or None
    changed = apply_leave(db, leave, cfg, actor) if approve else 0
    span = (f"{leave.from_date}" if leave.from_date == leave.to_date
            else f"{leave.from_date} to {leave.to_date}")
    notify(db, [leave.requester_id], f"leave_{leave.status}",
           f"Leave {leave.status}",
           f"Your {TYPES.get(leave.type, leave.type).lower()} leave ({span}) was {leave.status} "
           f"by {actor.display_name}." + (f" Remark: {leave.comment}" if leave.comment else "")
           + (f" {changed} recorded absence(s) changed to On leave." if changed else ""),
           link="/student/leaves", email=True)
    audit(db, actor, f"leave_{leave.status}", target_type="leave_request", target_id=leave.id,
          reason=leave.comment, detail={"records_changed": changed}, request=request)
    return changed


@router.post("/leaves/{leave_id}/approve")
def approve_leave(leave_id: int, body: DecisionIn, request: Request,
                  db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise HTTPException(404, "leave not found")
    changed = _decide(db, leave, actor, True, body.remark, request)
    db.commit()
    return {**_out(db, leave, with_student=True), "records_changed": changed}


@router.post("/leaves/{leave_id}/reject")
def reject_leave(leave_id: int, body: DecisionIn, request: Request,
                 db: Session = Depends(get_db), actor: User = Depends(require_staff)):
    leave = db.get(LeaveRequest, leave_id)
    if leave is None:
        raise HTTPException(404, "leave not found")
    _decide(db, leave, actor, False, body.remark, request)
    db.commit()
    return _out(db, leave, with_student=True)


class BulkIn(BaseModel):
    ids: List[int] = Field(min_length=1, max_length=200)
    remark: Optional[str] = Field(None, max_length=400)


@router.post("/leaves/bulk-approve")
def bulk_approve(body: BulkIn, request: Request, db: Session = Depends(get_db),
                 actor: User = Depends(require_staff)):
    """All-or-nothing: if any one cannot be approved, none are."""
    leaves = [db.get(LeaveRequest, i) for i in dict.fromkeys(body.ids)]
    if any(l is None for l in leaves):
        raise HTTPException(404, "one of the applications was not found")
    changed = 0
    try:
        for l in leaves:
            changed += _decide(db, l, actor, True, body.remark, request)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    return {"approved": len(leaves), "records_changed": changed}
