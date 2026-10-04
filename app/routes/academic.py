"""Academic structure: branches, programs, batches, sections (class groups), subjects, rooms,
holidays, terms, teacher assignments and the weekly timetable.

Write access:
    super admin  everything
    HOD          their own branch: programs, sections, subjects, assignments, timetable,
                 branch holidays, rooms
    teacher      read; timetable slots for classes they are assigned to
Batches and academic terms are organisation-wide and therefore super-admin only.

Deletes refuse while anything still depends on the row ("Branch CSE still has 120 students"),
because a cascade here would silently orphan or erase attendance history.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import audit
from app.auth import (
    current_user,
    is_admin,
    is_faculty,
    is_super_admin,
    require_admin,
    require_staff,
    require_super_admin,
)
from app.db import get_db
from app.models import (
    AcademicTerm,
    Batch,
    Camera,
    ClassSession,
    Department,
    FacultyAssignment,
    Holiday,
    Program,
    Role,
    Room,
    Section,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
)
from app.scope import manageable_section_ids, section_department_id

router = APIRouter(prefix="/api", tags=["academic"])

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ------------------------------------------------------------------ helpers

def _dept_guard(actor: User, department_id: Optional[int]) -> None:
    """HODs write only inside their own branch; super admins anywhere."""
    if is_super_admin(actor):
        return
    if not is_admin(actor) or actor.department_id is None or actor.department_id != department_id:
        raise HTTPException(403, "you can only change your own branch")


def _commit(db: Session, conflict: str) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, conflict)


def _flush(db: Session, conflict: str) -> None:
    """Flush to get an id, turning a uniqueness clash into the same 409 `_commit` gives."""
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, conflict)


def _refuse_if(count: int, message: str) -> None:
    if count:
        raise HTTPException(409, message.format(n=count))


def section_label(sec: Section) -> str:
    prog = sec.program
    dept = prog.department.code if prog and prog.department else ""
    batch = f" {sec.batch.label}" if sec.batch else ""
    return f"{dept} Y{sec.year}-{sec.name}{batch}".strip()


def _section_out(sec: Section, students: int = 0) -> dict:
    return {
        "id": sec.id, "name": sec.name, "year": sec.year, "semester": sec.semester,
        "program_id": sec.program_id, "program": sec.program.name if sec.program else None,
        "department_id": sec.program.department_id if sec.program else None,
        "department_code": sec.program.department.code if sec.program else None,
        "batch_id": sec.batch_id, "batch": sec.batch.label if sec.batch else None,
        "label": section_label(sec), "students": students,
    }


def _student_counts(db: Session) -> dict:
    return dict(db.execute(
        select(StudentProfile.section_id, func.count())
        .join(User, User.id == StudentProfile.user_id)
        .where(User.deleted_at.is_(None))
        .group_by(StudentProfile.section_id)).all())


# --------------------------------------------------------------- departments

class DepartmentIn(BaseModel):
    code: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("use letters and digits only, e.g. CSE")
        return v


@router.get("/departments")
def list_departments(db: Session = Depends(get_db), _: User = Depends(current_user)):
    counts = dict(db.execute(select(StudentProfile.department_id, func.count())
                             .group_by(StudentProfile.department_id)).all())
    return [{"id": d.id, "code": d.code, "name": d.name, "students": counts.get(d.id, 0)}
            for d in db.scalars(select(Department).order_by(Department.code))]


@router.post("/departments", status_code=201)
def create_department(body: DepartmentIn, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_super_admin)):
    d = Department(code=body.code, name=body.name.strip())
    db.add(d)
    _flush(db, f"a branch with code {body.code} already exists")
    # Every branch gets a default program so sections can be created straight away.
    db.add(Program(department_id=d.id, name=f"B.Tech {body.code}", duration_years=4))
    audit(db, actor, "branch_created", target_type="department", target_id=d.id,
          detail={"code": d.code}, request=request)
    _commit(db, f"a branch with code {body.code} already exists")
    return {"id": d.id, "code": d.code, "name": d.name}


@router.patch("/departments/{dept_id}")
def update_department(dept_id: int, body: DepartmentIn, request: Request,
                      db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    d = db.get(Department, dept_id)
    if d is None:
        raise HTTPException(404, "branch not found")
    _dept_guard(actor, d.id)
    before = {"code": d.code, "name": d.name}
    d.code, d.name = body.code, body.name.strip()
    audit(db, actor, "branch_updated", target_type="department", target_id=d.id,
          detail={"before": before, "after": {"code": d.code, "name": d.name}}, request=request)
    _commit(db, f"a branch with code {body.code} already exists")
    return {"id": d.id, "code": d.code, "name": d.name}


@router.delete("/departments/{dept_id}")
def delete_department(dept_id: int, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_super_admin)):
    d = db.get(Department, dept_id)
    if d is None:
        raise HTTPException(404, "branch not found")
    sec_ids = [s for s in db.scalars(select(Section.id).join(Program).where(
        Program.department_id == dept_id))]
    n_students = db.scalar(select(func.count()).select_from(StudentProfile).where(or_(
        StudentProfile.department_id == dept_id,
        StudentProfile.section_id.in_(sec_ids or [-1])))) or 0
    _refuse_if(n_students, f"Branch {d.code} still has {{n}} student(s). Move or remove them "
                           f"before deleting the branch.")
    _refuse_if(len(sec_ids), f"Branch {d.code} still has {{n}} section(s). Delete them first.")
    _refuse_if(db.scalar(select(func.count()).select_from(Subject)
                         .where(Subject.department_id == dept_id)) or 0,
               f"Branch {d.code} still has {{n}} subject(s). Delete them first.")
    _refuse_if(db.scalar(select(func.count()).select_from(User).where(
        User.department_id == dept_id, User.deleted_at.is_(None))) or 0,
        f"{{n}} staff account(s) belong to branch {d.code}. Reassign them first.")
    for p in db.scalars(select(Program).where(Program.department_id == dept_id)):
        db.delete(p)
    db.delete(d)
    audit(db, actor, "branch_deleted", target_type="department", target_id=dept_id,
          detail={"code": d.code}, request=request)
    db.commit()
    return {"deleted": dept_id}


# ------------------------------------------------------------------ programs

class ProgramIn(BaseModel):
    department_id: int
    name: str = Field(min_length=1, max_length=120)
    duration_years: int = Field(4, ge=1, le=6)


@router.get("/programs")
def list_programs(department_id: Optional[int] = None, db: Session = Depends(get_db),
                  _: User = Depends(current_user)):
    stmt = select(Program).order_by(Program.name)
    if department_id:
        stmt = stmt.where(Program.department_id == department_id)
    return [{"id": p.id, "department_id": p.department_id, "name": p.name,
             "duration_years": p.duration_years} for p in db.scalars(stmt)]


@router.post("/programs", status_code=201)
def create_program(body: ProgramIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    if db.get(Department, body.department_id) is None:
        raise HTTPException(404, "branch not found")
    _dept_guard(actor, body.department_id)
    p = Program(department_id=body.department_id, name=body.name.strip(),
                duration_years=body.duration_years)
    db.add(p)
    _flush(db, "that program already exists in this branch")
    audit(db, actor, "program_created", target_type="program", target_id=p.id, request=request)
    _commit(db, "that program already exists in this branch")
    return {"id": p.id, "department_id": p.department_id, "name": p.name,
            "duration_years": p.duration_years}


@router.patch("/programs/{program_id}")
def update_program(program_id: int, body: ProgramIn, request: Request,
                   db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    p = db.get(Program, program_id)
    if p is None:
        raise HTTPException(404, "program not found")
    _dept_guard(actor, p.department_id)
    too_high = db.scalar(select(func.count()).select_from(Section).where(
        Section.program_id == p.id, Section.year > body.duration_years)) or 0
    _refuse_if(too_high, "{n} section(s) are in a year beyond the new duration.")
    p.name, p.duration_years = body.name.strip(), body.duration_years
    audit(db, actor, "program_updated", target_type="program", target_id=p.id, request=request)
    _commit(db, "that program already exists in this branch")
    return {"id": p.id, "department_id": p.department_id, "name": p.name,
            "duration_years": p.duration_years}


@router.delete("/programs/{program_id}")
def delete_program(program_id: int, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    p = db.get(Program, program_id)
    if p is None:
        raise HTTPException(404, "program not found")
    _dept_guard(actor, p.department_id)
    _refuse_if(db.scalar(select(func.count()).select_from(Section)
                         .where(Section.program_id == p.id)) or 0,
               "This program still has {n} section(s). Delete them first.")
    db.delete(p)
    audit(db, actor, "program_deleted", target_type="program", target_id=program_id,
          request=request)
    db.commit()
    return {"deleted": program_id}


# ------------------------------------------------------------------- batches

class BatchIn(BaseModel):
    start_year: int = Field(ge=1990, le=2100)
    end_year: int = Field(ge=1990, le=2110)
    label: Optional[str] = Field(None, max_length=32)


@router.get("/batches")
def list_batches(db: Session = Depends(get_db), _: User = Depends(current_user)):
    counts = dict(db.execute(select(StudentProfile.batch_id, func.count())
                             .group_by(StudentProfile.batch_id)).all())
    return [{"id": b.id, "label": b.label, "start_year": b.start_year, "end_year": b.end_year,
             "students": counts.get(b.id, 0)}
            for b in db.scalars(select(Batch).order_by(Batch.start_year.desc()))]


def _batch_label(body: BatchIn) -> str:
    if body.end_year <= body.start_year:
        raise HTTPException(422, "The batch must end after it starts.")
    return (body.label or f"{body.start_year}-{body.end_year}").strip()


@router.post("/batches", status_code=201)
def create_batch(body: BatchIn, request: Request, db: Session = Depends(get_db),
                 actor: User = Depends(require_super_admin)):
    b = Batch(label=_batch_label(body), start_year=body.start_year, end_year=body.end_year)
    db.add(b)
    _flush(db, f"batch {b.label} already exists")
    audit(db, actor, "batch_created", target_type="batch", target_id=b.id, request=request)
    _commit(db, f"batch {b.label} already exists")
    return {"id": b.id, "label": b.label, "start_year": b.start_year, "end_year": b.end_year}


@router.patch("/batches/{batch_id}")
def update_batch(batch_id: int, body: BatchIn, request: Request, db: Session = Depends(get_db),
                 actor: User = Depends(require_super_admin)):
    b = db.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    b.label, b.start_year, b.end_year = _batch_label(body), body.start_year, body.end_year
    audit(db, actor, "batch_updated", target_type="batch", target_id=b.id, request=request)
    _commit(db, f"batch {b.label} already exists")
    return {"id": b.id, "label": b.label, "start_year": b.start_year, "end_year": b.end_year}


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: int, request: Request, db: Session = Depends(get_db),
                 actor: User = Depends(require_super_admin)):
    b = db.get(Batch, batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    n = db.scalar(select(func.count()).select_from(StudentProfile)
                  .join(User, User.id == StudentProfile.user_id)
                  .where(StudentProfile.batch_id == batch_id, User.deleted_at.is_(None))) or 0
    _refuse_if(n, f"Batch {b.label} still has {{n}} student(s). Move or remove them before "
                  f"deleting the batch.")
    _refuse_if(db.scalar(select(func.count()).select_from(Section)
                         .where(Section.batch_id == batch_id)) or 0,
               f"Batch {b.label} still has {{n}} section(s). Delete them first.")
    db.delete(b)
    audit(db, actor, "batch_deleted", target_type="batch", target_id=batch_id,
          detail={"label": b.label}, request=request)
    db.commit()
    return {"deleted": batch_id}


# ------------------------------------------------------------------ sections

class SectionIn(BaseModel):
    program_id: Optional[int] = None
    department_id: Optional[int] = None       # convenience: the branch's first program
    batch_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=32)
    year: int = Field(ge=1, le=6)
    semester: int = Field(ge=1, le=12)


def _resolve_program(db: Session, body: SectionIn) -> Program:
    if body.program_id:
        p = db.get(Program, body.program_id)
    elif body.department_id:
        p = db.scalars(select(Program).where(Program.department_id == body.department_id)
                       .order_by(Program.id)).first()
        if p is None and db.get(Department, body.department_id) is not None:
            d = db.get(Department, body.department_id)
            p = Program(department_id=d.id, name=f"B.Tech {d.code}", duration_years=4)
            db.add(p)
            db.flush()
    else:
        p = None
    if p is None:
        raise HTTPException(422, "Choose the branch (or program) for this section.")
    if body.year > p.duration_years:
        raise HTTPException(422, f"{p.name} runs {p.duration_years} year(s); year {body.year} "
                                 f"does not exist.")
    return p


@router.get("/sections")
def list_sections(department_id: Optional[int] = None, batch_id: Optional[int] = None,
                  year: Optional[int] = None, mine: bool = False,
                  db: Session = Depends(get_db), actor: User = Depends(current_user)):
    stmt = select(Section).join(Program, Program.id == Section.program_id)
    if department_id:
        stmt = stmt.where(Program.department_id == department_id)
    if batch_id:
        stmt = stmt.where(Section.batch_id == batch_id)
    if year:
        stmt = stmt.where(Section.year == year)
    if mine:
        allowed = manageable_section_ids(db, actor)
        if allowed is not None:
            stmt = stmt.where(Section.id.in_(allowed or {-1}))
    counts = _student_counts(db)
    rows = [_section_out(s, counts.get(s.id, 0)) for s in db.scalars(stmt)]
    rows.sort(key=lambda r: r["label"])
    return rows


@router.post("/sections", status_code=201)
def create_section(body: SectionIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    p = _resolve_program(db, body)
    _dept_guard(actor, p.department_id)
    if body.batch_id and db.get(Batch, body.batch_id) is None:
        raise HTTPException(404, "batch not found")
    s = Section(program_id=p.id, name=body.name.strip().upper(), year=body.year,
                semester=body.semester, batch_id=body.batch_id)
    db.add(s)
    _flush(db, "that section already exists for this year and semester")
    audit(db, actor, "section_created", target_type="section", target_id=s.id, request=request)
    _commit(db, "that section already exists for this year and semester")
    db.refresh(s)
    return _section_out(s)


@router.patch("/sections/{section_id}")
def update_section(section_id: int, body: SectionIn, request: Request,
                   db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    s = db.get(Section, section_id)
    if s is None:
        raise HTTPException(404, "section not found")
    _dept_guard(actor, s.program.department_id)
    p = _resolve_program(db, body)
    _dept_guard(actor, p.department_id)
    s.program_id, s.name, s.year, s.semester, s.batch_id = (
        p.id, body.name.strip().upper(), body.year, body.semester, body.batch_id)
    # Keep the students' denormalised class fields in step with the section.
    for prof in db.scalars(select(StudentProfile).where(StudentProfile.section_id == s.id)):
        prof.year, prof.batch_id, prof.department_id = s.year, s.batch_id, p.department_id
    audit(db, actor, "section_updated", target_type="section", target_id=s.id, request=request)
    _commit(db, "that section already exists for this year and semester")
    db.refresh(s)
    return _section_out(s, _student_counts(db).get(s.id, 0))


@router.delete("/sections/{section_id}")
def delete_section(section_id: int, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    s = db.get(Section, section_id)
    if s is None:
        raise HTTPException(404, "section not found")
    _dept_guard(actor, s.program.department_id)
    _refuse_if(_student_counts(db).get(section_id, 0),
               f"Section {section_label(s)} still has {{n}} student(s). Move them first.")
    _refuse_if(db.scalar(select(func.count()).select_from(ClassSession)
                         .where(ClassSession.section_id == section_id)) or 0,
               "This section has {n} recorded lecture(s); it cannot be deleted without "
               "erasing their attendance context.")
    db.delete(s)
    audit(db, actor, "section_deleted", target_type="section", target_id=section_id,
          request=request)
    db.commit()
    return {"deleted": section_id}


# ------------------------------------------------------------------ subjects

class SubjectIn(BaseModel):
    code: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=1, max_length=160)
    department_id: int
    year: Optional[int] = Field(None, ge=1, le=6)
    semester: Optional[int] = Field(None, ge=1, le=12)
    credits: int = Field(3, ge=0, le=20)


def _subject_out(s: Subject) -> dict:
    return {"id": s.id, "code": s.code, "name": s.name, "department_id": s.department_id,
            "department_code": s.department.code if s.department else None,
            "year": s.year, "semester": s.semester, "credits": s.credits}


@router.get("/subjects")
def list_subjects(department_id: Optional[int] = None, year: Optional[int] = None,
                  semester: Optional[int] = None, db: Session = Depends(get_db),
                  _: User = Depends(current_user)):
    stmt = select(Subject).order_by(Subject.code)
    if department_id:
        stmt = stmt.where(Subject.department_id == department_id)
    if year:
        stmt = stmt.where(Subject.year == year)
    if semester:
        stmt = stmt.where(Subject.semester == semester)
    return [_subject_out(s) for s in db.scalars(stmt)]


@router.post("/subjects", status_code=201)
def create_subject(body: SubjectIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    if db.get(Department, body.department_id) is None:
        raise HTTPException(404, "branch not found")
    _dept_guard(actor, body.department_id)
    s = Subject(code=body.code.strip().upper(), name=body.name.strip(),
                department_id=body.department_id, year=body.year, semester=body.semester,
                credits=body.credits)
    db.add(s)
    _flush(db, f"subject code {s.code} is already in use")
    audit(db, actor, "subject_created", target_type="subject", target_id=s.id, request=request)
    _commit(db, f"subject code {s.code} is already in use")
    db.refresh(s)
    return _subject_out(s)


@router.patch("/subjects/{subject_id}")
def update_subject(subject_id: int, body: SubjectIn, request: Request,
                   db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    s = db.get(Subject, subject_id)
    if s is None:
        raise HTTPException(404, "subject not found")
    _dept_guard(actor, s.department_id)
    _dept_guard(actor, body.department_id)
    s.code, s.name, s.department_id = body.code.strip().upper(), body.name.strip(), body.department_id
    s.year, s.semester, s.credits = body.year, body.semester, body.credits
    audit(db, actor, "subject_updated", target_type="subject", target_id=s.id, request=request)
    _commit(db, f"subject code {s.code} is already in use")
    db.refresh(s)
    return _subject_out(s)


@router.delete("/subjects/{subject_id}")
def delete_subject(subject_id: int, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    s = db.get(Subject, subject_id)
    if s is None:
        raise HTTPException(404, "subject not found")
    _dept_guard(actor, s.department_id)
    _refuse_if(db.scalar(select(func.count()).select_from(ClassSession)
                         .where(ClassSession.subject_id == subject_id)) or 0,
               f"{s.code} has {{n}} recorded lecture(s); deleting it would strip their "
               f"attendance of its subject.")
    _refuse_if(db.scalar(select(func.count()).select_from(TimetableSlot)
                         .where(TimetableSlot.subject_id == subject_id)) or 0,
               f"{s.code} is on the timetable {{n}} time(s). Remove those periods first.")
    for a in db.scalars(select(FacultyAssignment).where(FacultyAssignment.subject_id == subject_id)):
        db.delete(a)
    db.delete(s)
    audit(db, actor, "subject_deleted", target_type="subject", target_id=subject_id,
          detail={"code": s.code}, request=request)
    db.commit()
    return {"deleted": subject_id}


# --------------------------------------------------------------------- rooms

class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    building: Optional[str] = Field(None, max_length=120)
    capacity: Optional[int] = Field(None, ge=1, le=5000)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_m: Optional[float] = Field(None, ge=10, le=5000)


def _room_out(r: Room) -> dict:
    return {"id": r.id, "name": r.name, "building": r.building, "capacity": r.capacity,
            "latitude": r.latitude, "longitude": r.longitude, "radius_m": r.radius_m}


@router.get("/rooms")
def list_rooms(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_room_out(r) for r in db.scalars(select(Room).order_by(Room.name))]


@router.post("/rooms", status_code=201)
def create_room(body: RoomIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(422, "Give both latitude and longitude, or neither.")
    r = Room(**{**body.model_dump(), "name": body.name.strip()})
    db.add(r)
    _flush(db, f"room {r.name} already exists")
    audit(db, actor, "room_created", target_type="room", target_id=r.id, request=request)
    _commit(db, f"room {r.name} already exists")
    return _room_out(r)


@router.patch("/rooms/{room_id}")
def update_room(room_id: int, body: RoomIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    r = db.get(Room, room_id)
    if r is None:
        raise HTTPException(404, "room not found")
    if (body.latitude is None) != (body.longitude is None):
        raise HTTPException(422, "Give both latitude and longitude, or neither.")
    old = r.name
    for k, v in body.model_dump().items():
        setattr(r, k, v.strip() if isinstance(v, str) and k == "name" else v)
    if r.name != old:
        # Slots and cameras refer to rooms by name; rename them together.
        for slot in db.scalars(select(TimetableSlot).where(TimetableSlot.room == old)):
            slot.room = r.name
        for cam in db.scalars(select(Camera).where(Camera.room == old)):
            cam.room = r.name
    audit(db, actor, "room_updated", target_type="room", target_id=r.id, request=request)
    _commit(db, f"room {r.name} already exists")
    return _room_out(r)


@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    r = db.get(Room, room_id)
    if r is None:
        raise HTTPException(404, "room not found")
    _refuse_if(db.scalar(select(func.count()).select_from(TimetableSlot)
                         .where(TimetableSlot.room == r.name)) or 0,
               f"{r.name} is used by {{n}} timetable period(s). Move them first.")
    _refuse_if(db.scalar(select(func.count()).select_from(Camera)
                         .where(Camera.room == r.name)) or 0,
               f"{{n}} camera(s) are installed in {r.name}. Move or delete them first.")
    db.delete(r)
    audit(db, actor, "room_deleted", target_type="room", target_id=room_id, request=request)
    db.commit()
    return {"deleted": room_id}


# ------------------------------------------------------------------ holidays

class HolidayIn(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=160)
    department_code: Optional[str] = None      # None = whole college


@router.get("/holidays")
def list_holidays(year: Optional[int] = None, db: Session = Depends(get_db),
                  _: User = Depends(current_user)):
    stmt = select(Holiday).order_by(Holiday.date)
    if year:
        stmt = stmt.where(Holiday.date >= date(year, 1, 1), Holiday.date <= date(year, 12, 31))
    return [{"id": h.id, "date": h.date.isoformat(), "name": h.name,
             "department_code": h.applies_to} for h in db.scalars(stmt)]


@router.post("/holidays", status_code=201)
def create_holiday(body: HolidayIn, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    scope = (body.department_code or "").strip().upper() or None
    if not is_super_admin(actor):
        dept = db.get(Department, actor.department_id) if actor.department_id else None
        if dept is None or scope != dept.code:
            raise HTTPException(403, "Heads of department can only declare holidays for their "
                                     "own branch.")
    elif scope and db.scalars(select(Department).where(Department.code == scope)).first() is None:
        raise HTTPException(404, f"no branch with code {scope}")
    h = Holiday(date=body.date, name=body.name.strip(), applies_to=scope)
    db.add(h)
    _flush(db, "that date is already a holiday for this scope")
    audit(db, actor, "holiday_created", target_type="holiday", target_id=h.id,
          detail={"date": body.date.isoformat(), "scope": scope or "all"}, request=request)
    _commit(db, "that date is already a holiday for this scope")
    return {"id": h.id, "date": h.date.isoformat(), "name": h.name, "department_code": scope}


@router.delete("/holidays/{holiday_id}")
def delete_holiday(holiday_id: int, request: Request, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    h = db.get(Holiday, holiday_id)
    if h is None:
        raise HTTPException(404, "holiday not found")
    if not is_super_admin(actor):
        dept = db.get(Department, actor.department_id) if actor.department_id else None
        if dept is None or h.applies_to != dept.code:
            raise HTTPException(403, "you can only remove your own branch's holidays")
    db.delete(h)
    audit(db, actor, "holiday_deleted", target_type="holiday", target_id=holiday_id,
          request=request)
    db.commit()
    return {"deleted": holiday_id}


def is_holiday(db: Session, on: date, department_id: Optional[int]) -> Optional[str]:
    """The holiday's name if `on` is a holiday for the whole college or this branch."""
    code = None
    if department_id:
        d = db.get(Department, department_id)
        code = d.code if d else None
    h = db.scalars(select(Holiday).where(
        Holiday.date == on, or_(Holiday.applies_to.is_(None),
                                Holiday.applies_to == code if code else False))).first()
    return h.name if h else None


# --------------------------------------------------------------------- terms

class TermIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    start_date: date
    end_date: date
    is_active: bool = False


def _term_out(t: AcademicTerm) -> dict:
    return {"id": t.id, "name": t.name, "start_date": t.start_date.isoformat(),
            "end_date": t.end_date.isoformat(), "is_active": t.is_active}


@router.get("/terms")
def list_terms(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [_term_out(t) for t in db.scalars(select(AcademicTerm)
                                              .order_by(AcademicTerm.start_date.desc()))]


def _activate(db: Session, term: AcademicTerm) -> None:
    for other in db.scalars(select(AcademicTerm).where(AcademicTerm.id != term.id,
                                                       AcademicTerm.is_active.is_(True))):
        other.is_active = False
    term.is_active = True


@router.post("/terms", status_code=201)
def create_term(body: TermIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_super_admin)):
    if body.end_date <= body.start_date:
        raise HTTPException(422, "The term must end after it starts.")
    t = AcademicTerm(name=body.name.strip(), start_date=body.start_date, end_date=body.end_date,
                     is_active=False)
    db.add(t)
    _flush(db, f"a term named {t.name} already exists")
    if body.is_active:
        _activate(db, t)
    audit(db, actor, "term_created", target_type="term", target_id=t.id, request=request)
    _commit(db, f"a term named {t.name} already exists")
    return _term_out(t)


@router.patch("/terms/{term_id}")
def update_term(term_id: int, body: TermIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_super_admin)):
    t = db.get(AcademicTerm, term_id)
    if t is None:
        raise HTTPException(404, "term not found")
    if body.end_date <= body.start_date:
        raise HTTPException(422, "The term must end after it starts.")
    t.name, t.start_date, t.end_date = body.name.strip(), body.start_date, body.end_date
    if body.is_active:
        _activate(db, t)
    else:
        t.is_active = False
    audit(db, actor, "term_updated", target_type="term", target_id=t.id, request=request)
    _commit(db, f"a term named {t.name} already exists")
    return _term_out(t)


@router.delete("/terms/{term_id}")
def delete_term(term_id: int, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_super_admin)):
    t = db.get(AcademicTerm, term_id)
    if t is None:
        raise HTTPException(404, "term not found")
    _refuse_if(db.scalar(select(func.count()).select_from(ClassSession)
                         .where(ClassSession.term_id == term_id)) or 0,
               "This term has {n} recorded lecture(s) and cannot be deleted.")
    _refuse_if(db.scalar(select(func.count()).select_from(TimetableSlot)
                         .where(TimetableSlot.term_id == term_id)) or 0,
               "This term has {n} timetable period(s). Remove them first.")
    for a in db.scalars(select(FacultyAssignment).where(FacultyAssignment.term_id == term_id)):
        db.delete(a)
    db.delete(t)
    audit(db, actor, "term_deleted", target_type="term", target_id=term_id, request=request)
    db.commit()
    return {"deleted": term_id}


def active_term(db: Session) -> Optional[AcademicTerm]:
    t = db.scalars(select(AcademicTerm).where(AcademicTerm.is_active.is_(True))).first()
    return t or db.scalars(select(AcademicTerm).order_by(AcademicTerm.start_date.desc())).first()


# --------------------------------------------------------------- assignments

class AssignmentIn(BaseModel):
    faculty_id: int
    subject_id: int
    section_id: int
    term_id: Optional[int] = None


def _assignment_out(a: FacultyAssignment) -> dict:
    return {"id": a.id, "faculty_id": a.faculty_id,
            "faculty_name": a.faculty.display_name if a.faculty else None,
            "subject_id": a.subject_id, "subject_code": a.subject.code if a.subject else None,
            "subject_name": a.subject.name if a.subject else None,
            "section_id": a.section_id,
            "section_label": section_label(a.section) if a.section else None,
            "term_id": a.term_id}


@router.get("/assignments")
def list_assignments(faculty_id: Optional[int] = None, section_id: Optional[int] = None,
                     mine: bool = False, db: Session = Depends(get_db),
                     actor: User = Depends(require_staff)):
    stmt = select(FacultyAssignment)
    if mine or is_faculty(actor):
        stmt = stmt.where(FacultyAssignment.faculty_id == actor.id)
    elif is_admin(actor) and not is_super_admin(actor):
        stmt = stmt.join(Subject, Subject.id == FacultyAssignment.subject_id) \
                   .where(Subject.department_id == actor.department_id)
    if faculty_id:
        stmt = stmt.where(FacultyAssignment.faculty_id == faculty_id)
    if section_id:
        stmt = stmt.where(FacultyAssignment.section_id == section_id)
    return [_assignment_out(a) for a in db.scalars(stmt)]


def _check_teacher(db: Session, faculty_id: int) -> User:
    t = db.get(User, faculty_id)
    role = t.role.value if t is not None and isinstance(t.role, Role) else (t.role if t else None)
    if t is None or t.deleted_at is not None or role not in ("faculty", "admin", "super_admin"):
        raise HTTPException(404, "teacher not found")
    return t


@router.post("/assignments", status_code=201)
def create_assignment(body: AssignmentIn, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_admin)):
    _check_teacher(db, body.faculty_id)
    subj = db.get(Subject, body.subject_id)
    sec = db.get(Section, body.section_id)
    if subj is None or sec is None:
        raise HTTPException(404, "subject or section not found")
    _dept_guard(actor, subj.department_id)
    term = db.get(AcademicTerm, body.term_id) if body.term_id else active_term(db)
    if term is None:
        raise HTTPException(422, "Create an academic term first (Setup → Terms).")
    a = FacultyAssignment(faculty_id=body.faculty_id, subject_id=subj.id, section_id=sec.id,
                          term_id=term.id)
    db.add(a)
    _flush(db, "this teacher is already assigned to that subject and section")
    audit(db, actor, "assignment_created", target_type="assignment", target_id=a.id,
          detail=body.model_dump(), request=request)
    _commit(db, "this teacher is already assigned to that subject and section")
    db.refresh(a)
    return _assignment_out(a)


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: int, request: Request, db: Session = Depends(get_db),
                      actor: User = Depends(require_admin)):
    a = db.get(FacultyAssignment, assignment_id)
    if a is None:
        raise HTTPException(404, "assignment not found")
    _dept_guard(actor, a.subject.department_id if a.subject else None)
    db.delete(a)
    audit(db, actor, "assignment_deleted", target_type="assignment", target_id=assignment_id,
          request=request)
    db.commit()
    return {"deleted": assignment_id}


# ----------------------------------------------------------------- timetable

def _parse_hhmm(v: str) -> int:
    try:
        h, m = v.split(":")
        minute = int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        raise ValueError("use HH:MM, e.g. 09:30")
    if not 0 <= minute < 24 * 60:
        raise ValueError("time must be within the day")
    return minute


class SlotIn(BaseModel):
    section_id: int
    subject_id: int
    faculty_id: int
    day_of_week: int = Field(ge=0, le=6)
    start_time: str
    end_time: str
    room: str = Field(min_length=1, max_length=80)
    term_id: Optional[int] = None

    @field_validator("start_time", "end_time")
    @classmethod
    def _time(cls, v: str) -> str:
        _parse_hhmm(v)
        return v


def _slot_out(s: TimetableSlot) -> dict:
    return {"id": s.id, "section_id": s.section_id,
            "section_label": section_label(s.section) if s.section else None,
            "subject_id": s.subject_id, "subject_code": s.subject.code if s.subject else None,
            "subject_name": s.subject.name if s.subject else None,
            "faculty_id": s.faculty_id,
            "faculty_name": s.faculty.display_name if s.faculty else None,
            "day_of_week": s.day_of_week, "day": DAYS[s.day_of_week],
            "start_time": s.start_time, "end_time": s.end_time, "room": s.room,
            "term_id": s.term_id}


def _overlaps(db: Session, body: SlotIn, start: int, end: int, term_id: int,
              exclude_id: Optional[int]) -> Optional[str]:
    clash = select(TimetableSlot).where(
        TimetableSlot.term_id == term_id, TimetableSlot.day_of_week == body.day_of_week,
        TimetableSlot.start_minute < end, TimetableSlot.end_minute > start)
    if exclude_id:
        clash = clash.where(TimetableSlot.id != exclude_id)
    for other in db.scalars(clash):
        if other.section_id == body.section_id:
            return f"This class already has {other.subject.code} at {other.start_time}–{other.end_time}."
        if other.faculty_id == body.faculty_id:
            return (f"{other.faculty.display_name} already teaches {other.subject.code} at "
                    f"{other.start_time}–{other.end_time}.")
        if other.room == body.room:
            return f"{body.room} is booked for {other.subject.code} at {other.start_time}–{other.end_time}."
    return None


def _slot_guard(db: Session, actor: User, body: SlotIn) -> None:
    """HOD/admin inside their branch; a teacher only for classes and subjects assigned to them."""
    subj = db.get(Subject, body.subject_id)
    sec = db.get(Section, body.section_id)
    if subj is None or sec is None:
        raise HTTPException(404, "subject or section not found")
    if is_admin(actor):
        _dept_guard(actor, subj.department_id)
        return
    if body.faculty_id != actor.id:
        raise HTTPException(403, "teachers can only schedule their own periods")
    assigned = db.scalars(select(FacultyAssignment.id).where(
        FacultyAssignment.faculty_id == actor.id, FacultyAssignment.subject_id == subj.id,
        FacultyAssignment.section_id == sec.id)).first()
    if assigned is None:
        raise HTTPException(403, "you are not assigned to teach this subject to this class")


def _validate_slot(db: Session, body: SlotIn, exclude_id: Optional[int] = None):
    start, end = _parse_hhmm(body.start_time), _parse_hhmm(body.end_time)
    if end <= start:
        raise HTTPException(422, "The period must end after it starts.")
    _check_teacher(db, body.faculty_id)
    if db.scalars(select(Room).limit(1)).first() is not None and \
            db.scalars(select(Room).where(Room.name == body.room)).first() is None:
        raise HTTPException(422, f"Room {body.room} does not exist. Add it under Setup → Rooms.")
    term = db.get(AcademicTerm, body.term_id) if body.term_id else active_term(db)
    if term is None:
        raise HTTPException(422, "Create an academic term first (Setup → Terms).")
    clash = _overlaps(db, body, start, end, term.id, exclude_id)
    if clash:
        raise HTTPException(409, clash)
    return start, end, term


@router.get("/timetable")
def list_timetable(section_id: Optional[int] = None, faculty_id: Optional[int] = None,
                   mine: bool = False, db: Session = Depends(get_db),
                   actor: User = Depends(current_user)):
    stmt = select(TimetableSlot).order_by(TimetableSlot.day_of_week, TimetableSlot.start_minute)
    role = actor.role.value if isinstance(actor.role, Role) else str(actor.role)
    if role == "student":
        prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == actor.id)).first()
        stmt = stmt.where(TimetableSlot.section_id == (prof.section_id if prof and prof.section_id
                                                       else -1))
    elif role == "parent":
        raise HTTPException(403, "not available for parent accounts")
    else:
        if mine:
            stmt = stmt.where(TimetableSlot.faculty_id == actor.id)
        if section_id:
            stmt = stmt.where(TimetableSlot.section_id == section_id)
        if faculty_id:
            stmt = stmt.where(TimetableSlot.faculty_id == faculty_id)
    term = active_term(db)
    if term is not None:
        stmt = stmt.where(TimetableSlot.term_id == term.id)
    return [_slot_out(s) for s in db.scalars(stmt)]


@router.post("/timetable", status_code=201)
def create_slot(body: SlotIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_staff)):
    _slot_guard(db, actor, body)
    start, end, term = _validate_slot(db, body)
    # The teacher of a period is, by definition, assigned to that subject and class.
    if db.scalars(select(FacultyAssignment.id).where(
            FacultyAssignment.faculty_id == body.faculty_id,
            FacultyAssignment.subject_id == body.subject_id,
            FacultyAssignment.section_id == body.section_id,
            FacultyAssignment.term_id == term.id)).first() is None:
        db.add(FacultyAssignment(faculty_id=body.faculty_id, subject_id=body.subject_id,
                                 section_id=body.section_id, term_id=term.id))
    s = TimetableSlot(section_id=body.section_id, subject_id=body.subject_id,
                      faculty_id=body.faculty_id, term_id=term.id, day_of_week=body.day_of_week,
                      start_minute=start, end_minute=end, room=body.room.strip())
    db.add(s)
    _flush(db, "this class already has a period starting at that time")
    audit(db, actor, "timetable_slot_created", target_type="timetable_slot", target_id=s.id,
          detail=body.model_dump(), request=request)
    _commit(db, "this class already has a period starting at that time")
    db.refresh(s)
    return _slot_out(s)


@router.patch("/timetable/{slot_id}")
def update_slot(slot_id: int, body: SlotIn, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_staff)):
    s = db.get(TimetableSlot, slot_id)
    if s is None:
        raise HTTPException(404, "period not found")
    if not is_admin(actor) and s.faculty_id != actor.id:
        raise HTTPException(403, "you can only change your own periods")
    _slot_guard(db, actor, body)
    start, end, term = _validate_slot(db, body, exclude_id=slot_id)
    s.section_id, s.subject_id, s.faculty_id = body.section_id, body.subject_id, body.faculty_id
    s.day_of_week, s.start_minute, s.end_minute = body.day_of_week, start, end
    s.room, s.term_id = body.room.strip(), term.id
    audit(db, actor, "timetable_slot_updated", target_type="timetable_slot", target_id=s.id,
          detail=body.model_dump(), request=request)
    _commit(db, "this class already has a period starting at that time")
    db.refresh(s)
    return _slot_out(s)


@router.delete("/timetable/{slot_id}")
def delete_slot(slot_id: int, request: Request, db: Session = Depends(get_db),
                actor: User = Depends(require_staff)):
    s = db.get(TimetableSlot, slot_id)
    if s is None:
        raise HTTPException(404, "period not found")
    if is_admin(actor):
        _dept_guard(actor, s.subject.department_id if s.subject else None)
    elif s.faculty_id != actor.id:
        raise HTTPException(403, "you can only remove your own periods")
    db.delete(s)                         # sessions keep their own copy of subject/section
    audit(db, actor, "timetable_slot_deleted", target_type="timetable_slot",
          target_id=slot_id, request=request)
    db.commit()
    return {"deleted": slot_id}


# ---------------------------------------------------------------- public

@router.get("/public/academic-options")
def academic_options(db: Session = Depends(get_db)):
    """What the sign-up form's dropdowns offer. Public, and deliberately minimal: names of
    branches, batches and sections, never people."""
    sections = []
    for s in db.scalars(select(Section)):
        dept_id = s.program.department_id if s.program else None
        sections.append({"id": s.id, "name": s.name, "year": s.year, "semester": s.semester,
                         "department_id": dept_id, "batch_id": s.batch_id,
                         "label": section_label(s)})
    sections.sort(key=lambda x: x["label"])
    max_years = dict(db.execute(select(Program.department_id, func.max(Program.duration_years))
                                .group_by(Program.department_id)).all())
    from app import settings_service
    from app.runtime import cfg

    s_all = settings_service.all_settings(db, cfg)
    return {
        "org_name": s_all["org_name"],
        "retention": {"review_days": s_all["review_retention_days"],
                      "thumbnail_days": s_all["thumbnail_retention_days"]},
        "policy": {"present_window_min": s_all["present_window_min"],
                   "late_window_min": s_all["late_window_min"],
                   "min_attendance_pct": s_all["min_attendance_pct"],
                   "staff_registration_approval": s_all["staff_registration_approval"]},
        "departments": [{"id": d.id, "code": d.code, "name": d.name,
                         "years": int(max_years.get(d.id) or 4)}
                        for d in db.scalars(select(Department).order_by(Department.code))],
        "batches": [{"id": b.id, "label": b.label}
                    for b in db.scalars(select(Batch).order_by(Batch.start_year.desc()))],
        "sections": sections,
    }


__all__ = ["router", "is_holiday", "active_term", "section_label", "section_department_id"]
