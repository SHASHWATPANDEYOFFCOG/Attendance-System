"""Bridges the database to the pure rules in `app.rules`, and owns retention and export.

`recompute_session` is the proof that attendance records are derived data: it deletes nothing it
cannot rebuild, and running it twice on unchanged sightings produces byte-identical rows. The one
thing it will never overwrite is a **human override** — a faculty decision outranks a derived one,
so overrides survive recompute and are re-applied on top.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    AttendanceRecordRow,
    AuditLog,
    CaptureMethod,
    ClassSession,
    Enrollment,
    RosterEntry,
    Sighting,
    UnknownSighting,
    User,
    utcnow,
)
from app.rules import (
    CameraMode,
    SessionSpec,
    SightingSpec,
    Status,
    attendance_percentage,
    compute_attendance,
)
from occlubio.utils import get_logger

log = get_logger("app.attendance")


def _spec(session: ClassSession) -> SessionSpec:
    return SessionSpec(
        id=session.id,
        scheduled_start=session.scheduled_start,
        scheduled_end=session.scheduled_end,
        mode=CameraMode(session.mode) if session.mode in ("kiosk", "room") else CameraMode.KIOSK,
        grace_minutes=session.grace_minutes,
        min_presence_seconds=session.min_presence_seconds,
    )


def roster_ids(db: Session, session_id: int) -> List[int]:
    return list(db.scalars(select(RosterEntry.user_id).where(RosterEntry.session_id == session_id)))


def session_sightings(db: Session, session_id: int) -> List[Sighting]:
    return list(db.scalars(select(Sighting).where(Sighting.session_id == session_id)))


def recompute_session(db: Session, session: ClassSession, cfg,
                      actor: Optional[User] = None) -> List[AttendanceRecordRow]:
    """Rebuild every attendance record for a session from its immutable sightings.

    Only meaningful for face-captured sessions, where sightings are the primitive evidence and
    records are derived. For a manually-marked session the records ARE the evidence -- there is
    nothing more primitive to rebuild from -- so recomputing would delete every mark and return
    a roster of `absent`. Those sessions are returned untouched.
    """
    if session.capture_method != CaptureMethod.FACE.value:
        log.info("session %s is %s-captured; records are the source of truth, not recomputing",
                 session.id, session.capture_method)
        return list(db.scalars(
            select(AttendanceRecordRow)
            .where(AttendanceRecordRow.session_id == session.id)
            .order_by(AttendanceRecordRow.id)
        ))

    roster = roster_ids(db, session.id)
    rows = session_sightings(db, session.id)

    specs = [
        SightingSpec(
            user_id=s.user_id,
            first_seen=s.first_seen,
            last_seen=s.last_seen,
            frames_matched=s.frames_matched,
            median_confidence=s.median_confidence,
            best_quality=s.best_quality,
            mean_occluded_ratio=s.mean_occluded_ratio,
            confirmed=s.confirmed,
            antispoof_evaluated=(s.antispoof_result == "passed"),
            needs_review=s.needs_review,
            review_reason=s.review_reason,
        )
        for s in rows
    ]

    computed = compute_attendance(_spec(session), roster, specs, cfg)

    # Preserve human decisions across the rebuild.
    existing = {
        r.user_id: r
        for r in db.scalars(select(AttendanceRecordRow)
                            .where(AttendanceRecordRow.session_id == session.id))
    }
    overrides = {
        uid: (r.overridden_status, r.override_reason, r.overridden_by_id, r.overridden_at,
              r.leave_request_id)
        for uid, r in existing.items() if r.overridden_status
    }
    # Records that are not derived from sightings (a CCTV confirmation, a selfie, a QR scan, a
    # teacher's mark, a close-time fill) ARE the evidence. Rebuilding must never erase them.
    kept = {uid: r for uid, r in existing.items() if r.source != CaptureMethod.FACE.value}

    db.execute(delete(AttendanceRecordRow).where(
        AttendanceRecordRow.session_id == session.id,
        AttendanceRecordRow.source == CaptureMethod.FACE.value))

    out: List[AttendanceRecordRow] = list(kept.values())
    for rec in computed:
        if rec.user_id in kept:
            continue
        row = AttendanceRecordRow(
            session_id=session.id,
            user_id=rec.user_id,
            status=rec.status.value,
            first_seen=rec.first_seen,
            last_seen=rec.last_seen,
            total_visible_s=rec.total_visible_s,
            avg_confidence=rec.avg_confidence,
            frames_matched=rec.frames_matched,
            needs_review=rec.needs_review,
            review_reason=rec.review_reason,
            evidence="; ".join(rec.evidence) or None,
            computed_at=utcnow(),
        )
        if rec.user_id in overrides:
            status_, reason, by_id, at, leave_id = overrides[rec.user_id]
            row.overridden_status, row.override_reason = status_, reason
            row.overridden_by_id, row.overridden_at = by_id, at
            row.leave_request_id = leave_id
        db.add(row)
        out.append(row)

    db.add(AuditLog(actor_id=actor.id if actor else None, action="recompute",
                    target_type="session", target_id=str(session.id),
                    detail=f"{len(out)} record(s) rebuilt from {len(rows)} sighting(s)"))
    db.commit()
    log.info("session %d recomputed: %d records from %d sightings", session.id, len(out), len(rows))
    return out


def ensure_records(db: Session, session: ClassSession, cfg) -> List[AttendanceRecordRow]:
    """Return records, computing them on first access."""
    rows = list(db.scalars(select(AttendanceRecordRow)
                           .where(AttendanceRecordRow.session_id == session.id)))
    if rows:
        return rows
    return recompute_session(db, session, cfg)


def session_summary(records: Sequence[AttendanceRecordRow], cfg) -> dict:
    """Counts by effective status, plus the pass/fail against the minimum-attendance rule."""
    counts: dict[str, int] = {}
    for r in records:
        counts[r.effective_status] = counts.get(r.effective_status, 0) + 1
    present_like = counts.get(Status.PRESENT.value, 0) + counts.get(Status.LATE.value, 0)
    total = len(records) or 1
    pct = 100.0 * present_like / total
    return {
        "total": len(records),
        "counts": counts,
        "attendance_pct": round(pct, 1),
        "minimum_pct": float(cfg.attendance.minimum_attendance_pct),
        "meets_minimum": pct >= float(cfg.attendance.minimum_attendance_pct),
        "needs_review": sum(1 for r in records if r.needs_review or
                            r.effective_status == Status.NEEDS_REVIEW.value),
    }


# ---------------------------------------------------------------------- csv

def records_csv(db: Session, session: ClassSession,
                records: Sequence[AttendanceRecordRow]) -> str:
    """CSV export. Field-for-field identical to the JSON the dashboard renders."""
    users = {u.id: u for u in db.scalars(select(User))}
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([
        "session_id", "session_title", "room", "scheduled_start_utc", "scheduled_end_utc",
        "user_id", "roll_number", "display_name", "status", "effective_status",
        "first_seen_utc", "last_seen_utc", "total_visible_s", "avg_confidence",
        "frames_matched", "needs_review", "review_reason",
        "overridden_status", "override_reason", "computed_at_utc",
    ])
    for r in sorted(records, key=lambda x: x.user_id):
        u = users.get(r.user_id)
        w.writerow([
            session.id, session.title, session.room,
            session.scheduled_start.isoformat(), session.scheduled_end.isoformat(),
            r.user_id, u.roll_number if u else "", u.display_name if u else "",
            r.status, r.effective_status,
            r.first_seen.isoformat() if r.first_seen else "",
            r.last_seen.isoformat() if r.last_seen else "",
            round(r.total_visible_s, 1), round(r.avg_confidence, 4), r.frames_matched,
            int(r.needs_review), r.review_reason or "",
            r.overridden_status or "", r.override_reason or "",
            r.computed_at.isoformat(),
        ])
    return buf.getvalue()


# ---------------------------------------------------------------- retention

def run_retention(db: Session, cfg, actor: Optional[User] = None) -> dict:
    """Delete imagery past `cfg.attendance.retention_days`. Attendance survives; biometrics do not.

    Only thumbnails and their DB pointers are removed. The attendance record — the thing a
    student may later need to dispute a grade — is deliberately untouched.
    """
    days = int(cfg.attendance.retention_days)
    cutoff = utcnow() - timedelta(days=days)
    removed_files = 0
    cleared = 0

    for model in (Sighting, UnknownSighting):
        stale = db.scalars(
            select(model).where(model.thumbnail_path.is_not(None), model.created_at < cutoff)
        )
        for row in stale:
            p = Path(row.thumbnail_path)
            try:
                if p.exists():
                    p.unlink()
                    removed_files += 1
            except OSError as exc:
                log.warning("could not delete %s: %s", p, exc)
            row.thumbnail_path = None
            cleared += 1

    db.add(AuditLog(actor_id=actor.id if actor else None, action="retention_sweep",
                    target_type="system", target_id=None,
                    detail=f"cutoff={cutoff.isoformat()} files_deleted={removed_files} "
                           f"rows_cleared={cleared}"))
    db.commit()
    log.info("retention sweep: %d file(s) deleted, %d row(s) cleared (older than %d days)",
             removed_files, cleared, days)
    return {"cutoff_utc": cutoff.isoformat(), "files_deleted": removed_files,
            "rows_cleared": cleared, "retention_days": days}


def erase_biometrics(db: Session, user: User, cfg, actor: Optional[User] = None) -> dict:
    """Right to erasure: drop every face template, keep anonymised attendance history.

    The attendance rows stay because they are an academic/payroll record with its own lawful
    basis and retention duty. What is destroyed is the biometric — the template, and every crop
    of the person's face.
    """
    n_templates = 0
    for e in db.scalars(select(Enrollment).where(Enrollment.user_id == user.id)):
        db.delete(e)
        n_templates += 1

    n_thumbs = 0
    for s in db.scalars(select(Sighting).where(Sighting.user_id == user.id,
                                               Sighting.thumbnail_path.is_not(None))):
        try:
            p = Path(s.thumbnail_path)
            if p.exists():
                p.unlink()
                n_thumbs += 1
        except OSError:
            pass
        s.thumbnail_path = None

    user.consent_given = False
    user.consent_at = None

    db.add(AuditLog(actor_id=actor.id if actor else None, action="erase_biometrics",
                    target_type="user", target_id=str(user.id),
                    reason="subject erasure request",
                    detail=f"templates_deleted={n_templates} thumbnails_deleted={n_thumbs}; "
                           f"attendance history retained"))
    db.commit()

    from app.gallery_service import rebuild_index
    rebuild_index(db, cfg)              # the index must not outlive the templates

    log.info("erased biometrics for user %s: %d template(s), %d thumbnail(s)",
             user.username, n_templates, n_thumbs)
    return {"templates_deleted": n_templates, "thumbnails_deleted": n_thumbs,
            "attendance_history_retained": True}
