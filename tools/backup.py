"""Back up and restore the attendance portal: database + uploaded files.

    python tools/backup.py create [--dest var/backups] [--keep 14]
    python tools/backup.py list   [--dest var/backups]
    python tools/backup.py verify <backup-folder>
    python tools/backup.py restore <backup-folder> --yes

A backup is one folder, `attendance-YYYYmmdd-HHMMSS/`, holding:

    database.sqlite   (SQLite: an online, consistent copy made with SQLite's backup API —
     or database.dump  PostgreSQL: `pg_dump --format=custom`, needs pg_dump on PATH)
    uploads.zip       profile photos, leave/issue attachments (var/uploads)
    manifest.json     what was backed up, when, and a SHA-256 of every file

What is NOT in it, on purpose:

  * ATTENDANCE_FERNET_KEY / ATTENDANCE_JWT_SECRET. Face templates and camera passwords in the
    database are encrypted with the Fernet key; a backup restored without that key cannot
    recognise anyone. Keep the key in your password manager / secret store, separately.
  * CCTV review snapshots (var/review): short-lived by design (deleted after the retention
    period set in Settings), so restoring them would undo that promise.

Run `create` daily from Task Scheduler / cron. `--keep N` deletes all but the newest N
backups in --dest. Copy the folder off the machine (another disk, NAS, cloud bucket):
a backup on the same disk as the database does not survive the disk.

`restore` overwrites the current database and uploads. Stop the API server first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "attendance-"

# Same settings as the API server (`uvicorn --env-file .env`); real environment variables win.
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    pass


def db_url() -> str:
    return os.environ.get("ATTENDANCE_DB_URL", "sqlite:///var/attendance.db")


def sqlite_path(url: str) -> Path | None:
    if not url.startswith("sqlite:///"):
        return None
    p = Path(url.replace("sqlite:///", "", 1))
    return p if p.is_absolute() else ROOT / p


def uploads_dir() -> Path:
    p = Path(os.environ.get("ATTENDANCE_UPLOAD_DIR", "var/uploads"))
    return p if p.is_absolute() else ROOT / p


def pg_url(url: str) -> str:
    """pg_dump wants a libpq URL; SQLAlchemy's driver suffix (+psycopg) must go."""
    scheme, rest = url.split("://", 1)
    return "postgresql://" + rest if scheme.startswith("postgres") else url


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> None:
    print(f"backup: {msg}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------------- create

def create(dest: Path, keep: int) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = dest / f"{PREFIX}{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    url = db_url()
    files: dict[str, str] = {}
    try:
        src = sqlite_path(url)
        if src is not None:
            if not src.exists():
                fail(f"database file not found: {src}")
            target = out / "database.sqlite"
            # The backup API copies a consistent snapshot while the server keeps writing
            # (WAL mode); a plain file copy could catch a half-written page.
            with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(target) as d:
                s.backup(d)
            with sqlite3.connect(target) as d:
                ok = d.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                fail(f"integrity check of the copy failed: {ok}")
            files["database.sqlite"] = sha256(target)
            kind = "sqlite"
        elif url.startswith("postgres"):
            if shutil.which("pg_dump") is None:
                fail("pg_dump is not on PATH. Install the PostgreSQL client tools.")
            target = out / "database.dump"
            r = subprocess.run(["pg_dump", "--format=custom", "--no-owner", f"--file={target}", pg_url(url)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                fail(f"pg_dump failed: {r.stderr.strip()}")
            files["database.dump"] = sha256(target)
            kind = "postgresql"
        else:
            fail(f"unsupported database URL scheme: {url.split(':', 1)[0]}")

        up = uploads_dir()
        count = 0
        with zipfile.ZipFile(out / "uploads.zip", "w", zipfile.ZIP_DEFLATED) as z:
            if up.exists():
                for p in sorted(up.rglob("*")):
                    if p.is_file():
                        z.write(p, p.relative_to(up).as_posix())
                        count += 1
        files["uploads.zip"] = sha256(out / "uploads.zip")

        (out / "manifest.json").write_text(json.dumps({
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "database": kind,
            "uploads": count,
            "files": files,
            "note": "Restoring needs the same ATTENDANCE_FERNET_KEY the server used.",
        }, indent=2), encoding="utf-8")
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise

    size = sum(p.stat().st_size for p in out.iterdir()) / 1e6
    print(f"backup written: {out}  ({size:.1f} MB, {count} uploaded files)")
    prune(dest, keep)
    return out


def backups(dest: Path) -> list[Path]:
    return sorted((p for p in dest.glob(f"{PREFIX}*") if (p / "manifest.json").exists()), key=lambda p: p.name)


def prune(dest: Path, keep: int) -> None:
    if keep <= 0:
        return
    for old in backups(dest)[:-keep]:
        shutil.rmtree(old)
        print(f"removed old backup: {old.name}")


# ------------------------------------------------------------------- verify

def verify(folder: Path) -> dict:
    mf = folder / "manifest.json"
    if not mf.exists():
        fail(f"{folder} is not a backup folder (no manifest.json)")
    manifest = json.loads(mf.read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        p = folder / name
        if not p.exists():
            fail(f"missing file: {name}")
        if sha256(p) != digest:
            fail(f"checksum mismatch: {name} — this backup is damaged")
    if manifest["database"] == "sqlite":
        with sqlite3.connect(folder / "database.sqlite") as d:
            ok = d.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            fail(f"database integrity check failed: {ok}")
    with zipfile.ZipFile(folder / "uploads.zip") as z:
        bad = z.testzip()
        if bad:
            fail(f"uploads.zip is damaged at {bad}")
    return manifest


# ------------------------------------------------------------------ restore

def restore(folder: Path) -> None:
    manifest = verify(folder)
    url = db_url()
    if manifest["database"] == "sqlite":
        dst = sqlite_path(url)
        if dst is None:
            fail("this is a SQLite backup but ATTENDANCE_DB_URL points at another database")
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Restore through the backup API too: it replaces the content in place, so a stale
        # -wal / -shm pair next to the file cannot resurrect old pages.
        with sqlite3.connect(folder / "database.sqlite") as s, sqlite3.connect(dst) as d:
            s.backup(d)
    else:
        if not url.startswith("postgres"):
            fail("this is a PostgreSQL backup but ATTENDANCE_DB_URL is not PostgreSQL")
        if shutil.which("pg_restore") is None:
            fail("pg_restore is not on PATH. Install the PostgreSQL client tools.")
        r = subprocess.run(["pg_restore", "--clean", "--if-exists", "--no-owner",
                            f"--dbname={pg_url(url)}", str(folder / "database.dump")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"pg_restore failed: {r.stderr.strip()}")

    up = uploads_dir()
    if up.exists():
        shutil.rmtree(up)
    up.mkdir(parents=True)
    with zipfile.ZipFile(folder / "uploads.zip") as z:
        for info in z.infolist():
            target = (up / info.filename).resolve()
            if up.resolve() not in target.parents:          # no ../ escapes
                fail(f"unsafe path in uploads.zip: {info.filename}")
            z.extract(info, up)
    print(f"restored {folder.name}: database ({manifest['database']}) and {manifest['uploads']} uploaded files")
    print("Start the API server again. It needs the same ATTENDANCE_FERNET_KEY as when the backup was made.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Back up / restore the attendance portal.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="make a new backup")
    c.add_argument("--dest", type=Path, default=ROOT / "var" / "backups")
    c.add_argument("--keep", type=int, default=14, help="keep only the newest N backups (0 = keep all)")
    ls = sub.add_parser("list", help="list backups")
    ls.add_argument("--dest", type=Path, default=ROOT / "var" / "backups")
    v = sub.add_parser("verify", help="check a backup's checksums and integrity")
    v.add_argument("folder", type=Path)
    r = sub.add_parser("restore", help="overwrite the current data with a backup")
    r.add_argument("folder", type=Path)
    r.add_argument("--yes", action="store_true", help="confirm: the current data will be replaced")
    args = ap.parse_args()

    if args.cmd == "create":
        create(args.dest, args.keep)
    elif args.cmd == "list":
        for b in backups(args.dest):
            m = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
            print(f"{b.name}  {m['database']:<10}  {m['uploads']:>5} files  {m['created_at']}")
    elif args.cmd == "verify":
        m = verify(args.folder)
        print(f"OK: {args.folder.name} ({m['database']}, {m['uploads']} uploaded files)")
    elif args.cmd == "restore":
        if not args.yes:
            fail("restore REPLACES the current database and uploads. Stop the server, then re-run with --yes.")
        restore(args.folder)


if __name__ == "__main__":
    main()
