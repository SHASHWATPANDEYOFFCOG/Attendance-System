"""Background jobs, run on one daemon thread inside the API process.

Each job is a plain function `(db) -> None` with its own interval. A failing job is logged and
retried on its next tick; it never takes the others down. Jobs are idempotent, so a restart
mid-tick (or two ticks overlapping after a long pause) can never double-apply anything.

Disabled when ATTENDANCE_DISABLE_BACKGROUND=1 (the test suite drives jobs directly instead).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List

from app.db import SessionLocal
from occlubio.utils import get_logger

log = get_logger("app.scheduler")


@dataclass
class Job:
    name: str
    interval_s: float
    fn: Callable
    last_run: float = field(default=0.0)


class Scheduler:
    def __init__(self) -> None:
        self.jobs: List[Job] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def add(self, name: str, interval_s: float, fn: Callable) -> None:
        self.jobs.append(Job(name, interval_s, fn))

    def start(self) -> None:
        if os.environ.get("ATTENDANCE_DISABLE_BACKGROUND") == "1":
            log.info("background jobs disabled by ATTENDANCE_DISABLE_BACKGROUND")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self._thread.start()
        log.info("scheduler started: %s", ", ".join(j.name for j in self.jobs))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def run_once(self, name: str) -> None:
        for j in self.jobs:
            if j.name == name:
                self._run(j)

    def _run(self, job: Job) -> None:
        db = SessionLocal()
        try:
            job.fn(db)
        except Exception:                      # noqa: BLE001 - a job must never kill the loop
            db.rollback()
            log.exception("job %s failed", job.name)
        finally:
            db.close()
            job.last_run = time.monotonic()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            for job in self.jobs:
                if now - job.last_run >= job.interval_s:
                    self._run(job)
            self._stop.wait(1.0)


scheduler = Scheduler()


def _dispatch_emails(db) -> None:
    from app import settings_service
    from app.notify import dispatch_emails
    from app.runtime import cfg, public_base_url

    dispatch_emails(db, public_base_url(), str(settings_service.get(db, cfg, "org_name")))


def _sessions(db) -> None:
    from app.runtime import cfg
    from app.session_service import tick

    tick(db, cfg)


scheduler.add("email", 5.0, _dispatch_emails)
scheduler.add("sessions", 30.0, _sessions)
