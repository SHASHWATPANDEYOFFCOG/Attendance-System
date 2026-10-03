"""CCTV support used by the camera worker and the camera routes.

* Stream credentials are stored Fernet-encrypted and spliced into the URL only in memory, at the
  moment the stream is opened. Anything shown in the UI or written to logs is the masked URL.
* Review snapshots (near-threshold matches) are the only images the CCTV path ever writes, and
  they are encrypted on disk, kept `review_retention_days`, then deleted. Raw video is never
  written; unknown faces are never written at all.
"""
from __future__ import annotations

import base64
import os
import secrets
import threading
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote, urlsplit, urlunsplit

import cv2
import numpy as np

from app.crypto import decrypt_bytes, decrypt_text, encrypt_bytes
from app.models import Camera


def mask_source(source: str) -> str:
    """rtsp://user:pass@host/x -> rtsp://***@host/x (never show credentials)."""
    try:
        parts = urlsplit(source)
    except ValueError:
        return source
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment))
    return source


def stream_url(cam: Camera) -> str:
    """The URL to open, with decrypted credentials inserted. Only ever held in memory."""
    src = cam.source or ""
    user = decrypt_text(cam.username_encrypted)
    password = decrypt_text(cam.password_encrypted)
    if not user or src.isdigit() or "://" not in src:
        return src
    parts = urlsplit(src)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    cred = quote(user, safe="") + (f":{quote(password, safe='')}" if password else "")
    return urlunsplit((parts.scheme, f"{cred}@{host}", parts.path, parts.query, parts.fragment))


def grab_frame(url: str, timeout_s: float = 12.0) -> Tuple[Optional[np.ndarray], str]:
    """Open a stream and read one frame, without hanging the request on a dead RTSP host."""
    result: dict = {}

    def work():
        cap = None
        try:
            cap = cv2.VideoCapture(int(url)) if url.isdigit() else cv2.VideoCapture(url)
            if not cap.isOpened():
                result["error"] = "The stream could not be opened. Check the address, port and credentials."
                return
            for _ in range(5):                     # the first frames of some cameras are blank
                ok, frame = cap.read()
                if ok and frame is not None:
                    result["frame"] = frame
            if "frame" not in result:
                result["error"] = "Connected, but no video frames arrived."
        except Exception as exc:                   # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if cap is not None:
                cap.release()

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return None, f"No response within {timeout_s:.0f} seconds. Check the camera is on the network."
    return result.get("frame"), result.get("error", "")


def jpeg_data_url(frame: np.ndarray, max_width: int = 960) -> str:
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""


# -------------------------------------------------------------- review crops

def review_dir() -> Path:
    return Path(os.environ.get("ATTENDANCE_REVIEW_DIR", "var/review"))


def save_review_crop(chip: Optional[np.ndarray]) -> Optional[str]:
    if chip is None:
        return None
    ok, buf = cv2.imencode(".jpg", chip, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return None
    folder = review_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{secrets.token_hex(16)}.bin"
    path.write_bytes(encrypt_bytes(buf.tobytes()))
    return str(path)


def load_review_crop(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        return "data:image/jpeg;base64," + base64.b64encode(decrypt_bytes(p.read_bytes())).decode()
    except Exception:                               # noqa: BLE001 - wrong key / corrupt file
        return None


def delete_review_crop(path: Optional[str]) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
