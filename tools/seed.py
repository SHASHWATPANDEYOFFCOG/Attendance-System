"""Create the first (super admin) account, and optionally a demo session for a first run.

    python tools/seed.py --admin root --password "choose-something-strong"
    python tools/seed.py --admin root --password "..." --demo

`--demo` adds a faculty member, three students, a camera and a session scheduled around now, so
the dashboard has something to render before any face is enrolled. It creates NO biometric data:
there are no face templates and no consent records, because those must come from real people.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.crypto import hash_password
from app.db import SessionLocal, init_db
from app.models import Camera, ClassSession, Role, RosterEntry, User
from occlubio import load_config


def ensure_user(db, username, display_name, role, password, **kw) -> User:
    existing = db.scalars(select(User).where(User.username == username)).first()
    if existing:
        print(f"  = {username} already exists (id={existing.id})")
        return existing
    u = User(username=username, display_name=display_name, role=role,
             password_hash=hash_password(password), **kw)
    db.add(u)
    db.commit()
    db.refresh(u)
    print(f"  + {role.value:<8} {username} (id={u.id})")
    return u


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", default="root")
    ap.add_argument("--password", required=True)
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    if len(args.password) < 8:
        raise SystemExit("choose a password of at least 8 characters")

    cfg = load_config()
    init_db()
    db = SessionLocal()
    try:
        print("accounts:")
        # The first account must be able to do everything: settings, staff, every department.
        # A plain admin is an HOD scoped to one department, and with no department sees nothing.
        ensure_user(db, args.admin, "Administrator", Role.SUPER_ADMIN, args.password)

        if not args.demo:
            return

        prof = ensure_user(db, "prof.rao", "Dr Rao", Role.FACULTY, args.password)
        students = [
            ensure_user(db, f"s{n}", name, Role.STUDENT, args.password, roll_number=f"2107500{n}")
            for n, name in enumerate(["Aarti Menon", "Devansh Kapoor", "Ishita Rai"], start=1)
        ]

        cam = db.scalars(select(Camera).where(Camera.name == "door-lh4")).first()
        if cam is None:
            cam = Camera(name="door-lh4", room="LH-4", source="0",
                         mode=str(cfg.attendance.default_camera_mode))
            db.add(cam)
            db.commit()
            db.refresh(cam)
            print(f"\ncamera:\n  + {cam.name} room={cam.room} source={cam.source} mode={cam.mode}")

        start = datetime.now(timezone.utc) - timedelta(minutes=5)
        sess = db.scalars(select(ClassSession).where(ClassSession.title == "CS301 Lecture")).first()
        if sess is None:
            sess = ClassSession(
                title="CS301 Lecture", room="LH-4", camera_id=cam.id, owner_id=prof.id,
                scheduled_start=start, scheduled_end=start + timedelta(minutes=50),
                mode=str(cfg.attendance.default_camera_mode),
                grace_minutes=int(cfg.attendance.grace_minutes),
                min_presence_seconds=int(cfg.attendance.min_presence_seconds),
            )
            db.add(sess)
            db.commit()
            db.refresh(sess)
            for s in students:
                db.add(RosterEntry(session_id=sess.id, user_id=s.id))
            db.commit()
            print(f"\nsession:\n  + {sess.title} in {sess.room}, "
                  f"{sess.scheduled_start:%H:%M}-{sess.scheduled_end:%H:%M} UTC, "
                  f"{len(students)} rostered")

        print("\nNOTE: no face templates were created. Every student above will read as "
              "`absent` until they consent and enrol a real face at /static/enroll.html.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
