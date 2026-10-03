"""Phase 2: sign-in hardening, password hashing, token revocation, additive migration."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, inspect


def _legacy_pbkdf2(password: str) -> str:
    salt = b"0123456789abcdef"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 1000)
    return f"pbkdf2_sha256$1000${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def _set(user_id: int, **fields):
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
    finally:
        db.close()


def _get(user_id: int):
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        return db.get(User, user_id)
    finally:
        db.close()


def test_login_accepts_username_email_or_roll_number(api, make_user):
    make_user("asha", email="Asha@College.edu", roll_number="CSE-23-014")
    for ident in ("asha", "asha@college.edu", "ASHA@COLLEGE.EDU", "CSE-23-014"):
        r = api.post("/api/auth/login", json={"username": ident, "password": "password123"})
        assert r.status_code == 200, (ident, r.text)
        assert r.json()["role"] == "student"


def test_wrong_password_never_says_which_part_was_wrong(api, make_user):
    make_user("ravi")
    a = api.post("/api/auth/login", json={"username": "ravi", "password": "nope-nope"})
    b = api.post("/api/auth/login", json={"username": "no-such-user", "password": "nope-nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_account_locks_after_five_failures_then_unlocks(api, make_user):
    uid, _ = make_user("meera")
    for _ in range(5):
        api.post("/api/auth/login", json={"username": "meera", "password": "wrong-pass"})

    r = api.post("/api/auth/login", json={"username": "meera", "password": "password123"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "locked"

    _set(uid, locked_until=datetime.now(timezone.utc) - timedelta(seconds=1))
    r = api.post("/api/auth/login", json={"username": "meera", "password": "password123"})
    assert r.status_code == 200


def test_successful_login_resets_the_failure_counter(api, make_user):
    uid, _ = make_user("kiran")
    for _ in range(4):
        api.post("/api/auth/login", json={"username": "kiran", "password": "wrong-pass"})
    assert api.post("/api/auth/login",
                    json={"username": "kiran", "password": "password123"}).status_code == 200
    assert _get(uid).failed_logins == 0


def test_legacy_pbkdf2_hash_still_signs_in_and_is_upgraded_to_argon2(api, make_user):
    uid, _ = make_user("old-timer")
    _set(uid, password_hash=_legacy_pbkdf2("legacy-pass-1"))

    r = api.post("/api/auth/login", json={"username": "old-timer", "password": "legacy-pass-1"})
    assert r.status_code == 200
    assert _get(uid).password_hash.startswith("$argon2id$")

    # And the upgraded hash keeps working.
    r = api.post("/api/auth/login", json={"username": "old-timer", "password": "legacy-pass-1"})
    assert r.status_code == 200


def test_new_hashes_are_argon2id():
    from app.crypto import hash_password, verify_password

    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2id$")
    assert verify_password("s3cret-pass", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", "garbage$hash")


def test_password_change_revokes_older_tokens(api, make_user):
    uid, headers = make_user("tok")
    assert api.get("/api/me", headers=headers).status_code == 200
    _set(uid, password_changed_at=datetime.now(timezone.utc) + timedelta(seconds=2))
    r = api.get("/api/me", headers=headers)
    assert r.status_code == 401


def test_login_is_rate_limited_per_client(api, make_user, monkeypatch):
    import app.ratelimit as rl

    monkeypatch.setitem(rl.LIMITS, "login", (3, 60.0))
    make_user("spam")
    codes = [api.post("/api/auth/login", json={"username": "spam", "password": "x"}).status_code
             for _ in range(4)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429


def test_rate_limit_ignores_spoofed_forwarded_for_from_untrusted_peer(monkeypatch):
    import app.ratelimit as rl
    from starlette.requests import Request

    scope = {"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4")],
             "client": ("203.0.113.9", 5555)}
    assert rl.client_ip(Request(scope)) == "203.0.113.9"
    scope["client"] = ("127.0.0.1", 5555)
    assert rl.client_ip(Request(scope)) == "1.2.3.4"


def test_pending_unverified_signup_cannot_sign_in(api, make_user):
    from app.db import SessionLocal
    from app.models import StudentProfile

    uid, _ = make_user("newbie", email="newbie@college.edu")
    db = SessionLocal()
    db.add(StudentProfile(user_id=uid, status="pending"))
    db.commit()
    db.close()

    r = api.post("/api/auth/login", json={"username": "newbie", "password": "password123"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "email_unverified"

    _set(uid, email_verified_at=datetime.now(timezone.utc))
    r = api.post("/api/auth/login", json={"username": "newbie", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["student_status"] == "pending"


def test_me_reports_student_status(api, make_user):
    from app.db import SessionLocal
    from app.models import StudentProfile

    uid, headers = make_user("stat")
    db = SessionLocal()
    db.add(StudentProfile(user_id=uid, status="rejected", rejection_reason="wrong section"))
    db.commit()
    db.close()
    me = api.get("/api/me", headers=headers).json()
    assert me["student_status"] == "rejected"
    assert me["rejection_reason"] == "wrong section"


def test_existing_enrollments_and_students_migrate_in_as_approved(tmp_path):
    """An old database gains the new columns with defaults that keep it working unchanged."""
    import sqlite3

    from app.migrate import describe, migrate

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), display_name VARCHAR(128),
            email VARCHAR(200), roll_number VARCHAR(32), role VARCHAR(16), password_hash VARCHAR(256),
            is_active BOOLEAN, phone VARCHAR(32), avatar_url VARCHAR(400), department_id INTEGER,
            deleted_at DATETIME, consent_given BOOLEAN, consent_at DATETIME,
            consent_text_version VARCHAR(32), created_at DATETIME);
        CREATE TABLE student_profiles (id INTEGER PRIMARY KEY, user_id INTEGER, section_id INTEGER,
            admission_year INTEGER, parent_id INTEGER);
        CREATE TABLE sessions (id INTEGER PRIMARY KEY, title VARCHAR(160), room VARCHAR(80),
            camera_id INTEGER, owner_id INTEGER, scheduled_start DATETIME, scheduled_end DATETIME,
            mode VARCHAR(16), grace_minutes INTEGER, min_presence_seconds INTEGER, created_at DATETIME);
        INSERT INTO users (id, username, display_name, role, password_hash, is_active)
            VALUES (1, 'legacy', 'Legacy', 'student', 'x', 1);
        INSERT INTO student_profiles (id, user_id, admission_year) VALUES (1, 1, 2024);
        INSERT INTO sessions (id, title, room, owner_id, mode, grace_minutes, min_presence_seconds)
            VALUES (1, 'old', 'R1', 1, 'kiosk', 10, 1500);
    """)
    con.commit()
    con.close()

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    migrate(engine)
    assert list(describe(engine)) == []                       # idempotent

    cols = {c["name"] for c in inspect(engine).get_columns("student_profiles")}
    assert {"status", "roll_number", "batch_id", "guardian_phone"} <= cols
    with engine.connect() as c:
        from sqlalchemy import text

        assert c.execute(text("SELECT status FROM student_profiles")).scalar() == "approved"
        # Old sessions are history: they must come in closed so nothing re-closes them.
        assert c.execute(text("SELECT state FROM sessions")).scalar() == "closed"
        assert c.execute(text("SELECT failed_logins FROM users")).scalar() == 0
    engine.dispose()
