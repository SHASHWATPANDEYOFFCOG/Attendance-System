"""Starts and stops camera workers with the lectures in their room, and watches their health.

Only cameras that are enabled and set to auto-start are managed; a camera an operator started by
hand is left alone. A worker that has stopped sending heartbeats during a lecture is reported as
offline (the teacher and HOD are alerted once per outage) and restarted.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Camera, CameraStatus, ClassSession, SessionState, utcnow
from occlubio.utils import get_logger

log = get_logger("app.cameras")

_auto_started: Set[int] = set()


def _lecture_now(db: Session, room: str):
    now = utcnow()
    return db.scalars(select(ClassSession).where(
        ClassSession.room == room, ClassSession.state == SessionState.ACTIVE.value,
        ClassSession.deleted_at.is_(None), ClassSession.scheduled_end >= now)).first()


def lecture_for(db: Session, cam: Camera):
    """The live lecture this camera serves: one it was connected to by hand, else its room's."""
    linked = db.scalars(select(ClassSession).where(
        ClassSession.camera_id == cam.id, ClassSession.state == SessionState.ACTIVE.value,
        ClassSession.deleted_at.is_(None))).first()
    return linked if linked is not None else _lecture_now(db, cam.room)


def mark_managed(camera_id: int) -> None:
    """A camera connected to a lecture by hand: stop it when that lecture ends, as if auto-started."""
    _auto_started.add(camera_id)


def forget(camera_id: int) -> None:
    _auto_started.discard(camera_id)


def tick(db: Session, cfg) -> dict:
    from app.worker import alert_camera_offline, registry

    started = stopped = alerted = 0
    stale_after = timedelta(seconds=float(cfg.attendance.camera_offline_after_s))
    for cam in db.scalars(select(Camera)):
        lecture = lecture_for(db, cam) if cam.enabled else None
        running = registry.is_running(cam.id)

        if cam.enabled and cam.auto_start and lecture is not None and not running:
            registry.start(cam.id, cfg)
            _auto_started.add(cam.id)
            started += 1
            continue
        if running and cam.id in _auto_started and (lecture is None or not cam.enabled):
            registry.stop(cam.id)
            _auto_started.discard(cam.id)
            cam.status, cam.status_detail = CameraStatus.STOPPED, "stopped: no lecture in the room"
            stopped += 1
            continue
        # A worker that died silently: no heartbeat for a while during a lecture.
        if lecture is not None and cam.last_heartbeat is not None and \
                utcnow() - cam.last_heartbeat > stale_after and cam.status != CameraStatus.STOPPED:
            if alert_camera_offline(db, cam, "no heartbeat from the camera worker"):
                alerted += 1
            cam.status = CameraStatus.OFFLINE
            cam.status_detail = "no heartbeat"
            if cam.auto_start and not running:
                registry.start(cam.id, cfg)
    db.commit()
    return {"started": started, "stopped": stopped, "alerted": alerted}
