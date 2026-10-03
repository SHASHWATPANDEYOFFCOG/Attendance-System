"""Seed a realistic 90-day demo organisation.

    python tools/seed_demo.py --password "demo-password" [--reset] [--days 90]

Creates 3 departments, 6 sections, 12 subjects, ~15 faculty, ~150 students, a full weekly
timetable, a holiday calendar, and back-dated attendance for every scheduled period.

Attendance is not coin-flipped. Each student is given a *target percentage* drawn from a
deliberate mix, and exactly that many absences are then placed across their sessions using
weighted sampling. That guarantees the demo actually contains the cohorts a reviewer looks
for -- in particular the borderline 74-76% band, which a naive Bernoulli draw would only
populate by luck:

    ~55%  regular      88-97%
    ~15%  good         80-88%
    ~10%  borderline   74-76%   <- the band the threshold argument is about
    ~15%  defaulter    52-72%
    ~5%   erratic      60-90%, clustered absences rather than scattered

Absences are weighted toward Mondays, the day after a holiday, and first period, so the
day-of-week heatmap shows a real pattern instead of noise.

Records are written with capture_method=MANUAL: they are the evidence, not derived from
sightings. `recompute_session` leaves them alone (see app/attendance_service.py).
"""
from __future__ import annotations

import argparse
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List

import numpy as np
from sqlalchemy import select, text

from app.crypto import hash_password
from app.db import SessionLocal, engine
from app.migrate import migrate
from app.models import (
    AcademicTerm,
    AttendanceRecordRow,
    AttendanceStatus,
    Camera,
    CaptureMethod,
    ClassSession,
    Department,
    FacultyAssignment,
    Holiday,
    LeaveRequest,
    LeaveStatus,
    LeaveType,
    Program,
    Role,
    RosterEntry,
    Section,
    Setting,
    StudentProfile,
    Subject,
    TimetableSlot,
    User,
    utcnow,
)
from occlubio import load_config
from occlubio.utils import get_logger

log = get_logger("seed")

# --------------------------------------------------------------------------- fixtures

DEPARTMENTS = [
    ("CSE",  "Computer Science & Engineering"),
    ("ECE",  "Electronics & Communication"),
    ("MECH", "Mechanical Engineering"),
]

SUBJECTS = {
    "CSE":  [("CS301", "Operating Systems", 4), ("CS302", "Database Systems", 4),
             ("CS303", "Computer Networks", 3), ("CS304", "Machine Learning", 3)],
    "ECE":  [("EC301", "Digital Signal Processing", 4), ("EC302", "VLSI Design", 4),
             ("EC303", "Embedded Systems", 3), ("EC304", "Control Systems", 3)],
    "MECH": [("ME301", "Thermodynamics", 4), ("ME302", "Fluid Mechanics", 4),
             ("ME303", "Machine Design", 3), ("ME304", "Manufacturing Processes", 3)],
}

FIRST_NAMES = [
    "Aarav", "Aarti", "Aditya", "Ananya", "Arjun", "Bhavna", "Chirag", "Deepa", "Devansh",
    "Divya", "Farhan", "Gaurav", "Harsha", "Ishita", "Jatin", "Kavya", "Kiran", "Lakshmi",
    "Manish", "Meera", "Naveen", "Neha", "Nikhil", "Pooja", "Pranav", "Priya", "Rahul",
    "Rakesh", "Riya", "Rohan", "Sanya", "Shreya", "Siddharth", "Sneha", "Tanvi", "Tarun",
    "Uma", "Varun", "Vikram", "Yash", "Zoya", "Ayesha", "Imran", "Rizwan", "Sana",
]
LAST_NAMES = [
    "Sharma", "Verma", "Iyer", "Nair", "Menon", "Reddy", "Rao", "Kapoor", "Chatterjee",
    "Banerjee", "Gupta", "Joshi", "Desai", "Patel", "Khan", "Mehta", "Singh", "Bose",
    "Pillai", "Kulkarni", "Shetty", "Chauhan", "Mishra", "Trivedi", "Ahuja",
]

# Weekly grid: 6 periods a day, Monday-Friday.
PERIODS = [(9 * 60, 9 * 60 + 50), (10 * 60, 10 * 60 + 50), (11 * 60, 11 * 60 + 50),
           (13 * 60, 13 * 60 + 50), (14 * 60, 14 * 60 + 50), (15 * 60, 15 * 60 + 50)]

PROFILES = [
    ("regular",    0.55, (0.88, 0.97)),
    ("good",       0.15, (0.80, 0.88)),
    ("borderline", 0.10, (0.74, 0.762)),
    ("defaulter",  0.15, (0.52, 0.72)),
    ("erratic",    0.05, (0.60, 0.90)),
]


def local_dt(d: date, minute: int, tz_offset_minutes: int) -> datetime:
    """A local wall-clock time on `d`, converted to UTC for storage."""
    naive = datetime.combine(d, time(minute // 60, minute % 60))
    return (naive - timedelta(minutes=tz_offset_minutes)).replace(tzinfo=timezone.utc)


#: Deleted on --reset, children before parents. The cycle users -> departments -> users
#: (department_id, and StudentProfile.parent_id) cannot be resolved by ordering alone, so FK
#: enforcement is suspended for the duration of the wipe rather than relying on a fragile
#: sequence that breaks the moment a relationship is added.
_WIPE_ORDER = (
    "attendance_records", "sightings", "unknown_sightings", "correction_requests",
    "roster_entries", "notifications", "leave_requests", "sessions", "timetable_slots",
    "faculty_assignments", "student_profiles", "holidays", "sections", "programs",
    "subjects", "departments", "academic_terms", "cameras", "settings", "enrollments",
    "audit_log",
)


def wipe(db) -> None:
    """Remove all demo data. Destructive; only runs behind --reset."""
    db.execute(text("PRAGMA foreign_keys=OFF"))
    for table in _WIPE_ORDER:
        db.execute(text(f'DELETE FROM "{table}"'))
    # `root` is the operator's own account from tools/seed.py -- never destroy their login.
    db.execute(text("DELETE FROM users WHERE username != 'root'"))
    db.execute(text("UPDATE users SET department_id = NULL"))
    db.commit()
    db.execute(text("PRAGMA foreign_keys=ON"))
    log.info("wiped previous demo data")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--password", required=True, help="password for every demo account")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--students", type=int, default=150)
    ap.add_argument("--reset", action="store_true", help="wipe existing demo data first")
    ap.add_argument("--seed", type=int, default=20260801)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    nprng = np.random.default_rng(args.seed)
    cfg = load_config()
    tz_offset = 330                                   # Asia/Kolkata, UTC+05:30

    migrate(engine)
    db = SessionLocal()
    try:
        if args.reset:
            wipe(db)

        today = date.today()
        start = today - timedelta(days=args.days)

        # ------------------------------------------------------------------ term
        term = AcademicTerm(name=f"{today.year} Demo Term",
                            start_date=start, end_date=today + timedelta(days=60),
                            is_active=True)
        db.add(term)
        db.commit()
        db.refresh(term)

        # ------------------------------------------------------------ departments
        depts: Dict[str, Department] = {}
        for code, name in DEPARTMENTS:
            d = Department(code=code, name=name)
            db.add(d)
            depts[code] = d
        db.commit()

        subjects: Dict[str, List[Subject]] = {}
        for code, rows in SUBJECTS.items():
            subjects[code] = []
            for scode, sname, credits in rows:
                s = Subject(code=scode, name=sname, department_id=depts[code].id, credits=credits)
                db.add(s)
                subjects[code].append(s)
        db.commit()

        sections: List[Section] = []
        for code, _ in DEPARTMENTS:
            prog = Program(department_id=depts[code].id, name=f"B.Tech {code}", duration_years=4)
            db.add(prog)
            db.commit()
            db.refresh(prog)
            for letter in ("A", "B"):
                sec = Section(program_id=prog.id, name=letter, year=3, semester=5)
                db.add(sec)
                sections.append(sec)
        db.commit()

        # --------------------------------------------------------------- people
        pw = hash_password(args.password)

        admin = db.scalars(select(User).where(User.username == "principal")).first()
        if admin is None:
            admin = User(username="principal", display_name="Dr Anand Krishnan",
                         role=Role.SUPER_ADMIN, password_hash=pw, email="principal@demo.edu")
            db.add(admin)

        hods: Dict[str, User] = {}
        for code, _ in DEPARTMENTS:
            u = User(username=f"hod.{code.lower()}", display_name=f"HOD {code}",
                     role=Role.ADMIN, password_hash=pw, department_id=depts[code].id,
                     email=f"hod.{code.lower()}@demo.edu")
            db.add(u)
            hods[code] = u
        db.commit()

        faculty: Dict[str, List[User]] = {c: [] for c, _ in DEPARTMENTS}
        fac_n = 0
        for code, _ in DEPARTMENTS:
            for i in range(5):
                fac_n += 1
                name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                u = User(username=f"faculty{fac_n}", display_name=f"Prof {name}",
                         role=Role.FACULTY, password_hash=pw,
                         department_id=depts[code].id, email=f"faculty{fac_n}@demo.edu")
                db.add(u)
                faculty[code].append(u)
        db.commit()

        students: List[User] = []
        profiles: Dict[int, StudentProfile] = {}
        per_section = args.students // len(sections)
        roll = 0
        for sec in sections:
            dept_code = DEPARTMENTS[sections.index(sec) // 2][0]
            for _ in range(per_section):
                roll += 1
                name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                rollno = f"21{dept_code[:2]}{roll:04d}"
                u = User(username=rollno.lower(), display_name=name, role=Role.STUDENT,
                         password_hash=pw, roll_number=rollno,
                         email=f"{rollno.lower()}@demo.edu",
                         consent_given=True, consent_at=utcnow(),
                         consent_text_version="v1")
                db.add(u)
                db.commit()
                db.refresh(u)

                parent = User(username=f"parent.{rollno.lower()}",
                              display_name=f"Guardian of {name}", role=Role.PARENT,
                              password_hash=pw, email=f"parent.{rollno.lower()}@demo.edu")
                db.add(parent)
                db.commit()
                db.refresh(parent)

                sp = StudentProfile(user_id=u.id, section_id=sec.id, admission_year=2021,
                                    parent_id=parent.id)
                db.add(sp)
                students.append(u)
                profiles[u.id] = sp
        db.commit()
        log.info("people: 1 super admin, %d HODs, %d faculty, %d students (+parents)",
                 len(hods), fac_n, len(students))

        # ------------------------------------------------------------ timetable
        slots: List[TimetableSlot] = []
        for idx, sec in enumerate(sections):
            code = DEPARTMENTS[idx // 2][0]
            subs = subjects[code]
            facs = faculty[code]
            # 12 periods a week: each of the 4 subjects taught 3 times.
            plan: List[int] = []
            for si in range(len(subs)):
                plan += [si] * 3
            rng.shuffle(plan)

            cursor = 0
            for day in range(5):                       # Mon-Fri
                for period in range(len(PERIODS)):
                    if cursor >= len(plan):
                        break
                    if rng.random() < 0.45:            # leave gaps: a real grid is not full
                        continue
                    si = plan[cursor]
                    cursor += 1
                    st, en = PERIODS[period]
                    slot = TimetableSlot(
                        section_id=sec.id, subject_id=subs[si].id,
                        faculty_id=facs[si % len(facs)].id, term_id=term.id,
                        day_of_week=day, start_minute=st, end_minute=en,
                        room=f"{code}-{100 + idx * 10 + period}",
                    )
                    db.add(slot)
                    slots.append(slot)
            # Every subject a section studies must have a teacher of record.
            for si, sub in enumerate(subs):
                db.add(FacultyAssignment(faculty_id=facs[si % len(facs)].id,
                                         subject_id=sub.id, section_id=sec.id, term_id=term.id))
        db.commit()
        log.info("timetable: %d weekly slots across %d sections", len(slots), len(sections))

        # -------------------------------------------------------------- holidays
        holiday_dates = set()
        d = start
        while d <= today:
            if d.weekday() < 5 and rng.random() < 0.045:
                holiday_dates.add(d)
            d += timedelta(days=1)
        for hd in sorted(holiday_dates):
            db.add(Holiday(date=hd, name=rng.choice(
                ["Founder's Day", "Regional Festival", "Convocation", "Maintenance Shutdown",
                 "Public Holiday"]), applies_to=None))
        db.commit()
        log.info("holidays: %d working days cancelled", len(holiday_dates))

        # --------------------------------------------------------------- cameras
        for idx, sec in enumerate(sections):
            db.add(Camera(name=f"cam-{sec.id}", room=f"{DEPARTMENTS[idx // 2][0]}-{100 + idx * 10}",
                          source=str(idx), mode="kiosk"))
        db.commit()

        # ---------------------------------------------------------- settings
        for key, value in [
            ("min_attendance_pct", "75"),
            ("late_threshold_minutes", "10"),
            ("edit_window_hours", "24"),
            ("late_counts_as_present", "true"),
            ("at_risk_band_pct", "80"),
        ]:
            db.add(Setting(key=key, value=value))
        db.commit()

        # ------------------------------------------------- sessions + attendance
        section_students: Dict[int, List[User]] = {
            s.id: [u for u in students if profiles[u.id].section_id == s.id] for s in sections
        }

        # Assign each student a target percentage from the deliberate mix.
        names, weights, bands = zip(*PROFILES)
        targets: Dict[int, float] = {}
        cohort: Dict[int, str] = {}
        for u in students:
            pick = rng.choices(range(len(names)), weights=weights)[0]
            lo, hi = bands[pick]
            targets[u.id] = rng.uniform(lo, hi)
            cohort[u.id] = names[pick]

        sessions_created = 0
        student_sessions: Dict[int, List[tuple]] = {u.id: [] for u in students}

        # The latest weekday that is not a holiday: its sessions are left unlocked and
        # unmarked so `/mark` has real work waiting when the demo is opened.
        last_open_day = today
        while last_open_day.weekday() >= 5 or last_open_day in holiday_dates:
            last_open_day -= timedelta(days=1)

        d = start
        while d <= today:
            if d.weekday() < 5 and d not in holiday_dates:
                day_after_holiday = (d - timedelta(days=1)) in holiday_dates
                for slot in slots:
                    if slot.day_of_week != d.weekday():
                        continue
                    starts = local_dt(d, slot.start_minute, tz_offset)
                    ends = local_dt(d, slot.end_minute, tz_offset)
                    sess = ClassSession(
                        title=f"{db.get(Subject, slot.subject_id).code} Period",
                        room=slot.room, owner_id=slot.faculty_id,
                        scheduled_start=starts, scheduled_end=ends,
                        mode="kiosk", grace_minutes=10, min_presence_seconds=1500,
                        timetable_slot_id=slot.id, subject_id=slot.subject_id,
                        section_id=slot.section_id, term_id=term.id,
                        capture_method=CaptureMethod.MANUAL.value,
                        marked_by_id=slot.faculty_id,
                        marked_at=ends + timedelta(minutes=rng.randint(2, 40)),
                        # The most recent working day stays OPEN, so the demo always has a
                        # register waiting to be marked instead of a wall of locked history.
                        is_locked=(d < last_open_day),
                    )
                    db.add(sess)
                    db.flush()
                    sessions_created += 1

                    weight = 1.0
                    if d.weekday() == 0:
                        weight *= 2.2                  # Monday
                    if day_after_holiday:
                        weight *= 1.8
                    if slot.start_minute == PERIODS[0][0]:
                        weight *= 1.4                  # first period
                    if d.weekday() == 4 and slot.start_minute >= PERIODS[4][0]:
                        weight *= 1.5                  # Friday afternoon

                    for u in section_students[slot.section_id]:
                        db.add(RosterEntry(session_id=sess.id, user_id=u.id))
                        student_sessions[u.id].append((sess.id, starts, weight))
            d += timedelta(days=1)
        db.commit()
        log.info("sessions: %d created across %d days", sessions_created, args.days)

        # Place exactly the right number of absences per student.
        total_records = 0
        leave_rows = 0
        for u in students:
            entries = student_sessions[u.id]
            if not entries:
                continue
            n = len(entries)

            # Approved leave leaves the DENOMINATOR, so it must be chosen before the absence
            # count is sized -- otherwise converting absences to excused afterwards silently
            # lifts every student above their target and the borderline band comes out empty.
            n_excused = int(round(n * 0.03))
            counted = max(1, n - n_excused)
            n_absent = max(0, min(counted, int(round(counted * (1.0 - targets[u.id])))))

            w = np.array([e[2] for e in entries], dtype=float)
            if cohort[u.id] == "erratic":
                # Clustered absences: boost a contiguous stretch so the trend line dips.
                lo = int(nprng.integers(0, max(1, n - n // 4)))
                w[lo:lo + n // 4] *= 6.0
            w /= w.sum()

            picked = nprng.choice(n, size=min(n, n_excused + n_absent), replace=False, p=w)
            excused_idx = set(picked[:n_excused].tolist())
            absent_idx = set(picked[n_excused:].tolist())

            for i, (sid, starts, _weight) in enumerate(entries):
                if i in excused_idx or i in absent_idx:
                    status = (AttendanceStatus.EXCUSED.value if i in excused_idx
                              else AttendanceStatus.ABSENT.value)
                    first = last = None
                    visible = 0.0
                    conf = 0.0
                elif rng.random() < 0.07:
                    status = AttendanceStatus.LATE.value
                    first = starts + timedelta(minutes=rng.randint(11, 25))
                    last = starts + timedelta(minutes=48)
                    visible = (last - first).total_seconds()
                    conf = round(rng.uniform(0.52, 0.78), 3)
                else:
                    status = AttendanceStatus.PRESENT.value
                    first = starts + timedelta(seconds=rng.randint(-120, 540))
                    last = starts + timedelta(minutes=48)
                    visible = max(60.0, (last - first).total_seconds())
                    conf = round(rng.uniform(0.55, 0.86), 3)

                db.add(AttendanceRecordRow(
                    session_id=sid, user_id=u.id, status=status,
                    first_seen=first, last_seen=last,
                    total_visible_s=visible, avg_confidence=conf,
                    frames_matched=0 if first is None else rng.randint(6, 40),
                    needs_review=False,
                    source=CaptureMethod.MANUAL.value,
                    computed_at=utcnow(),
                ))
                total_records += 1
            db.commit()

        # A handful of live leave requests so the approvals inbox is not empty.
        approvers = list(hods.values())
        for u in rng.sample(students, 12):
            frm = today - timedelta(days=rng.randint(0, 20))
            lr = LeaveRequest(
                requester_id=u.id,
                type=rng.choice([LeaveType.MEDICAL.value, LeaveType.CASUAL.value,
                                 LeaveType.ON_DUTY.value]),
                from_date=frm, to_date=frm + timedelta(days=rng.randint(0, 3)),
                reason=rng.choice([
                    "Viral fever, advised rest by the campus physician.",
                    "Representing the college at the inter-university tournament.",
                    "Sister's wedding, travelling out of station.",
                    "Hospital follow-up appointment.",
                ]),
                status=rng.choice([LeaveStatus.PENDING.value] * 2 + [LeaveStatus.APPROVED.value,
                                                                     LeaveStatus.REJECTED.value]),
            )
            if lr.status != LeaveStatus.PENDING.value:
                lr.approver_id = rng.choice(approvers).id
                lr.decided_at = utcnow() - timedelta(days=rng.randint(1, 10))
                lr.comment = "Documentation verified." if lr.status == "approved" else \
                             "Insufficient notice given."
            db.add(lr)
            leave_rows += 1
        db.commit()

        # --------------------------------------------------------------- report
        print("\n" + "=" * 74)
        print(f"{'DEMO ORGANISATION SEEDED':^74}")
        print("=" * 74)
        print(f"  departments {len(DEPARTMENTS):>6}   sections {len(sections):>6}"
              f"   subjects {sum(len(v) for v in subjects.values()):>6}")
        print(f"  faculty     {fac_n:>6}   students {len(students):>6}"
              f"   parents  {len(students):>6}")
        print(f"  weekly slots{len(slots):>6}   sessions {sessions_created:>6}"
              f"   records  {total_records:>6}")
        print(f"  holidays    {len(holiday_dates):>6}   leave    {leave_rows:>6}")

        _print_distribution(db, students, cohort)

        print("\n  demo logins (password as supplied)")
        print("  " + "-" * 70)
        print(f"  {'super admin':<14} principal")
        for code, _ in DEPARTMENTS:
            print(f"  {'admin/HOD':<14} hod.{code.lower()}")
        print(f"  {'faculty':<14} faculty1 .. faculty{fac_n}")
        print(f"  {'student':<14} {students[0].username} .. {students[-1].username}")
        print(f"  {'parent':<14} parent.{students[0].username}")
        print("=" * 74)
    finally:
        db.close()


def _print_distribution(db, students, cohort) -> None:
    """Verify the seed actually produced the cohorts it intended."""
    from app.models import AttendanceRecordRow as R

    rows = db.execute(
        select(R.user_id, R.status).where(R.user_id.in_([u.id for u in students]))
    ).all()

    tally: Dict[int, list] = {}
    for uid, status in rows:
        tally.setdefault(uid, []).append(status)

    pcts = {}
    for uid, statuses in tally.items():
        counted = [s for s in statuses if s != AttendanceStatus.EXCUSED.value]
        if not counted:
            continue
        present = sum(1 for s in counted
                      if s in (AttendanceStatus.PRESENT.value, AttendanceStatus.LATE.value))
        pcts[uid] = 100.0 * present / len(counted)

    bands = [("below 60%", 0, 60), ("60-74%", 60, 74), ("74-76% (borderline)", 74, 76.001),
             ("76-85%", 76.001, 85), ("85-95%", 85, 95), ("95%+", 95, 101)]
    print("\n  attendance distribution (approved leave excluded from the denominator)")
    print("  " + "-" * 70)
    for label, lo, hi in bands:
        n = sum(1 for p in pcts.values() if lo <= p < hi)
        bar = "#" * int(n / max(1, len(pcts)) * 46)
        print(f"  {label:<22}{n:>4}  {bar}")

    below = sum(1 for p in pcts.values() if p < 75)
    print(f"\n  defaulters below 75%: {below} of {len(pcts)} "
          f"({100.0 * below / max(1, len(pcts)):.0f}%)")
    if pcts:
        print(f"  mean {np.mean(list(pcts.values())):.1f}%   "
              f"median {np.median(list(pcts.values())):.1f}%   "
              f"min {min(pcts.values()):.1f}%   max {max(pcts.values()):.1f}%")


if __name__ == "__main__":
    main()
