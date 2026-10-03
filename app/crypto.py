"""Encryption for face templates, and password hashing.

A face embedding is not like a password. If a password database leaks, everyone rotates their
password. If a template database leaks, the subject cannot rotate their face — the compromise is
permanent and follows them to every other system that uses face recognition. So the embedding
column is encrypted at rest with a key that lives outside the database.

This is envelope-free symmetric encryption (Fernet: AES-128-CBC + HMAC-SHA256). It protects
against a stolen `.db` file, which is the realistic threat for a self-hosted deployment. It does
NOT protect against an attacker who also has the key, and it is not biometric template
protection in the cryptographic sense (cancellable biometrics / fuzzy vaults) — the architecture
doc flags that as a separate, unimplemented hook.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Optional

import numpy as np
from cryptography.fernet import Fernet, InvalidToken

from occlubio.utils import get_logger, l2_normalize

log = get_logger("app.crypto")

_KEY_ENV = "ATTENDANCE_FERNET_KEY"
_ENV_ENV = "ATTENDANCE_ENV"
_DEV_KEY_PATH = Path("var") / "dev_fernet.key"

_PBKDF2_ROUNDS = 200_000
_fernet: Optional[Fernet] = None


def _load_key() -> bytes:
    """Resolve the encryption key, refusing to invent one in production."""
    raw = os.environ.get(_KEY_ENV)
    if raw:
        return raw.encode()

    if os.environ.get(_ENV_ENV, "development").lower() == "production":
        raise RuntimeError(
            f"{_KEY_ENV} is not set and {_ENV_ENV}=production. Refusing to start: face "
            f"templates would be written with an ephemeral key. Generate one with "
            f"`python -c \"from cryptography.fernet import Fernet; "
            f"print(Fernet.generate_key().decode())\"` and set it in the environment."
        )

    # Development convenience only: a key persisted beside the database so restarts can still
    # read existing templates. Never acceptable in production — hence the guard above.
    if _DEV_KEY_PATH.exists():
        return _DEV_KEY_PATH.read_bytes().strip()
    _DEV_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    _DEV_KEY_PATH.write_bytes(key)
    log.warning(
        "%s not set — generated a DEVELOPMENT key at %s. Set %s before any real deployment.",
        _KEY_ENV, _DEV_KEY_PATH, _KEY_ENV,
    )
    return key


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_key())
    return _fernet


def reset_cache() -> None:
    """Drop the cached key. Used by tests that swap the environment."""
    global _fernet
    _fernet = None


# ----------------------------------------------------------------- embeddings

def encrypt_embedding(vec: np.ndarray) -> bytes:
    """L2-normalise, then encrypt a float32 template for storage.

    Normalising here means every template in the database is already unit-length, so the FAISS
    IndexFlatIP rebuild is a pure cosine index no matter which path inserted the row.
    """
    v = l2_normalize(np.asarray(vec, dtype=np.float32).ravel())
    return fernet().encrypt(v.tobytes())


def decrypt_embedding(blob: bytes, dim: int = 512) -> np.ndarray:
    """Decrypt a stored template back to a unit-length float32 vector."""
    try:
        raw = fernet().decrypt(blob)
    except InvalidToken as exc:
        raise RuntimeError(
            "Could not decrypt a face template. The encryption key does not match the one used "
            f"to write it — check {_KEY_ENV}."
        ) from exc
    v = np.frombuffer(raw, dtype=np.float32)
    if v.size != dim:
        raise ValueError(f"decrypted template has dim {v.size}, expected {dim}")
    return l2_normalize(v.copy())


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256. Stdlib only, no native build step on Windows."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}" \
           f"${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification; never raises on a malformed hash."""
    try:
        algo, rounds, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 base64.b64decode(salt_b64), int(rounds))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False
