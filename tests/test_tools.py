"""The operator tools: demo seed and backup/restore, run as the operator would (subprocesses)."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(args, env, check=True):
    r = subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    if check and r.returncode != 0:
        raise AssertionError(f"{args} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
    return r


@pytest.fixture()
def env(tmp_path):
    e = dict(os.environ)
    e.update({
        "ATTENDANCE_DB_URL": f"sqlite:///{(tmp_path / 'portal.db').as_posix()}",
        "ATTENDANCE_UPLOAD_DIR": str(tmp_path / "uploads"),
        "ATTENDANCE_DISABLE_BACKGROUND": "1",
        "ATTENDANCE_ENV": "test",
        "PYTHONIOENCODING": "utf-8",
    })
    return e


def count(db: Path, sql: str) -> int:
    with sqlite3.connect(db) as c:
        return c.execute(sql).fetchone()[0]


def test_seed_builds_the_demo_college_and_refuses_to_duplicate_it(env, tmp_path):
    out = run(["tools/seed_portal.py", "--password", "Demo-Pass-123", "--weeks", "3"], env).stdout
    assert "Demo-Pass-123" in out and "teacher.cse" in out
    db = tmp_path / "portal.db"
    assert count(db, "select count(*) from users where role='student'") == 31
    assert count(db, "select count(*) from student_profiles where status='pending'") == 1
    assert count(db, "select count(*) from users where role='faculty'") == 3
    assert count(db, "select count(*) from batches") == 2
    assert count(db, "select count(*) from sessions where state='closed'") > 0
    statuses = {r[0] for r in sqlite3.connect(db).execute("select distinct status from attendance_records")}
    assert {"present", "absent"} <= statuses
    methods = {r[0] for r in sqlite3.connect(db).execute("select distinct source from attendance_records")}
    assert {"cctv", "mobile", "system"} <= methods

    again = run(["tools/seed_portal.py", "--password", "Demo-Pass-123"], env, check=False)
    assert again.returncode != 0 and "--reset" in again.stderr
    assert count(db, "select count(*) from departments") == 3      # nothing was added twice


def test_seed_refuses_production(env):
    env["ATTENDANCE_ENV"] = "production"
    r = run(["tools/seed_portal.py", "--password", "Demo-Pass-123"], env, check=False)
    assert r.returncode != 0 and "production" in r.stderr


def test_backup_round_trip_restores_database_and_uploads(env, tmp_path):
    run(["tools/seed_portal.py", "--password", "Demo-Pass-123", "--weeks", "1"], env)
    uploads = tmp_path / "uploads"
    (uploads / "ab").mkdir(parents=True)
    (uploads / "ab" / "photo.jpg").write_bytes(b"\xff\xd8\xff original")
    db = tmp_path / "portal.db"
    students = count(db, "select count(*) from users where role='student'")

    dest = tmp_path / "backups"
    run(["tools/backup.py", "create", "--dest", str(dest)], env)
    (folder,) = list(dest.iterdir())
    assert "OK" in run(["tools/backup.py", "verify", str(folder)], env).stdout

    # Disaster: data lost, a file changed.
    with sqlite3.connect(db) as c:
        c.execute("delete from attendance_records")
        c.execute("delete from users where role='student'")
    (uploads / "ab" / "photo.jpg").write_bytes(b"overwritten")
    (uploads / "stray.txt").write_text("not in the backup")

    refused = run(["tools/backup.py", "restore", str(folder)], env, check=False)
    assert refused.returncode != 0 and "--yes" in refused.stderr
    run(["tools/backup.py", "restore", str(folder), "--yes"], env)

    assert count(db, "select count(*) from users where role='student'") == students
    assert count(db, "select count(*) from attendance_records") > 0
    assert (uploads / "ab" / "photo.jpg").read_bytes() == b"\xff\xd8\xff original"
    assert not (uploads / "stray.txt").exists()


def test_backup_verify_detects_damage_and_keep_prunes_old_backups(env, tmp_path):
    run(["tools/seed_portal.py", "--password", "Demo-Pass-123", "--weeks", "1"], env)
    dest = tmp_path / "backups"
    for _ in range(3):
        run(["tools/backup.py", "create", "--dest", str(dest), "--keep", "2"], env)
        # Folder names have one-second resolution.
        import time
        time.sleep(1.1)
    folders = sorted(dest.iterdir())
    assert len(folders) == 2

    with (folders[-1] / "database.sqlite").open("r+b") as f:
        f.seek(5000)
        f.write(b"corrupt")
    bad = run(["tools/backup.py", "verify", str(folders[-1])], env, check=False)
    assert bad.returncode != 0 and "checksum" in bad.stderr
