"""Write a confirmed sighting directly, as the camera worker would, then recompute.

This exists to exercise the dashboard's present/late rendering and the recompute path without a
camera or a real face. It writes exactly the row `CameraWorker._write_sighting` writes on a
CHECKIN decision.

It does NOT perform face recognition, and a row it creates is NOT evidence that anyone attended.
It is a rendering fixture. Do not run it against a real deployment.
"""
from __future__ import annotations

import argparse
from datetime import timedelta

from sqlalchemy import select

from app.attendance_service import recompute_session
from app.db import SessionLocal
from app.models import Camera, ClassSession, Sighting, User, utcnow
from occlubio import load_config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", required=True, help="who to mark seen")
    ap.add_argument("--session-id", type=int, default=None)
    ap.add_argument("--minutes-ago", type=float, default=2.0)
    ap.add_argument("--confidence", type=float, default=0.71)
    ap.add_argument("--visible-seconds", type=float, default=90.0)
    args = ap.parse_args()

    cfg = load_config()
    db = SessionLocal()
    try:
        user = db.scalars(select(User).where(User.username == args.username)).first()
        if user is None:
            raise SystemExit(f"no such user: {args.username}")

        sess = (db.get(ClassSession, args.session_id) if args.session_id
                else db.scalars(select(ClassSession)
                                .order_by(ClassSession.scheduled_start.desc())).first())
        if sess is None:
            raise SystemExit("no session exists - run tools/seed.py --demo first")

        cam = db.scalars(select(Camera).where(Camera.room == sess.room)).first()
        seen_at = utcnow() - timedelta(minutes=args.minutes_ago)

        db.add(Sighting(
            session_id=sess.id,
            camera_id=cam.id if cam else None,
            user_id=user.id,
            track_id=901,
            first_seen=seen_at,
            last_seen=seen_at + timedelta(seconds=args.visible_seconds),
            frames_matched=int(cfg.attendance.confirm_frames) + 3,
            median_confidence=args.confidence,
            max_confidence=args.confidence + 0.05,
            best_quality=0.82,
            mean_occluded_ratio=0.12,
            confirmed=True,
            antispoof_result="not_evaluated",
            needs_review=False,
            review_reason="SIMULATED by tools/simulate_checkin.py - not a real recognition",
        ))
        db.commit()

        rows = recompute_session(db, sess, cfg)
        status = {r.user_id: r.effective_status for r in rows}
        print(f"simulated check-in: {user.display_name} in '{sess.title}' "
              f"at {seen_at.isoformat()}")
        print(f"recomputed {len(rows)} record(s): {status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
