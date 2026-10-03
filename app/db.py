"""Database engine and session lifecycle."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base

DB_URL = os.environ.get("ATTENDANCE_DB_URL", "sqlite:///var/attendance.db")

if DB_URL.startswith("sqlite:///") and ":memory:" not in DB_URL:
    Path(DB_URL.replace("sqlite:///", "")).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DB_URL,
    future=True,
    # The camera worker runs on its own thread; SQLite's default same-thread check would
    # reject its connections.
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL keeps the worker's writes from blocking dashboard reads."""
    if not DB_URL.startswith("sqlite"):
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create missing tables, then add missing columns and indexes. Idempotent.

    Running the additive migrator here (not just `create_all`) means an existing database picks
    up new columns on the next start instead of failing at query time.
    """
    from app.migrate import migrate

    migrate(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
