"""File uploads: verified type, bounded size, private storage, random names.

* The **real** type is read from the file's leading bytes (magic numbers). The extension and the
  browser-supplied Content-Type are ignored for the decision, so `evil.html` renamed `note.pdf`
  is rejected.
* Size is enforced while reading, so a 2 GB upload is cut off at the limit rather than buffered.
* Bytes land under `var/uploads/` with a random name and no extension — never inside a folder a
  web server would serve — and are only ever returned through `GET /api/files/{id}`, which checks
  that the caller may see the record the file is attached to.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from pathlib import Path
from typing import Iterable, Optional, Tuple

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models import StoredFile

MB = 1024 * 1024

# kind -> (content type, predicate on the first bytes)
_SIGNATURES = {
    "pdf": ("application/pdf", lambda b: b.startswith(b"%PDF-")),
    "png": ("image/png", lambda b: b.startswith(b"\x89PNG\r\n\x1a\n")),
    "jpeg": ("image/jpeg", lambda b: b.startswith(b"\xff\xd8\xff")),
    "webp": ("image/webp", lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             lambda b: b.startswith(b"PK\x03\x04")),
}

DOCUMENTS = ("pdf", "png", "jpeg")          # leave certificates, issue attachments
IMAGES = ("png", "jpeg", "webp")             # profile photos


def upload_dir() -> Path:
    return Path(os.environ.get("ATTENDANCE_UPLOAD_DIR", "var/uploads"))


def sniff(head: bytes, allowed: Iterable[str]) -> Optional[Tuple[str, str]]:
    for kind in allowed:
        ctype, check = _SIGNATURES[kind]
        if check(head):
            return kind, ctype
    return None


def _safe_name(name: Optional[str]) -> str:
    base = os.path.basename(name or "file")
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip() or "file"
    return base[:150]


async def read_limited(upload: UploadFile, max_bytes: int) -> bytes:
    chunks, total = [], 0
    while True:
        chunk = await upload.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"{upload.filename or 'File'} is larger than "
                                     f"{max_bytes // MB} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def store_bytes(db: Session, data: bytes, *, owner_id: Optional[int], purpose: str,
                original_name: Optional[str], allowed: Iterable[str]) -> StoredFile:
    allowed = tuple(allowed)
    if not data:
        raise HTTPException(422, "The file is empty.")
    found = sniff(data[:16], allowed)
    if found is None:
        names = ", ".join(k.upper() for k in allowed).replace("JPEG", "JPG")
        raise HTTPException(415, f"Unsupported file type. Allowed: {names}.")
    _kind, ctype = found

    folder = upload_dir()
    folder.mkdir(parents=True, exist_ok=True)
    storage = secrets.token_hex(20)
    (folder / storage).write_bytes(data)

    row = StoredFile(owner_id=owner_id, purpose=purpose, original_name=_safe_name(original_name),
                     content_type=ctype, size=len(data),
                     sha256=hashlib.sha256(data).hexdigest(), storage_name=storage)
    db.add(row)
    db.flush()
    return row


async def save_upload(db: Session, upload: UploadFile, *, owner_id: Optional[int], purpose: str,
                      allowed: Iterable[str] = DOCUMENTS, max_bytes: int = 5 * MB) -> StoredFile:
    data = await read_limited(upload, max_bytes)
    return store_bytes(db, data, owner_id=owner_id, purpose=purpose,
                       original_name=upload.filename, allowed=allowed)


def file_path(row: StoredFile) -> Path:
    # storage_name is our own random hex; never a user-controlled path.
    if not re.fullmatch(r"[0-9a-f]{40}", row.storage_name or ""):
        raise HTTPException(404, "file not found")
    return upload_dir() / row.storage_name


def delete_file(db: Session, row: Optional[StoredFile]) -> None:
    if row is None:
        return
    try:
        file_path(row).unlink(missing_ok=True)
    except (OSError, HTTPException):
        pass
    db.delete(row)
