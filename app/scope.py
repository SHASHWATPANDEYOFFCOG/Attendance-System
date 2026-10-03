"""Who may see and manage which students, sections and classes.

The single source of truth for the teacher/HOD/admin boundary on *student* data, mirroring what
`app/auth.py` does for sessions:

    super admin   every student
    HOD (admin)   students of their own department (branch)
    teacher       students in sections they teach (a FacultyAssignment or a TimetableSlot)
    student       themselves only
    parent        their linked children, read-only

Every list endpoint applies `student_scope_clause` *in the query*; every detail/write endpoint
calls `assert_can_manage_student`. Hiding a button is never the protection.
"""
from __future__ import annotations

from typing import Optional, Set

from fastapi import HTTPException, status
from sqlalchemy import false, or_, select, true
from sqlalchemy.orm import Session

from app.auth import is_admin, is_faculty, is_parent, is_staff, is_super_admin, role_of
from app.models import (
    FacultyAssignment,
    Program,
    Section,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
)


def taught_section_ids(db: Session, actor: User) -> Set[int]:
    """Sections a teacher is attached to, through an assignment or a timetable slot."""
    a = set(db.scalars(select(FacultyAssignment.section_id)
                       .where(FacultyAssignment.faculty_id == actor.id)))
    t = set(db.scalars(select(TimetableSlot.section_id)
                       .where(TimetableSlot.faculty_id == actor.id)))
    return a | t


def department_section_ids(db: Session, department_id: int) -> Set[int]:
    return set(db.scalars(select(Section.id).join(Program, Program.id == Section.program_id)
                          .where(Program.department_id == department_id)))


def manageable_section_ids(db: Session, actor: User) -> Optional[Set[int]]:
    """Section ids the actor may manage, or None for "all" (super admin)."""
    if is_super_admin(actor):
        return None
    if is_admin(actor):
        return department_section_ids(db, actor.department_id) if actor.department_id else set()
    if is_faculty(actor):
        return taught_section_ids(db, actor)
    return set()


def student_scope_clause(db: Session, actor: User):
    """A WHERE clause on StudentProfile limiting rows to what `actor` may see."""
    if is_super_admin(actor):
        return true()
    if is_admin(actor):
        if not actor.department_id:
            return false()
        secs = department_section_ids(db, actor.department_id)
        # A pending student who chose this branch but whose section was later deleted still
        # belongs to the department.
        return or_(StudentProfile.department_id == actor.department_id,
                   StudentProfile.section_id.in_(secs or {-1}))
    if is_faculty(actor):
        secs = taught_section_ids(db, actor)
        return StudentProfile.section_id.in_(secs or {-1})
    return StudentProfile.user_id == actor.id


def can_manage_student(db: Session, actor: User, student_id: int) -> bool:
    if not is_staff(actor):
        return False
    if is_super_admin(actor):
        return True
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    if prof is None:
        return False
    if is_admin(actor):
        if not actor.department_id:
            return False
        if prof.department_id == actor.department_id:
            return True
        return prof.section_id in department_section_ids(db, actor.department_id)
    return prof.section_id is not None and prof.section_id in taught_section_ids(db, actor)


def assert_can_manage_student(db: Session, actor: User, student_id: int) -> StudentProfile:
    target = db.get(User, student_id)
    prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
    if target is None or prof is None or target.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "student not found")
    if not can_manage_student(db, actor, student_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "this student is not in a class you are responsible for")
    return prof


def can_read_student(db: Session, actor: User, student_id: int) -> bool:
    """Staff in scope, the student themselves, or a linked parent."""
    if actor.id == student_id:
        return True
    if is_parent(actor):
        prof = db.scalars(select(StudentProfile).where(StudentProfile.user_id == student_id)).first()
        return prof is not None and prof.parent_id == actor.id
    return can_manage_student(db, actor, student_id)


def assert_can_manage_section(db: Session, actor: User, section_id: int) -> Section:
    sec = db.get(Section, section_id)
    if sec is None:
        raise HTTPException(404, "section not found")
    allowed = manageable_section_ids(db, actor)
    if allowed is not None and section_id not in allowed:
        raise HTTPException(403, "this class is outside your scope")
    return sec


def section_department_id(db: Session, section_id: Optional[int]) -> Optional[int]:
    if section_id is None:
        return None
    return db.scalar(select(Program.department_id).join(Section, Section.program_id == Program.id)
                     .where(Section.id == section_id))


def subject_in_scope(db: Session, actor: User, subject_id: int) -> Subject:
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(404, "subject not found")
    if is_super_admin(actor):
        return subj
    if is_admin(actor) and subj.department_id == actor.department_id:
        return subj
    raise HTTPException(403, "this subject belongs to another department")


def section_teachers(db: Session, section_id: Optional[int]) -> Set[int]:
    """Teachers responsible for a section — who gets a student's approvals, leaves, issues."""
    if section_id is None:
        return set()
    a = set(db.scalars(select(FacultyAssignment.faculty_id)
                       .where(FacultyAssignment.section_id == section_id)))
    t = set(db.scalars(select(TimetableSlot.faculty_id)
                       .where(TimetableSlot.section_id == section_id)))
    return a | t


def department_heads(db: Session, department_id: Optional[int]) -> Set[int]:
    """HODs of a department, falling back to super admins when the department has none."""
    hods: Set[int] = set()
    if department_id is not None:
        hods = set(db.scalars(select(User.id).where(
            User.role == "admin", User.department_id == department_id,
            User.is_active.is_(True), User.deleted_at.is_(None))))
    if not hods:
        hods = set(db.scalars(select(User.id).where(
            User.role == "super_admin", User.is_active.is_(True), User.deleted_at.is_(None))))
    return hods


def responsible_staff(db: Session, prof: StudentProfile) -> Set[int]:
    """Teachers of the student's section; if none are assigned yet, the branch HOD/admins."""
    staff = section_teachers(db, prof.section_id)
    if not staff:
        dept = prof.department_id or section_department_id(db, prof.section_id)
        staff = department_heads(db, dept)
    return staff


__all__ = [
    "assert_can_manage_section", "assert_can_manage_student", "can_manage_student",
    "can_read_student", "department_heads", "manageable_section_ids", "responsible_staff",
    "role_of", "section_department_id", "section_teachers", "student_scope_clause",
    "subject_in_scope", "taught_section_ids",
]
