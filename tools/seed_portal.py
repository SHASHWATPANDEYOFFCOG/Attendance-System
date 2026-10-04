"""Seed a small, realistic college for trying the portal. DEVELOPMENT ONLY.

    python tools/seed_portal.py                      # random password, printed at the end
    python tools/seed_portal.py --password "S3cret-demo"
    python tools/seed_portal.py --reset              # wipe EVERY table first (dev DB only)

Creates 1 super admin, 1 HOD, 3 teachers, 3 branches, 2 batches, 4 class groups, 9 subjects,
rooms, a weekly timetable, a holiday calendar, 30 approved students (+1 registration waiting
for approval), ~8 weeks of closed sessions with mixed attendance from every capture method,
leave requests in every state, issues, teacher-student conversations and notices.

Attendance is shaped, not coin-flipped: each student gets a target percentage from a mix that
guarantees a few defaulters and a few right at the 75% line, so reports and alerts have
something to show.

Refuses to run when ATTENDANCE_ENV=production, and refuses to add a second copy of the demo
college on top of the first (use --reset).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import secrets
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Same settings as the API server (`uvicorn --env-file .env`); real environment variables win.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ImportError:
    pass

from sqlalchemy import select, text  # noqa: E402

from app import settings_service  # noqa: E402
from app.crypto import hash_password  # noqa: E402
from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.models import (  # noqa: E402
    AcademicTerm,
    Announcement,
    AttendanceRecordRow,
    AttendanceStatus,
    Batch,
    CaptureMethod,
    ClassSession,
    Conversation,
    Department,
    FacultyAssignment,
    Holiday,
    Issue,
    IssueCategory,
    IssueComment,
    IssueStatus,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Message,
    Program,
    Role,
    Room,
    Section,
    SessionState,
    StudentProfile,
    StudentStatus,
    Subject,
    TimetableSlot,
    User,
    utcnow,
)
from app.runtime import cfg  # noqa: E402
from app.session_service import local_dt, sync_roster  # noqa: E402

ORG = "Demo Institute of Technology"
DOMAIN = "demo.edu"

BRANCHES = [("CSE", "Computer Science & Engineering"), ("ECE", "Electronics & Communication"),
            ("ME", "Mechanical Engineering")]
BATCHES = [(2023, 2027), (2024, 2028)]
#: (branch, batch start year, section name, year, semester, students)
SECTIONS = [("CSE", 2023, "A", 3, 5, 8), ("CSE", 2024, "A", 2, 3, 8),
            ("ECE", 2023, "A", 3, 5, 7), ("ME", 2024, "A", 2, 3, 7)]
SUBJECTS = {
    ("CSE", 3): [("CS301", "Operating Systems"), ("CS302", "Database Systems"), ("CS303", "Computer Networks")],
    ("CSE", 2): [("CS201", "Data Structures"), ("CS202", "Digital Logic")],
    ("ECE", 3): [("EC301", "Digital Signal Processing"), ("EC302", "VLSI Design")],
    ("ME", 2): [("ME201", "Thermodynamics"), ("ME202", "Engineering Mechanics")],
}
#: teacher username -> (display name, branch, the (branch, year) groups they teach)
TEACHERS = {
    "teacher.cse": ("Prof. Meera Iyer", "CSE", [("CSE", 3), ("CSE", 2)]),
    "teacher.ece": ("Prof. Arjun Rao", "ECE", [("ECE", 3)]),
    "teacher.me": ("Prof. Kavya Nair", "ME", [("ME", 2)]),
}
ROOMS = [("CSE-101", "Block A", 60), ("CSE-102", "Block A", 60), ("ECE-201", "Block B", 60),
         ("ME-301", "Block C", 60)]
PERIODS = [(9 * 60, 9 * 60 + 50), (10 * 60, 10 * 60 + 50), (11 * 60 + 10, 12 * 60),
           (13 * 60, 13 * 60 + 50), (14 * 60, 14 * 60 + 50)]

FIRST = ["Aarav", "Ananya", "Rohan", "Ishita", "Kabir", "Diya", "Vihaan", "Saanvi", "Arnav", "Myra",
         "Reyansh", "Aadhya", "Sai", "Kiara", "Dhruv", "Anika", "Rudra", "Navya", "Atharv", "Prisha",
         "Kian", "Riya", "Ayaan", "Tara", "Neel", "Meher", "Yash", "Zara", "Om", "Pari", "Ira"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Kapoor", "Gupta", "Joshi", "Desai", "Patel",
        "Khan", "Mehta", "Singh", "Bose", "Pillai", "Kulkarni", "Shetty", "Mishra"]

#: (cohort, share, target attendance band)
COHORTS = [("regular", 0.55, (0.86, 0.97)), ("borderline", 0.15, (0.73, 0.77)),
           ("defaulter", 0.15, (0.55, 0.70)), ("perfect", 0.15, (0.98, 1.0))]


def refuse(msg: str) -> None:
    print(f"seed_portal: {msg}", file=sys.stderr)
    sys.exit(2)


def wipe() -> None:
    """Delete every row in every table. Development databases only."""
    with engine.begin() as conn:
        if engine.dialect.name == "sqlite":
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            for t in reversed(Base.metadata.sorted_tables):
                conn.execute(t.delete())
            conn.execute(text("PRAGMA foreign_keys=ON"))
        else:
            names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--password", help="password for every demo account (default: random, printed)")
    ap.add_argument("--reset", action="store_true", help="wipe ALL data in the database first")
    ap.add_argument("--weeks", type=int, default=8, help="weeks of past attendance (default 8)")
    ap.add_argument("--seed", type=int, default=20261004)
    args = ap.parse_args()

    if os.environ.get("ATTENDANCE_ENV", "").lower() == "production":
        refuse("ATTENDANCE_ENV=production - the demo seed never runs against a live deployment.")
    password = args.password or ("Demo-" + secrets.token_urlsafe(9))
    if len(password) < 8:
        refuse("--password must be at least 8 characters.")

    rng = random.Random(args.seed)
    init_db()
    if args.reset:
        wipe()

    db = SessionLocal()
    try:
        if db.scalars(select(Department).where(Department.code == "CSE")).first() is not None:
            refuse("the demo college is already in this database. Re-run with --reset to start over.")

        pw = hash_password(password)
        now = utcnow()
        today = datetime.now().astimezone().date()
        start = today - timedelta(weeks=args.weeks)

        settings_service.update(db, cfg, {"org_name": ORG}, actor_id=None)

        term = AcademicTerm(name=f"Odd semester {today.year}", start_date=start,
                            end_date=today + timedelta(weeks=10), is_active=True)
        db.add(term)

        # ------------------------------------------------------------ structure
        depts: Dict[str, Department] = {}
        progs: Dict[str, Program] = {}
        for code, name in BRANCHES:
            depts[code] = Department(code=code, name=name)
            db.add(depts[code])
        db.flush()
        for code, _ in BRANCHES:
            progs[code] = Program(department_id=depts[code].id, name=f"B.Tech {code}", duration_years=4)
            db.add(progs[code])
        batches: Dict[int, Batch] = {}
        for s, e in BATCHES:
            batches[s] = Batch(label=f"{s}-{e}", start_year=s, end_year=e)
            db.add(batches[s])
        for name, building, cap in ROOMS:
            db.add(Room(name=name, building=building, capacity=cap))
        db.flush()

        subjects: Dict[tuple, List[Subject]] = {}
        for (branch, year), rows in SUBJECTS.items():
            subjects[(branch, year)] = []
            for code, name in rows:
                s = Subject(code=code, name=name, department_id=depts[branch].id, credits=4,
                            year=year, semester=year * 2 - 1)
                db.add(s)
                subjects[(branch, year)].append(s)

        sections: List[Section] = []
        for branch, bstart, name, year, sem, _n in SECTIONS:
            sec = Section(program_id=progs[branch].id, name=name, year=year, semester=sem,
                          batch_id=batches[bstart].id)
            db.add(sec)
            sections.append(sec)
        db.flush()

        # ---------------------------------------------------------------- staff
        def staff(username: str, display: str, role: Role, dept: str | None) -> User:
            u = User(username=username, display_name=display, role=role, password_hash=pw,
                     email=f"{username}@{DOMAIN}", department_id=depts[dept].id if dept else None,
                     email_verified_at=now, password_changed_at=now)
            db.add(u)
            return u

        admin = staff("admin", "Dr. Anand Krishnan (Principal)", Role.SUPER_ADMIN, None)
        hod = staff("hod.cse", "Dr. Lakshmi Menon (HOD CSE)", Role.ADMIN, "CSE")
        teachers = {u: staff(u, d, Role.FACULTY, b) for u, (d, b, _) in TEACHERS.items()}
        db.flush()
        teacher_for = {grp: teachers[u] for u, (_, _, groups) in TEACHERS.items() for grp in groups}

        # ------------------------------------------------------------- students
        names = [f"{f} {rng.choice(LAST)}" for f in FIRST]
        rng.shuffle(names)
        students: List[User] = []
        section_students: Dict[int, List[User]] = {}
        n = 0
        for (branch, bstart, _name, year, _sem, count), sec in zip(SECTIONS, sections):
            section_students[sec.id] = []
            for _ in range(count):
                n += 1
                roll = f"{str(bstart)[2:]}{branch}{n:03d}"
                u = User(username=roll.lower(), display_name=names[n - 1], role=Role.STUDENT,
                         password_hash=pw, email=f"{roll.lower()}@{DOMAIN}", roll_number=roll,
                         phone=f"98{rng.randint(10_000_000, 99_999_999)}",
                         email_verified_at=now, password_changed_at=now)
                db.add(u)
                db.flush()
                db.add(StudentProfile(
                    user_id=u.id, section_id=sec.id, admission_year=bstart, roll_number=roll,
                    enrollment_no=f"EN{bstart}{n:04d}", department_id=depts[branch].id,
                    batch_id=batches[bstart].id, year=year,
                    dob=date(bstart - 18, rng.randint(1, 12), rng.randint(1, 28)),
                    gender=rng.choice(["female", "male"]),
                    guardian_name=f"Guardian of {names[n - 1].split()[0]}",
                    guardian_phone=f"97{rng.randint(10_000_000, 99_999_999)}",
                    status=StudentStatus.APPROVED.value, decided_by_id=admin.id, decided_at=now))
                students.append(u)
                section_students[sec.id].append(u)

        # One registration waiting in the approvals queue.
        pending_name = names[n]
        pu = User(username=f"pending.{DOMAIN.split('.')[0]}", display_name=pending_name, role=Role.STUDENT,
                  password_hash=pw, email=f"new.student@{DOMAIN}", roll_number="24CSE099",
                  email_verified_at=now, password_changed_at=now)
        db.add(pu)
        db.flush()
        db.add(StudentProfile(user_id=pu.id, section_id=sections[1].id, admission_year=2024,
                              roll_number="24CSE099", enrollment_no="EN20240099",
                              department_id=depts["CSE"].id, batch_id=batches[2024].id, year=2,
                              status=StudentStatus.PENDING.value))

        # ------------------------------------------------------------ timetable
        slots: List[TimetableSlot] = []
        for (branch, _b, _nm, year, _s, _c), sec, room in zip(SECTIONS, sections, ROOMS):
            subs = subjects[(branch, year)]
            teacher = teacher_for[(branch, year)]
            plan = [s for s in subs for _ in range(3)]          # each subject 3x a week
            cells = [(d, p) for d in range(5) for p in range(len(PERIODS))]
            rng.shuffle(cells)
            for sub, (day, period) in zip(plan, sorted(cells[:len(plan)])):
                st, en = PERIODS[period]
                slots.append(TimetableSlot(section_id=sec.id, subject_id=sub.id, faculty_id=teacher.id,
                                           term_id=term.id, day_of_week=day, start_minute=st,
                                           end_minute=en, room=room[0]))
            for sub in subs:
                db.add(FacultyAssignment(faculty_id=teacher.id, subject_id=sub.id,
                                         section_id=sec.id, term_id=term.id))
        db.add_all(slots)

        # -------------------------------------------------------------- holidays
        past_holiday = start + timedelta(days=17)
        while past_holiday.weekday() >= 5:
            past_holiday += timedelta(days=1)
        future_holiday = today + timedelta(days=12)
        db.add_all([Holiday(date=past_holiday, name="Foundation Day"),
                    Holiday(date=future_holiday, name="Regional festival")])
        db.flush()

        # ------------------------------------------------- past sessions + marks
        targets = {}
        for u in students:
            _c, _share, (lo, hi) = rng.choices(COHORTS, weights=[c[1] for c in COHORTS])[0]
            targets[u.id] = rng.uniform(lo, hi)

        # An approved medical leave: its days become "on leave", outside the denominator.
        leave_student = students[3]
        leave_from = start + timedelta(days=24)
        while leave_from.weekday() >= 5:
            leave_from += timedelta(days=1)
        leave_to = leave_from + timedelta(days=1)

        methods = [CaptureMethod.CCTV.value] * 5 + [CaptureMethod.MOBILE.value] * 3 + \
                  [CaptureMethod.QR.value] + [CaptureMethod.MANUAL.value]
        sessions = records = 0
        d = start
        while d < today:
            if d.weekday() < 5 and d != past_holiday:
                for slot in slots:
                    if slot.day_of_week != d.weekday():
                        continue
                    begins = local_dt(d, slot.start_minute, cfg)
                    ends = local_dt(d, slot.end_minute, cfg)
                    sub = db.get(Subject, slot.subject_id)
                    method = rng.choice(methods)
                    sess = ClassSession(
                        title=f"{sub.code} {sub.name}", room=slot.room, owner_id=slot.faculty_id,
                        scheduled_start=begins, scheduled_end=ends, mode="kiosk",
                        timetable_slot_id=slot.id, subject_id=slot.subject_id,
                        section_id=slot.section_id, term_id=term.id, capture_method=method,
                        state=SessionState.CLOSED.value, started_at=begins,
                        started_by_id=slot.faculty_id, closed_at=ends, is_locked=True,
                        marked_by_id=slot.faculty_id if method == CaptureMethod.MANUAL.value else None,
                        marked_at=ends if method == CaptureMethod.MANUAL.value else None)
                    db.add(sess)
                    db.flush()
                    sync_roster(db, sess)
                    sessions += 1
                    for u in section_students[slot.section_id]:
                        on_leave = u.id == leave_student.id and leave_from <= d <= leave_to
                        roll = rng.random()
                        if on_leave:
                            status, src, seen = AttendanceStatus.ON_LEAVE.value, CaptureMethod.SYSTEM.value, None
                        elif roll > targets[u.id]:
                            status, src, seen = AttendanceStatus.ABSENT.value, CaptureMethod.SYSTEM.value, None
                        else:
                            late = rng.random() < 0.08
                            status = AttendanceStatus.LATE.value if late else AttendanceStatus.PRESENT.value
                            src = method
                            seen = begins + timedelta(minutes=rng.randint(11, 19) if late else rng.randint(0, 8))
                        auto = src in (CaptureMethod.CCTV.value, CaptureMethod.MOBILE.value)
                        db.add(AttendanceRecordRow(
                            session_id=sess.id, user_id=u.id, status=status, source=src,
                            first_seen=seen, last_seen=seen, computed_at=ends,
                            marked_at=seen or ends,
                            marked_by_id=slot.faculty_id if src == CaptureMethod.MANUAL.value else None,
                            confidence=round(rng.uniform(0.55, 0.82), 3) if auto and seen else None,
                            avg_confidence=round(rng.uniform(0.55, 0.82), 3) if auto and seen else 0.0,
                            frames_matched=rng.randint(3, 12) if src == CaptureMethod.CCTV.value and seen else 0))
                        records += 1
            d += timedelta(days=1)
        db.flush()

        # ------------------------------------------------------------------ leave
        lr_ok = LeaveRequest(requester_id=leave_student.id, type=LeaveType.MEDICAL.value,
                             from_date=leave_from, to_date=leave_to,
                             reason="Viral fever; doctor advised two days of rest.",
                             status=LeaveStatus.APPROVED.value, approver_id=teacher_for[("CSE", 3)].id,
                             decided_at=now - timedelta(days=20), comment="Get well soon.")
        soon = today + timedelta(days=3)
        while soon.weekday() >= 5:
            soon += timedelta(days=1)
        lr_pending = LeaveRequest(requester_id=students[1].id, type=LeaveType.ON_DUTY.value,
                                  from_date=soon, to_date=soon,
                                  reason="Representing the college at the inter-university coding contest.",
                                  status=LeaveStatus.PENDING.value)
        lr_pending2 = LeaveRequest(requester_id=students[17].id, type=LeaveType.FAMILY_EMERGENCY.value,
                                   from_date=soon, to_date=soon + timedelta(days=1),
                                   reason="Travelling home for a family emergency.",
                                   status=LeaveStatus.PENDING.value)
        lr_rejected = LeaveRequest(requester_id=students[9].id, type=LeaveType.PERSONAL.value,
                                   from_date=start + timedelta(days=10), to_date=start + timedelta(days=10),
                                   reason="Personal work.", status=LeaveStatus.REJECTED.value,
                                   approver_id=teacher_for[("CSE", 2)].id, decided_at=now - timedelta(days=30),
                                   comment="Please give more detail and apply in advance.")
        db.add_all([lr_ok, lr_pending, lr_pending2, lr_rejected])

        # ----------------------------------------------------------------- issues
        def issue(student: User, cat: IssueCategory, title: str, body: str, status: IssueStatus,
                  assignee: User, replies: List[tuple]) -> None:
            created = now - timedelta(days=rng.randint(2, 12))
            i = Issue(student_id=student.id, category=cat.value, title=title, description=body,
                      status=status.value, assigned_to_id=assignee.id, created_at=created,
                      updated_at=created,
                      resolved_at=created + timedelta(days=1) if status == IssueStatus.RESOLVED else None)
            db.add(i)
            db.flush()
            for k, (author, text_) in enumerate(replies):
                db.add(IssueComment(issue_id=i.id, author_id=author.id, body=text_,
                                    created_at=created + timedelta(hours=3 * (k + 1))))

        t_cse = teacher_for[("CSE", 3)]
        issue(students[0], IssueCategory.ATTENDANCE_CORRECTION, "Marked absent in CS302 though I was present",
              "The camera did not pick me up in Tuesday's Database Systems lecture; I sat in the last row.",
              IssueStatus.OPEN, t_cse, [])
        issue(students[2], IssueCategory.TECHNICAL, "Selfie check keeps saying 'move closer'",
              "On my phone the face check fails even in good light.", IssueStatus.IN_PROGRESS, t_cse,
              [(t_cse, "Please try with the phone held at eye level and the screen brightness up. "
                       "If it still fails, bring the phone to the department office."),
               (students[2], "Will do, thanks.")])
        issue(students[20], IssueCategory.ACADEMIC, "Lab record submission date",
              "Is the DSP lab record due this Friday or next?", IssueStatus.RESOLVED,
              teacher_for[("ECE", 3)], [(teacher_for[("ECE", 3)], "Next Friday. It is on the notice board too.")])

        # --------------------------------------------------------------- messages
        def conversation(t: User, s: User, lines: List[tuple]) -> None:
            first = now - timedelta(days=rng.randint(1, 6))
            c = Conversation(staff_id=t.id, student_id=s.id, created_at=first, last_message_at=first)
            db.add(c)
            db.flush()
            for k, (sender, body) in enumerate(lines):
                at = first + timedelta(minutes=30 * k)
                db.add(Message(conversation_id=c.id, sender_id=sender.id, body=body, created_at=at,
                               read_at=at + timedelta(minutes=5) if k < len(lines) - 1 else None))
                c.last_message_at = at

        defaulters = sorted(students, key=lambda u: targets[u.id])[:2]
        for s in defaulters:
            t = next(t for (b, y), t in teacher_for.items() if s in section_students[
                next(sec.id for (bb, _b, _n, yy, _s, _c), sec in zip(SECTIONS, sections) if bb == b and yy == y)])
            conversation(t, s, [(t, f"Hi {s.display_name.split()[0]}, your attendance has dropped below 75%. "
                                    "Please meet me after class this week."),
                                (s, "Sorry ma'am/sir, I was unwell. I will come by on Thursday.")])
        conversation(t_cse, students[5], [(t_cse, "Good work on the OS assignment. Could you help set up the lab demo?")])

        # ----------------------------------------------------------- notices
        db.add_all([
            Announcement(author_id=admin.id, title="Welcome to the attendance portal",
                         body="Mark attendance from your phone during a live lecture, check your percentage "
                              "any time, and apply for leave online. Enrol your face once from 'Face check'.",
                         audience_type="all", pinned=True, created_at=now - timedelta(days=7)),
            Announcement(author_id=t_cse.id, title="CS301 extra class on Saturday",
                         body="An extra Operating Systems lecture will be held on Saturday at 10:00 in CSE-101.",
                         audience_type="section", audience_ids=json.dumps([sections[0].id]),
                         created_at=now - timedelta(days=2)),
        ])
        db.commit()

        # ------------------------------------------------------------------ report
        print("\n" + "=" * 72)
        print(f"{'DEMO COLLEGE SEEDED - ' + ORG:^72}")
        print("=" * 72)
        print(f"  branches {len(BRANCHES)}  batches {len(BATCHES)}  class groups {len(sections)}  "
              f"subjects {sum(len(v) for v in SUBJECTS.values())}  weekly slots {len(slots)}")
        print(f"  students {len(students)} (+1 waiting for approval)  sessions {sessions}  records {records}")
        print("\n  Logins - every account uses the same password:")
        print(f"    password      {password}")
        print("    super admin   admin")
        print("    HOD (CSE)     hod.cse")
        print("    teachers      " + ", ".join(TEACHERS))
        print(f"    students      {students[0].username} .. {students[-1].username}   "
              f"(or their email, e.g. {students[0].email})")
        print("\n  Students have not enrolled a face yet - sign in as one and open 'Face check'.")
        print("  This data is for development. Never run this against a real college's database.")
        print("=" * 72)
    finally:
        db.close()


if __name__ == "__main__":
    main()
