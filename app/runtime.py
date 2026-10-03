"""Process-wide configuration, shared by app/api.py and the routers in app/routes/.

Kept in its own module so a router can import `cfg` without importing app.api (which imports
the routers) — the circular import that would otherwise follow.
"""
from __future__ import annotations

import os

from occlubio import load_config

cfg = load_config()


def public_base_url() -> str:
    """Where the web app lives, for links in emails (reset password, open notification)."""
    return os.environ.get("ATTENDANCE_PUBLIC_URL", "http://localhost:3001").rstrip("/")
