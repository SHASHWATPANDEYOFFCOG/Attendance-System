"""One long-lived supervised worker per camera.

A worker never runs inside a request handler — a single camera would block the whole service.
The API starts and stops these; each owns its own DB session, its own tracker and its own
confirmation state machine.

Design notes that matter operationally:

* **Always process the newest frame.** `_LatestFrame` drains the capture on its own thread and
  keeps only the most recent image. A backlog would mean stamping people present for frames
  from thirty seconds ago, which is worse than dropping them.
* **Confirmed tracks stop being embedded.** Detection and IoU association continue (so presence
  time keeps accumulating), but align -> embed -> search is skipped entirely. On this hardware
  that is the single largest CPU saving available: 66 ms per face per processed frame.
* **A sighting row is finalized when its track closes**, then never edited. While a track is
  still open its `last_seen`/`frames_matched` are still being written — that is construction,
  not mutation of a settled fact.
* **A camera that quietly died looks exactly like a room full of absent students.** Hence
  heartbeats, an explicit `offline` status, backoff reconnection and a disk spool.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from sqlalchemy import select

from app.bus import emit
from app.confirm import ConfirmationManager, Decision, EventKind, Observation
from app.db import SessionLocal
from app.gallery_service import get_gallery, search_top1
from app.models import (
    Camera,
    CameraStatus,
    ClassSession,
    Sighting,
    UnknownSighting,
    User,
    utcnow,
)
from app.pipeline_service import PipelineService, get_pipeline
from occlubio.tracking import IoUTracker
from occlubio.utils import get_logger

log = get_logger("app.worker")


# --------------------------------------------------------------------- clock

def clock_warning() -> Optional[str]:
    """Best-effort check that the host clock is synchronised.

    Every late/absent verdict depends on the clock. A drifted host silently marks on-time
    arrivals late, and nothing else in the system can detect it — so this is surfaced in
    `/api/system/status` and banners on the dashboard rather than only logged.
    """
    try:
        out = subprocess.run(
            ["w32tm", "/query", "/status"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return "Windows Time service did not report a status; clock sync is unverified."
        text = out.stdout.lower()
        if "last successful sync time" in text and "unspecified" in text:
            return "The host clock has never successfully synchronised with a time source."
        return None
    except FileNotFoundError:
        return None                      # not Windows; assume the platform handles NTP
    except (subprocess.SubprocessError, OSError) as exc:
        return f"Could not verify host clock synchronisation: {exc}"


# ------------------------------------------------------------- frame capture

class _LatestFrame:
    """Reads a capture continuously, keeping only the newest frame."""

    def __init__(self, cap: cv2.VideoCapture) -> None:
        self._cap = cap
        self._frame: Optional[np.ndarray] = None
        self._ts: float = 0.0
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._failed = threading.Event()
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        misses = 0
        while not self._stopping.is_set():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                misses += 1
                if misses > 30:
                    self._failed.set()
                    return
                time.sleep(0.05)
                continue
            misses = 0
            with self._lock:
                self._frame = frame
                self._ts = time.monotonic()

    def get(self) -> Tuple[Optional[np.ndarray], float]:
        with self._lock:
            return (None, 0.0) if self._frame is None else (self._frame.copy(), self._ts)

    @property
    def failed(self) -> bool:
        return self._failed.is_set()

    def close(self) -> None:
        self._stopping.set()
        self._thread.join(timeout=2.0)
        self._cap.release()


# ---------------------------------------------------------------- the worker

class CameraWorker(threading.Thread):
    """Supervised capture + recognition loop for one camera."""

    def __init__(self, camera_id: int, cfg, pipeline: Optional[PipelineService] = None) -> None:
        super().__init__(name=f"camera-{camera_id}", daemon=True)
        self.camera_id = camera_id
        self.cfg = cfg
        self._pipeline = pipeline
        # NOT `self._stop`: threading.Thread uses a private `_stop()` method during join(), and
        # shadowing it with an Event makes join() raise "'Event' object is not callable".
        self._stopping = threading.Event()
        self.last_error: Optional[str] = None
        self.measured_fps: float = 0.0

        a = cfg.attendance
        self.stride = max(1, int(a.detect_every_n_frames))
        self.max_faces = int(a.max_faces_per_frame)
        self.backoff: List[int] = [int(x) for x in a.reconnect_backoff_s]
        self.heartbeat_interval_s = float(a.heartbeat_interval_s)
        self.store_thumbnails = bool(a.store_thumbnails)
        self.spool = Path(str(a.event_buffer_path))
        self.thumb_dir = Path("var") / "thumbs"

    # ------------------------------------------------------------ lifecycle

    def stop(self) -> None:
        self._stopping.set()

    def run(self) -> None:
        db = SessionLocal()
        try:
            cam = db.get(Camera, self.camera_id)
            if cam is None:
                log.error("camera %d vanished before the worker started", self.camera_id)
                return

            if not self._antispoof_ok(db, cam):
                return

            attempt = 0
            while not self._stopping.is_set():
                delay = self.backoff[min(attempt, len(self.backoff) - 1)] if attempt else 0
                if delay:
                    log.warning("camera %s: reconnecting in %ds", cam.name, delay)
                    self._set_status(db, cam, CameraStatus.OFFLINE,
                                     f"reconnecting in {delay}s: {self.last_error or 'stream lost'}")
                    if self._stopping.wait(delay):
                        break

                cap = self._open(cam.source)
                if cap is None or not cap.isOpened():
                    self.last_error = f"cannot open source: {cam.source}"
                    attempt += 1
                    continue

                self._set_status(db, cam, CameraStatus.RUNNING, "streaming")
                try:
                    self._session_loop(db, cam, cap)
                    attempt = 0
                except Exception as exc:                      # keep the supervisor alive
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    log.exception("camera %s: loop crashed", cam.name)
                    attempt += 1

            self._set_status(db, cam, CameraStatus.STOPPED, "stopped")
        finally:
            db.close()

    def _antispoof_ok(self, db, cam: Camera) -> bool:
        """B9: in `strict` mode a live camera refuses to run without PAD weights."""
        pipeline = self._pipeline or get_pipeline(self.cfg)
        self._pipeline = pipeline
        if pipeline.antispoof_available:
            return True
        mode = str(self.cfg.attendance.antispoof_mode).lower()
        msg = ("No anti-spoof weights are loaded. Anyone can hold up a phone showing an enrolled "
               "person's face and be stamped present — exactly the proxy attendance this system "
               "exists to stop. Set antispoof.onnx_path (MiniFASNet ONNX) in configs/default.yaml.")
        if mode == "strict":
            self.last_error = msg
            log.error("camera %s REFUSED TO START (antispoof_mode=strict). %s", cam.name, msg)
            self._set_status(db, cam, CameraStatus.ERROR, msg)
            emit("camera_status", {"camera_id": cam.id, "status": "error", "detail": msg},
                 camera_id=cam.id)
            return False
        log.warning("=" * 100)
        log.warning("ANTI-SPOOFING IS DISABLED (antispoof_mode=permissive). %s", msg)
        log.warning("=" * 100)
        return True

    @staticmethod
    def _open(source: str) -> Optional[cv2.VideoCapture]:
        try:
            cap = cv2.VideoCapture(int(source)) if str(source).isdigit() \
                else cv2.VideoCapture(str(source))
            # Keep the driver-side buffer minimal; staleness is handled by _LatestFrame too.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        except (cv2.error, ValueError) as exc:
            log.error("cannot open %s: %s", source, exc)
            return None

    # ----------------------------------------------------------- main loop

    def _session_loop(self, db, cam: Camera, cap: cv2.VideoCapture) -> None:
        pipeline = self._pipeline or get_pipeline(self.cfg)
        reader = _LatestFrame(cap)
        tracker = IoUTracker(
            iou_thresh=self.cfg.tracking.iou_thresh,
            max_age=self.cfg.tracking.max_age,
            min_hits=self.cfg.tracking.min_hits,
        )
        manager = ConfirmationManager(self.cfg)
        open_sightings: Dict[int, int] = {}       # track_id -> sightings.id
        track_users: Dict[int, int] = {}          # track_id -> user_id
        unknown_emitted: set[int] = set()

        frame_no = 0
        last_beat = 0.0
        last_ts = 0.0
        fps_ema: Optional[float] = None
        timeout = float(self.cfg.attendance.frame_grab_timeout_s)

        try:
            while not self._stopping.is_set():
                if reader.failed:
                    self.last_error = "stream ended or stopped delivering frames"
                    raise RuntimeError(self.last_error)

                frame, ts = reader.get()
                now_mono = time.monotonic()

                if frame is None or ts == last_ts:
                    if frame is None and now_mono - (last_beat or now_mono) > timeout:
                        self.last_error = "no frames within frame_grab_timeout_s"
                        raise RuntimeError(self.last_error)
                    time.sleep(0.01)
                    self._maybe_beat(db, cam, now_mono, last_beat)
                    last_beat = now_mono if now_mono - last_beat > self.heartbeat_interval_s else last_beat
                    continue

                last_ts = ts
                frame_no += 1
                if frame_no % self.stride:
                    continue

                t_start = time.perf_counter()
                session = self._resolve_session(db, cam)
                faces = pipeline.detect(frame)[: self.max_faces]
                faces = tracker.update(faces)

                for face in faces:
                    tid = face.track_id
                    if tid is None:
                        continue

                    if manager.is_confirmed(tid):
                        # Keep the presence window growing, but skip align/embed/search.
                        self._extend_sighting(db, open_sightings.get(tid))
                        continue

                    chip = pipeline.align(frame, face)
                    passed, quality, occ, spoof = pipeline.assess(chip, face.det_score)
                    gallery = get_gallery(db, self.cfg)
                    user_id, score = (None, 0.0)
                    if passed:
                        emb = pipeline.embed(frame, face, chip)
                        user_id, score = search_top1(gallery, emb)

                    obs = Observation(
                        ts=ts,
                        identity=str(user_id) if user_id is not None else None,
                        score=score,
                        quality=quality,
                        quality_passed=passed,
                        live=bool(spoof.get("live", True)),
                        antispoof_evaluated=pipeline.antispoof_available,
                        occluded_ratio=float(occ.get("occluded_ratio", 0.0)),
                    )
                    decision = manager.observe(tid, obs)
                    if decision is not None:
                        self._handle(db, cam, session, decision, chip, track_users,
                                     open_sightings, unknown_emitted)

                for decision in manager.tick(ts):
                    self._handle(db, cam, session, decision, None, track_users,
                                 open_sightings, unknown_emitted)

                dt = time.perf_counter() - t_start
                fps_ema = (1.0 / dt) if fps_ema is None else 0.9 * fps_ema + 0.1 * (1.0 / max(dt, 1e-6))
                self.measured_fps = float(fps_ema)

                if now_mono - last_beat > self.heartbeat_interval_s:
                    last_beat = now_mono
                    self._beat(db, cam)
                    self._flush_spool(db)
        finally:
            reader.close()

    # ------------------------------------------------------------- handling

    def _handle(self, db, cam: Camera, session: Optional[ClassSession], d: Decision,
                chip: Optional[np.ndarray], track_users: Dict[int, int],
                open_sightings: Dict[int, int], unknown_emitted: set) -> None:
        ev = d.evidence
        sid = session.id if session else None

        if d.kind is EventKind.CANDIDATE and ev is not None:
            emit("candidate", {
                "track_id": d.track_id,
                "user_id": int(ev.identity) if ev.identity and ev.identity.isdigit() else None,
                "frames": ev.frames_matched,
                "needed": int(self.cfg.attendance.confirm_frames),
                "confidence": round(ev.median_confidence, 4),
                "detail": d.detail,
            }, session_id=sid, camera_id=cam.id)
            return

        if d.kind is EventKind.CHECKIN and ev is not None and ev.identity:
            user_id = int(ev.identity)
            track_users[d.track_id] = user_id
            row = self._write_sighting(db, cam, session, d, ev, user_id, chip, confirmed=True)
            if row is not None:
                open_sightings[d.track_id] = row.id
            user = db.get(User, user_id)
            emit("checkin", {
                "track_id": d.track_id,
                "user_id": user_id,
                "display_name": user.display_name if user else f"user {user_id}",
                "roll_number": user.roll_number if user else None,
                "confidence": round(ev.median_confidence, 4),
                "frames": ev.frames_matched,
                "quality": round(ev.best_quality, 4),
                "occluded_ratio": round(ev.mean_occluded_ratio, 4),
                "antispoof": "passed" if ev.antispoof_evaluated else "not_evaluated",
                "unscheduled": session is None,
                "sighting_id": row.id if row else None,
            }, session_id=sid, camera_id=cam.id)
            return

        if d.kind in (EventKind.AMBIGUOUS, EventKind.SPOOF_SUSPECTED) and ev is not None:
            if ev.identity and ev.identity.isdigit():
                self._write_sighting(db, cam, session, d, ev, int(ev.identity), chip,
                                     confirmed=False)
            emit(d.kind.value, {
                "track_id": d.track_id,
                "user_id": int(ev.identity) if ev.identity and ev.identity.isdigit() else None,
                "reason": ev.review_reason or d.detail,
            }, session_id=sid, camera_id=cam.id)
            return

        if d.kind is EventKind.UNKNOWN_FACE and d.track_id not in unknown_emitted:
            unknown_emitted.add(d.track_id)
            self._write_unknown(db, cam, session, d, chip)
            emit("unknown_face", {
                "track_id": d.track_id,
                "best_score": round(ev.max_confidence, 4) if ev else 0.0,
                "detail": "never auto-assigned — an authority must resolve this",
            }, session_id=sid, camera_id=cam.id)
            return

        if d.kind is EventKind.DISCARDED:
            open_sightings.pop(d.track_id, None)
            if ev is not None and ev.identity and ev.identity.isdigit() and ev.frames_matched:
                self._write_sighting(db, cam, session, d, ev, int(ev.identity), chip,
                                     confirmed=False)

    # --------------------------------------------------------- persistence

    def _write_sighting(self, db, cam: Camera, session: Optional[ClassSession], d: Decision,
                        ev, user_id: int, chip: Optional[np.ndarray],
                        confirmed: bool) -> Optional[Sighting]:
        row = Sighting(
            session_id=session.id if session else None,
            camera_id=cam.id,
            user_id=user_id,
            track_id=d.track_id,
            first_seen=utcnow() - timedelta(seconds=max(ev.span_seconds, 0.0)),
            last_seen=utcnow(),
            frames_matched=ev.frames_matched,
            median_confidence=ev.median_confidence,
            max_confidence=ev.max_confidence,
            best_quality=ev.best_quality,
            mean_occluded_ratio=ev.mean_occluded_ratio,
            confirmed=confirmed,
            antispoof_result="passed" if ev.antispoof_evaluated else "not_evaluated",
            needs_review=ev.needs_review,
            review_reason=ev.review_reason,
            thumbnail_path=self._save_thumb(chip),
        )
        try:
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        except Exception as exc:
            db.rollback()
            log.error("sighting write failed, spooling to disk: %s", exc)
            self._spool({"kind": "sighting", "camera_id": cam.id, "user_id": user_id,
                         "session_id": session.id if session else None,
                         "track_id": d.track_id, "frames": ev.frames_matched,
                         "confidence": ev.median_confidence, "confirmed": confirmed,
                         "at": utcnow().isoformat()})
            return None

    def _extend_sighting(self, db, sighting_id: Optional[int]) -> None:
        """Grow an open track's presence window. Finalized when the track closes."""
        if sighting_id is None:
            return
        row = db.get(Sighting, sighting_id)
        if row is None:
            return
        row.last_seen = utcnow()
        row.frames_matched += 1
        try:
            db.commit()
        except Exception:
            db.rollback()

    def _write_unknown(self, db, cam: Camera, session: Optional[ClassSession],
                       d: Decision, chip: Optional[np.ndarray]) -> None:
        ev = d.evidence
        row = UnknownSighting(
            session_id=session.id if session else None,
            camera_id=cam.id,
            track_id=d.track_id,
            first_seen=utcnow() - timedelta(seconds=max(ev.span_seconds if ev else 0.0, 0.0)),
            last_seen=utcnow(),
            best_score=ev.max_confidence if ev else 0.0,
            frames=ev.frames_matched if ev else 0,
            thumbnail_path=self._save_thumb(chip),
        )
        try:
            db.add(row)
            db.commit()
        except Exception as exc:
            db.rollback()
            log.error("unknown-sighting write failed: %s", exc)

    def _save_thumb(self, chip: Optional[np.ndarray]) -> Optional[str]:
        if chip is None or not self.store_thumbnails:
            return None
        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        path = self.thumb_dir / f"{uuid.uuid4().hex}.jpg"
        try:
            cv2.imwrite(str(path), chip)
            return str(path)
        except cv2.error:
            return None

    # -------------------------------------------------------------- spool

    def _spool(self, payload: dict) -> None:
        """Buffer an event to disk when the database is unavailable."""
        try:
            self.spool.parent.mkdir(parents=True, exist_ok=True)
            with open(self.spool, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, default=str) + "\n")
        except OSError as exc:
            log.error("could not spool event to disk: %s", exc)

    def _flush_spool(self, db) -> None:
        """Replay spooled events once the database is writable again."""
        if not self.spool.exists():
            return
        try:
            lines = self.spool.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        kept: List[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                db.add(Sighting(
                    session_id=rec.get("session_id"), camera_id=rec.get("camera_id"),
                    user_id=rec["user_id"], track_id=rec.get("track_id", -1),
                    first_seen=datetime.fromisoformat(rec["at"]),
                    last_seen=datetime.fromisoformat(rec["at"]),
                    frames_matched=rec.get("frames", 0),
                    median_confidence=rec.get("confidence", 0.0),
                    confirmed=rec.get("confirmed", False),
                    review_reason="replayed from disk spool after a database outage",
                ))
                db.commit()
            except Exception:
                db.rollback()
                kept.append(line)
        try:
            if kept:
                self.spool.write_text("\n".join(kept) + "\n", encoding="utf-8")
            else:
                self.spool.unlink()
                log.info("disk spool flushed and cleared")
        except OSError:
            pass

    # -------------------------------------------------------------- status

    def _resolve_session(self, db, cam: Camera) -> Optional[ClassSession]:
        """The session scheduled for this camera's room right now, with configured slack.

        Never guesses: with no scheduled session the check-in is recorded as an unscheduled
        sighting (session_id NULL) rather than attached to whatever session is nearest.
        """
        now = utcnow()
        early = timedelta(minutes=int(self.cfg.attendance.early_checkin_minutes))
        late = timedelta(minutes=int(self.cfg.attendance.late_checkin_minutes))
        # The slack is applied to `now` rather than to the columns: doing the arithmetic in SQL
        # would bind a timedelta through the UTCDateTime decorator, which only accepts datetimes.
        # (start - early <= now) is the same condition as (start <= now + early).
        stmt = (
            select(ClassSession)
            .where(ClassSession.room == cam.room)
            .where(ClassSession.scheduled_start <= now + early)
            .where(ClassSession.scheduled_end >= now - late)
            .order_by(ClassSession.scheduled_start.desc())
        )
        return db.scalars(stmt).first()

    def _maybe_beat(self, db, cam: Camera, now_mono: float, last_beat: float) -> None:
        if now_mono - last_beat > self.heartbeat_interval_s:
            self._beat(db, cam)

    def _beat(self, db, cam: Camera) -> None:
        try:
            cam.last_heartbeat = utcnow()
            cam.measured_fps = round(self.measured_fps, 2)
            db.commit()
        except Exception:
            db.rollback()

    def _set_status(self, db, cam: Camera, status: CameraStatus, detail: str) -> None:
        try:
            cam.status = status
            cam.status_detail = detail[:300]
            cam.last_heartbeat = utcnow()
            db.commit()
            emit("camera_status", {"camera_id": cam.id, "name": cam.name,
                                   "status": status.value, "detail": detail,
                                   "measured_fps": round(self.measured_fps, 2)},
                 camera_id=cam.id)
        except Exception:
            db.rollback()


# ------------------------------------------------------------------ registry

class WorkerRegistry:
    """Tracks the running worker per camera so the API can start and stop them."""

    def __init__(self) -> None:
        self._workers: Dict[int, CameraWorker] = {}
        self._lock = threading.Lock()

    def start(self, camera_id: int, cfg) -> CameraWorker:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing and existing.is_alive():
                return existing
            w = CameraWorker(camera_id, cfg)
            self._workers[camera_id] = w
            w.start()
            return w

    def stop(self, camera_id: int) -> bool:
        with self._lock:
            w = self._workers.pop(camera_id, None)
        if w is None:
            return False
        w.stop()
        w.join(timeout=5.0)
        return True

    def stop_all(self) -> None:
        for cid in list(self._workers):
            self.stop(cid)

    def is_running(self, camera_id: int) -> bool:
        w = self._workers.get(camera_id)
        return bool(w and w.is_alive())

    def get(self, camera_id: int) -> Optional[CameraWorker]:
        return self._workers.get(camera_id)


registry = WorkerRegistry()
