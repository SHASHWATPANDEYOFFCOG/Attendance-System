"""Shared fixtures.

Environment is configured **before** any `app.*` import, because `app/db.py` resolves its
database URL at import time. Nothing here downloads a model or opens a camera: the pipeline is
replaced with a stub so the API suite runs in under a second.
"""
from __future__ import annotations

import copy
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

_TMP = Path(tempfile.mkdtemp(prefix="attendance-tests-"))
os.environ["ATTENDANCE_DB_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["ATTENDANCE_JWT_SECRET"] = "test-secret-not-for-production-" + "0" * 32
os.environ["ATTENDANCE_FERNET_KEY"] = Fernet.generate_key().decode()
os.environ["ATTENDANCE_ENV"] = "test"

from occlubio import load_config  # noqa: E402


@pytest.fixture()
def cfg():
    """The real configs/default.yaml — so the tests also guard the shipped thresholds."""
    return copy.deepcopy(load_config())


@pytest.fixture()
def t0() -> datetime:
    return datetime(2026, 7, 29, 9, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------- API fixtures

class StubPipeline:
    """Stands in for PipelineService so the API suite needs no 300 MB model."""

    antispoof_available = False

    def detect(self, frame):
        return []

    def align(self, frame, face):
        return frame

    def assess(self, chip, det_score):
        return True, 1.0, {"type": "clear", "occluded_ratio": 0.0}, {"live": True, "score": 1.0}

    def embed(self, frame, face, chip):
        raise AssertionError("the stub pipeline should never be asked to embed")


@pytest.fixture()
def api(monkeypatch):
    """A fresh database and TestClient per test."""
    from fastapi.testclient import TestClient

    import app.pipeline_service as ps
    from app.db import engine
    from app.models import Base
    import app.gallery_service as gs

    import app.settings_service as settings_service
    from app.ratelimit import limiter

    monkeypatch.setattr(ps, "_instance", StubPipeline())
    monkeypatch.setattr("app.api.get_pipeline", lambda _cfg: StubPipeline())
    gs.invalidate()
    settings_service.invalidate()       # cached settings belong to the previous test's database
    limiter.reset()

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from app.api import app as fastapi_app

    with TestClient(fastapi_app) as client:
        yield client

    Base.metadata.drop_all(engine)
    gs.invalidate()


@pytest.fixture()
def make_user(api):
    """Create a user of any role directly in the DB and return (user_id, auth headers)."""
    from app.crypto import hash_password
    from app.db import SessionLocal
    from app.models import Role, User
    from app.auth import create_token

    created: list[int] = []

    def _make(username: str, role: str = "student", password: str = "password123",
              consent: bool = True, **kw):
        db = SessionLocal()
        try:
            u = User(
                username=username,
                display_name=kw.pop("display_name", username.title()),
                role=Role(role),
                password_hash=hash_password(password),
                consent_given=consent,
                consent_at=datetime.now(timezone.utc) if consent else None,
                **kw,
            )
            db.add(u)
            db.commit()
            db.refresh(u)
            created.append(u.id)
            token = create_token(u, "access")
            return u.id, {"Authorization": f"Bearer {token}"}
        finally:
            db.close()

    return _make


@pytest.fixture()
def make_session(api):
    """Create a ClassSession owned by `owner_id`, with an optional roster."""
    from app.db import SessionLocal
    from app.models import ClassSession, RosterEntry

    def _make(owner_id: int, roster=(), *, room="R1", mode="kiosk",
              start=None, minutes=50, grace=10, min_presence=1500):
        start = start or datetime.now(timezone.utc) - timedelta(minutes=5)
        db = SessionLocal()
        try:
            s = ClassSession(
                title="Test Session", room=room, owner_id=owner_id,
                scheduled_start=start, scheduled_end=start + timedelta(minutes=minutes),
                mode=mode, grace_minutes=grace, min_presence_seconds=min_presence,
            )
            db.add(s)
            db.commit()
            db.refresh(s)
            for uid in roster:
                db.add(RosterEntry(session_id=s.id, user_id=uid))
            db.commit()
            return s.id
        finally:
            db.close()

    return _make
