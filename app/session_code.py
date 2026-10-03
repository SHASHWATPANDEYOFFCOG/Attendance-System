"""The rotating classroom code shown on the teacher's screen (as digits and as a QR code).

code(step) = HMAC-SHA256(session secret, step) -> 6 digits, step = floor(unix_time / rotation).

The secret is per session and never leaves the server except as the current code, so a code
photographed and sent to a friend outside dies within one rotation (plus one step of grace for a
student who was mid-scan when it changed). It proves "you could see the classroom screen just
now"; the geofence and face match prove the rest.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Optional


def new_secret() -> str:
    return secrets.token_hex(24)


def _code(secret: str, step: int) -> str:
    mac = hmac.new(bytes.fromhex(secret), str(step).encode(), hashlib.sha256).digest()
    n = int.from_bytes(mac[:4], "big") % 1_000_000
    return f"{n:06d}"


def current(secret: str, rotation_s: int, now: Optional[float] = None) -> tuple[str, int]:
    """(code, seconds until it changes)."""
    t = time.time() if now is None else now
    step = int(t // rotation_s)
    remaining = rotation_s - int(t - step * rotation_s)
    return _code(secret, step), remaining


def verify(secret: Optional[str], code: str, rotation_s: int, now: Optional[float] = None) -> bool:
    if not secret or not code or not code.strip().isdigit():
        return False
    t = time.time() if now is None else now
    step = int(t // rotation_s)
    given = code.strip().zfill(6)
    # Current step, plus the previous one so a scan that straddles a rotation still counts.
    return any(hmac.compare_digest(_code(secret, s), given) for s in (step, step - 1))
