"""Check the seeded data actually contains the patterns the demo claims.

    python tools/verify_seed.py

A seed that looks plausible in aggregate but has a flat day-of-week profile makes the analytics
screens meaningless, so the patterns are asserted rather than assumed.
"""
from __future__ import annotations

import sys
from collections import defaultdict

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    AttendanceRecordRow,
    AttendanceStatus,
    ClassSession,
    Department,
    Section,
    Subject,
    TimetableSlot,
    User,
)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TZ_OFFSET_MIN = 330                                    # Asia/Kolkata
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'' if ok else '  -> ' + detail}")
    if not ok:
        failures.append(label)


def main() -> int:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(AttendanceRecordRow.status, ClassSession.scheduled_start,
                   ClassSession.section_id, ClassSession.subject_id)
            .join(ClassSession, ClassSession.id == AttendanceRecordRow.session_id)
        ).all()
        if not rows:
            print("no seeded attendance found - run tools/seed_demo.py first")
            return 1

        print(f"\n{len(rows):,} attendance records\n")

        # ------------------------------------------------------ day of week
        by_day = defaultdict(lambda: [0, 0])           # weekday -> [absent, total]
        for status, start, _sec, _sub in rows:
            local = start.timestamp() + TZ_OFFSET_MIN * 60
            import datetime as _dt
            wd = _dt.datetime.fromtimestamp(local, _dt.timezone.utc).weekday()
            if status == AttendanceStatus.EXCUSED.value:
                continue
            by_day[wd][1] += 1
            if status == AttendanceStatus.ABSENT.value:
                by_day[wd][0] += 1

        print("  absence rate by weekday")
        print("  " + "-" * 56)
        rates = {}
        for wd in sorted(by_day):
            absent, total = by_day[wd]
            rate = 100.0 * absent / max(1, total)
            rates[wd] = rate
            print(f"  {DAYS[wd]:<5}{rate:>6.1f}%   {'#' * int(rate * 1.6)}")

        monday = rates.get(0, 0)
        others = [r for wd, r in rates.items() if wd != 0]
        print()
        check("Monday absence exceeds the weekly average",
              monday > sum(others) / max(1, len(others)),
              f"Mon {monday:.1f}% vs avg {sum(others)/max(1,len(others)):.1f}%")
        check("no weekend sessions were scheduled",
              5 not in rates and 6 not in rates, str(sorted(rates)))

        # ------------------------------------------------------ percentages
        per_student = defaultdict(lambda: [0, 0])      # uid -> [present, counted]
        srows = db.execute(
            select(AttendanceRecordRow.user_id, AttendanceRecordRow.status)
        ).all()
        for uid, status in srows:
            if status == AttendanceStatus.EXCUSED.value:
                continue
            per_student[uid][1] += 1
            if status in (AttendanceStatus.PRESENT.value, AttendanceStatus.LATE.value):
                per_student[uid][0] += 1

        pct = {uid: 100.0 * p / t for uid, (p, t) in per_student.items() if t}
        borderline = [u for u, p in pct.items() if 74 <= p <= 76]
        defaulters = [u for u, p in pct.items() if p < 75]

        check("borderline 74-76% cohort exists", len(borderline) >= 5, str(len(borderline)))
        check("defaulters are a meaningful minority",
              0.10 <= len(defaulters) / len(pct) <= 0.40,
              f"{len(defaulters)}/{len(pct)}")
        check("nobody is at exactly 0% or 100%",
              all(0 < p < 100 for p in pct.values()),
              f"min {min(pct.values()):.1f} max {max(pct.values()):.1f}")

        # ------------------------------------------------------- structure
        n_dept = db.scalar(select(Department).with_only_columns(
            Department.id).order_by(Department.id.desc()).limit(1))
        depts = len(db.scalars(select(Department)).all())
        secs = len(db.scalars(select(Section)).all())
        subs = len(db.scalars(select(Subject)).all())
        slots = len(db.scalars(select(TimetableSlot)).all())
        students = len(db.scalars(select(User).where(User.role == "student")).all())

        print()
        check("3 departments", depts == 3, str(depts))
        check("6 sections", secs == 6, str(secs))
        check("12 subjects", subs == 12, str(subs))
        check("timetable populated", slots >= 40, str(slots))
        check("~150 students", 140 <= students <= 160, str(students))

        # every session carries its academic context
        orphan = db.scalars(
            select(ClassSession).where(ClassSession.subject_id.is_(None))
        ).all()
        check("every session is linked to a subject", not orphan, f"{len(orphan)} orphans")

        print("\n" + ("ALL PATTERNS PRESENT" if not failures
                      else f"{len(failures)} FAILED: " + ", ".join(failures)))
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
