"""SQLAlchemy models. The database is the source of truth; the FAISS index is derived from it.

Two rules govern this schema:

1. **Sightings are immutable.** The worker appends; nothing edits or deletes them during a
   session. `attendance_records` are *derived* and can be dropped and rebuilt from sightings at
   any time (`POST /api/sessions/{id}/recompute`). A record is never the only copy of a fact.
2. **Every timestamp is stored in UTC.** SQLite has no timezone type, so `UTCDateTime` below
   forces tz-aware UTC on the way in and on the way out. Rendering into
   `cfg.attendance.timezone` happens in the browser, never in the database.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    """Stores tz-aware UTC and returns tz-aware UTC, regardless of backend support.

    Without this, SQLite silently returns naive datetimes and every comparison in rules.py
    raises `TypeError: can't compare offset-naive and offset-aware datetimes` — but only once
    real data exists, which is the worst possible time to find out.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime reached the database; pass UTC-aware values only")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: Optional[datetime], dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------- enums

class Role(str, enum.Enum):
    """Ordered by authority. `rank()` is what permission checks compare, so a new role can be
    slotted in without hunting down every `role ==` test in the codebase."""

    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"              # HOD-equivalent: scoped to their own department
    FACULTY = "faculty"
    STUDENT = "student"
    PARENT = "parent"            # read-only, linked to one student

    def rank(self) -> int:
        return _ROLE_RANK[self]

    def at_least(self, other: "Role") -> bool:
        return self.rank() >= other.rank()


_ROLE_RANK = {
    Role.PARENT: 0,
    Role.STUDENT: 1,
    Role.FACULTY: 2,
    Role.ADMIN: 3,
    Role.SUPER_ADMIN: 4,
}

STAFF_ROLES = (Role.FACULTY, Role.ADMIN, Role.SUPER_ADMIN)
ADMIN_ROLES = (Role.ADMIN, Role.SUPER_ADMIN)


class CameraStatus(str, enum.Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    OFFLINE = "offline"
    ERROR = "error"


class AttendanceStatus(str, enum.Enum):
    """The values `rules.py` produces. Stored as plain strings so the pure rules module never
    has to import this file."""

    PRESENT = "present"
    LATE = "late"
    ABSENT = "absent"
    PARTIAL = "partial"
    LEFT_EARLY = "left_early"
    ON_DUTY = "on_duty"
    EXCUSED = "excused"          # approved leave -- excluded from the percentage denominator
    NEEDS_REVIEW = "needs_review"


#: Statuses that count toward the numerator of an attendance percentage.
COUNTS_PRESENT = {AttendanceStatus.PRESENT.value, AttendanceStatus.LATE.value,
                  AttendanceStatus.ON_DUTY.value}
#: Statuses removed from the denominator entirely -- approved absence is not a miss.
EXCLUDED_FROM_TOTAL = {AttendanceStatus.EXCUSED.value}


class CaptureMethod(str, enum.Enum):
    FACE = "face"                # the occlubio pipeline
    MANUAL = "manual"            # faculty marks a roster
    QR = "qr"
    DEVICE = "device"            # biometric / RFID webhook
    IMPORT = "import"            # CSV backfill


class LeaveType(str, enum.Enum):
    CASUAL = "casual"
    MEDICAL = "medical"
    ON_DUTY = "on_duty"          # representing the org: counts as present
    OTHER = "other"


class LeaveStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


# --------------------------------------------------------------------- people

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    email: Mapped[Optional[str]] = mapped_column(String(200), unique=True, nullable=True)
    roll_number: Mapped[Optional[str]] = mapped_column(String(32), unique=True, nullable=True)
    role: Mapped[Role] = mapped_column(String(16), default=Role.STUDENT)

    password_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)

    # Scoping boundary for ADMIN (HOD): they administer this department only.
    # NULL for SUPER_ADMIN (org-wide) and for students, who are scoped via their section.
    department_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True)

    # Soft delete. Attendance is an academic record: a departed user's history must survive,
    # so a User is never hard-deleted.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, index=True)

    # DPDP Act 2023 — biometric enrollment is refused unless consent is explicitly recorded.
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    consent_text_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="user",
                                                           cascade="all, delete-orphan")

    @property
    def has_biometrics(self) -> bool:
        return any(e.is_active for e in self.enrollments)


class Enrollment(Base):
    """One face template per person. The embedding column is encrypted at rest.

    A leaked face template is a permanent compromise — unlike a password, the subject cannot
    rotate their face. See app/crypto.py.
    """

    __tablename__ = "enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    embedding_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    dim: Mapped[int] = mapped_column(Integer, default=512)
    n_images: Mapped[int] = mapped_column(Integer, default=0)
    mean_quality: Mapped[float] = mapped_column(Float, default=0.0)
    min_quality: Mapped[float] = mapped_column(Float, default=0.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    user: Mapped[User] = relationship(back_populates="enrollments")


# -------------------------------------------------------------------- capture

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    room: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(512))          # "0" | rtsp://... | path.mp4
    mode: Mapped[str] = mapped_column(String(16), default="kiosk")   # kiosk | room

    status: Mapped[CameraStatus] = mapped_column(String(16), default=CameraStatus.STOPPED)
    status_detail: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    measured_fps: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ClassSession(Base):
    """A scheduled session. Named ClassSession to avoid colliding with SQLAlchemy's Session."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    room: Mapped[str] = mapped_column(String(80), index=True)
    camera_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    scheduled_start: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    scheduled_end: Mapped[datetime] = mapped_column(UTCDateTime)

    mode: Mapped[str] = mapped_column(String(16), default="kiosk")
    grace_minutes: Mapped[int] = mapped_column(Integer, default=10)
    min_presence_seconds: Mapped[int] = mapped_column(Integer, default=1500)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # --- timetable linkage (nullable: ad-hoc sessions with no slot remain valid) ----------
    # A session is one dated instance of a recurring TimetableSlot. subject/section/term are
    # denormalised from the slot so a session survives the slot being edited or deleted --
    # attendance must never lose the context it was recorded in.
    timetable_slot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("timetable_slots.id", ondelete="SET NULL"), nullable=True, index=True)
    subject_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True)
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True)
    term_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("academic_terms.id", ondelete="SET NULL"), nullable=True, index=True)

    # --- marking state -------------------------------------------------------------------
    # server_default as well as default: the Python-side default only fires on insert, and
    # ALTER TABLE ADD COLUMN on a populated table needs a DDL-level default. See app/migrate.py.
    capture_method: Mapped[str] = mapped_column(
        String(16), default=CaptureMethod.FACE.value,
        server_default=text(f"'{CaptureMethod.FACE.value}'"))
    marked_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    marked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    # Locked after cfg.attendance.edit_window_hours; a locked record needs a correction request.
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True,
                                            server_default=text("0"))
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, index=True)

    camera: Mapped[Optional[Camera]] = relationship()
    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    subject: Mapped[Optional["Subject"]] = relationship()
    section: Mapped[Optional["Section"]] = relationship()


class RosterEntry(Base):
    __tablename__ = "roster_entries"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_roster_session_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


# ------------------------------------------------------------------- evidence

class Sighting(Base):
    """IMMUTABLE. Appended by the worker, never updated. Attendance is derived from these."""

    __tablename__ = "sightings"
    __table_args__ = (Index("ix_sighting_session_user", "session_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    track_id: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime)

    frames_matched: Mapped[int] = mapped_column(Integer, default=0)
    median_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    max_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    best_quality: Mapped[float] = mapped_column(Float, default=0.0)
    mean_occluded_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    antispoof_result: Mapped[str] = mapped_column(String(24), default="not_evaluated")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class UnknownSighting(Base):
    """A face that never matched anyone. Never auto-assigned — an authority assigns it."""

    __tablename__ = "unknown_sightings"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    camera_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    track_id: Mapped[int] = mapped_column(Integer)

    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime)
    best_score: Mapped[float] = mapped_column(Float, default=0.0)
    frames: Mapped[int] = mapped_column(Integer, default=0)

    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    resolved_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AttendanceRecordRow(Base):
    """DERIVED. Safe to delete and recompute from sightings; overrides are preserved."""

    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "user_id", name="uq_record_session_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    status: Mapped[str] = mapped_column(String(20), index=True)
    first_seen: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    total_visible_s: Mapped[float] = mapped_column(Float, default=0.0)
    avg_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    frames_matched: Mapped[int] = mapped_column(Integer, default=0)

    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # How this row was captured. Face and manual sessions coexist in one table.
    source: Mapped[str] = mapped_column(
        String(16), default=CaptureMethod.FACE.value,
        server_default=text(f"'{CaptureMethod.FACE.value}'"))
    # Set when an approved LeaveRequest covers this date; excludes the row from the denominator.
    leave_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("leave_requests.id", ondelete="SET NULL"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True, index=True)

    # An override survives recompute — a human decision outranks a derived one.
    overridden_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    override_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    overridden_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    overridden_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    @property
    def effective_status(self) -> str:
        return self.overridden_status or self.status


class CorrectionRequest(Base):
    """A student disputing their own record. Never edits attendance directly."""

    __tablename__ = "correction_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")   # open | accepted | rejected
    resolved_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AuditLog(Base):
    """Append-only. Every override, export, assignment and biometric deletion lands here."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


# ==========================================================================================
# ORGANISATION STRUCTURE
#
# Department -> Program -> Section is the containment chain a student sits in. Subject is
# owned by a Department but taught to a Section, so the two meet at FacultyAssignment and
# TimetableSlot rather than being nested.
# ==========================================================================================

class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)   # "CSE"
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    programs: Mapped[list["Program"]] = relationship(back_populates="department")


class Program(Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("department_id", "name", name="uq_program_dept_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))                          # "B.Tech CSE"
    duration_years: Mapped[int] = mapped_column(Integer, default=4)

    department: Mapped[Department] = relationship(back_populates="programs")
    sections: Mapped[list["Section"]] = relationship(back_populates="program")


class Section(Base):
    """A cohort that shares a timetable. The roster unit."""

    __tablename__ = "sections"
    __table_args__ = (
        UniqueConstraint("program_id", "name", "year", "semester", name="uq_section_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"),
                                            index=True)
    name: Mapped[str] = mapped_column(String(32))                           # "A"
    year: Mapped[int] = mapped_column(Integer, default=1)
    semester: Mapped[int] = mapped_column(Integer, default=1)

    program: Mapped[Program] = relationship(back_populates="sections")

    @property
    def label(self) -> str:
        return f"{self.program.name} Y{self.year}S{self.semester}-{self.name}"


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)  # "CS301"
    name: Mapped[str] = mapped_column(String(160))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    credits: Mapped[int] = mapped_column(Integer, default=3)

    department: Mapped[Department] = relationship()


class AcademicTerm(Base):
    __tablename__ = "academic_terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)              # "2026 Odd Semester"
    start_date: Mapped[Date] = mapped_column(Date, index=True)
    end_date: Mapped[Date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class StudentProfile(Base):
    """Everything about a student that is not identity. Split from User so faculty and admin
    rows are not carrying null section columns."""

    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                         unique=True, index=True)
    section_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True)
    admission_year: Mapped[int] = mapped_column(Integer, default=2026)
    # A parent is a User with Role.PARENT; one parent may link to several students.
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    section: Mapped[Optional[Section]] = relationship()


class FacultyAssignment(Base):
    """Who teaches what, to whom, in which term. This is the authorisation boundary: a faculty
    member may only mark sessions for a (subject, section) they are assigned to."""

    __tablename__ = "faculty_assignments"
    __table_args__ = (
        UniqueConstraint("faculty_id", "subject_id", "section_id", "term_id",
                         name="uq_assignment_identity"),
        Index("ix_assignment_lookup", "subject_id", "section_id", "term_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_terms.id", ondelete="CASCADE"))

    faculty: Mapped[User] = relationship()
    subject: Mapped[Subject] = relationship()
    section: Mapped[Section] = relationship()


class TimetableSlot(Base):
    """A recurring weekly period. `ClassSession` is one dated instance of a slot.

    Times are minutes from local midnight in the org timezone, not UTC: a 09:00 lecture stays
    at 09:00 across a DST change, whereas a stored instant would drift by an hour.
    """

    __tablename__ = "timetable_slots"
    __table_args__ = (
        # One section cannot be in two places at once in the same period.
        UniqueConstraint("section_id", "day_of_week", "start_minute", "term_id",
                         name="uq_slot_section_period"),
        Index("ix_slot_faculty_day", "faculty_id", "day_of_week"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"),
                                            index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    faculty_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("academic_terms.id", ondelete="CASCADE"),
                                         index=True)

    day_of_week: Mapped[int] = mapped_column(Integer, index=True)     # 0 = Monday .. 6 = Sunday
    start_minute: Mapped[int] = mapped_column(Integer)                # 540 == 09:00 local
    end_minute: Mapped[int] = mapped_column(Integer)
    room: Mapped[str] = mapped_column(String(80), index=True)

    section: Mapped[Section] = relationship()
    subject: Mapped[Subject] = relationship()
    faculty: Mapped[User] = relationship()

    @staticmethod
    def hhmm(minute: int) -> str:
        return f"{minute // 60:02d}:{minute % 60:02d}"

    @property
    def start_time(self) -> str:
        return self.hhmm(self.start_minute)

    @property
    def end_time(self) -> str:
        return self.hhmm(self.end_minute)


class Holiday(Base):
    """Excluded from percentage denominators. `applies_to` is a department code or NULL for
    the whole organisation."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("date", "applies_to", name="uq_holiday_date_scope"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[Date] = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(160))
    applies_to: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


# ==========================================================================================
# WORKFLOW
# ==========================================================================================

class LeaveRequest(Base):
    """Approved leave rewrites attendance for the covered dates -- see rules.py. It never
    deletes a sighting; the evidence stays and the derived status changes."""

    __tablename__ = "leave_requests"
    __table_args__ = (Index("ix_leave_requester_status", "requester_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"),
                                              index=True)
    type: Mapped[str] = mapped_column(String(16), default=LeaveType.CASUAL.value)
    from_date: Mapped[Date] = mapped_column(Date, index=True)
    to_date: Mapped[Date] = mapped_column(Date, index=True)
    reason: Mapped[str] = mapped_column(Text)
    attachment_url: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default=LeaveStatus.PENDING.value, index=True)
    approver_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])


class Setting(Base):
    """Runtime-editable knobs (threshold %, late window, lock window).

    configs/default.yaml remains the source of truth for the *pipeline*; this table is for
    values an admin changes from the UI without a restart. `get_setting` falls back to the
    YAML value when a key is absent, so there is exactly one default.
    """

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(String(400))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)


class Notification(Base):
    """Queued, not sent inline. `sent_at` NULL means still pending; a worker drains these."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notification_pending", "sent_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(48), index=True)
    payload: Mapped[str] = mapped_column(Text)                    # JSON
    channel: Mapped[str] = mapped_column(String(16), default="email")

    read_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
