"""Runtime settings an admin edits from the UI, typed and validated.

`configs/default.yaml` stays the source of truth for the recognition *pipeline*; this module
holds the policy knobs (minimum %, time windows, geofence, retry limits, retention). Each key has
exactly one default, taken from the YAML where the YAML already defines it, so there is never a
second, disagreeing default hiding in code.

Values are stored as strings in the existing `settings` table and parsed through the spec below,
so a bad value is rejected when it is *written*, not discovered when a student is refused.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting, utcnow


@dataclass(frozen=True)
class Spec:
    kind: str                         # int | float | bool | str | float?
    default: Callable[[Any], Any]     # cfg -> default value
    label: str
    help: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    group: str = "general"


def _cfg(path: str, fallback):
    def get(cfg):
        node = cfg
        for part in path.split("."):
            node = getattr(node, part, None)
            if node is None:
                return fallback
        return node
    return get


def _const(v):
    return lambda _cfg: v


SPECS: Dict[str, Spec] = {
    # ---- attendance policy -------------------------------------------------------------
    "org_name": Spec("str", _cfg("attendance.organisation", "Attendance Register"),
                     "College / institute name", "Printed on every report and email.",
                     group="general"),
    "staff_registration_approval": Spec(
        "bool", _const(False), "Staff registrations need approval",
        "Off: a teacher who registers at /authority/register can sign in as soon as their email "
        "is verified (anyone who knows the address can then see their branch's students). On: an "
        "administrator or HOD approves each request first. HOD rights are never self-granted.",
        group="general"),
    "min_attendance_pct": Spec("float", _cfg("attendance.minimum_attendance_pct", 75.0),
                               "Minimum attendance %", min=0, max=100, group="policy"),
    "present_window_min": Spec("int", _const(10), "Present window (minutes after start)",
                               "Marked within this many minutes of the start: Present.",
                               min=0, max=180, group="policy"),
    "late_window_min": Spec("int", _const(20), "Late window (minutes after start)",
                            "After the present window and up to this: Late. After it: Absent.",
                            min=0, max=240, group="policy"),
    "leave_backdate_days": Spec("int", _const(7), "Leave back-dating limit (days)",
                                "How far back a student may apply for leave.", min=0, max=60,
                                group="policy"),
    "auto_sessions": Spec("bool", _const(True), "Start sessions from the timetable",
                          "Open each lecture automatically at its start time.", group="policy"),

    # ---- mobile / QR ---------------------------------------------------------------------
    "geofence_enabled": Spec("bool", _const(True), "Enforce campus geofence", group="mobile"),
    "campus_lat": Spec("float?", _const(None), "Campus latitude", min=-90, max=90, group="mobile"),
    "campus_lng": Spec("float?", _const(None), "Campus longitude", min=-180, max=180,
                       group="mobile"),
    "geofence_radius_m": Spec("float", _const(250.0), "Geofence radius (metres)", min=10,
                              max=20000, group="mobile"),
    "geo_max_accuracy_m": Spec("float", _const(150.0), "Worst accepted GPS accuracy (metres)",
                               "Readings less precise than this are refused.", min=5, max=5000,
                               group="mobile"),
    "require_session_code": Spec("bool", _const(False), "Require the rotating session code",
                                 "Students must enter/scan the code shown in class.",
                                 group="mobile"),
    "session_code_rotation_s": Spec("int", _const(30), "Code rotation (seconds)", min=10,
                                    max=300, group="mobile"),
    "selfmark_retry_limit": Spec("int", _const(3), "Failed attempts allowed per lecture", min=1,
                                 max=20, group="mobile"),

    # ---- face ------------------------------------------------------------------------------
    "face_match_threshold": Spec("float", _cfg("gallery.match_threshold", 0.45),
                                 "Face match threshold (cosine)",
                                 "Tune with tools/roc.py on your own enrolled faces.",
                                 min=0.1, max=0.95, group="face"),
    "face_review_threshold": Spec("float", _cfg("gallery.review_threshold", 0.32),
                                  "CCTV review threshold (cosine)",
                                  "Matches between this and the match threshold go to review.",
                                  min=0.05, max=0.95, group="face"),
    "cctv_confirm_frames": Spec("int", _const(3), "CCTV frames needed to mark", min=1, max=30,
                                group="face"),
    "cctv_frame_interval_s": Spec("float", _const(2.0), "CCTV frame interval (seconds)",
                                  "How often a camera frame is analysed.", min=0.2, max=30,
                                  group="face"),

    # ---- retention -------------------------------------------------------------------------
    "review_retention_days": Spec("int", _const(7), "Review snapshots kept (days)", min=1,
                                  max=90, group="retention"),
    "thumbnail_retention_days": Spec("int", _cfg("attendance.retention_days", 30),
                                     "Recognition crops kept (days)", min=1, max=365,
                                     group="retention"),

    # ---- notifications ---------------------------------------------------------------------
    "weekly_summary_enabled": Spec("bool", _const(False), "Weekly summary email",
                                   "Monday-morning summary to students (and guardians).",
                                   group="notifications"),
}


class SettingsError(ValueError):
    pass


def _parse(key: str, raw: Any) -> Any:
    spec = SPECS[key]
    kind = spec.kind
    if kind == "float?" and (raw is None or str(raw).strip() == ""):
        return None
    try:
        if kind == "bool":
            if isinstance(raw, bool):
                val: Any = raw
            else:
                s = str(raw).strip().lower()
                if s not in ("true", "false", "1", "0", "yes", "no", "on", "off"):
                    raise ValueError
                val = s in ("true", "1", "yes", "on")
        elif kind == "int":
            val = int(float(raw))
            if float(raw) != val:
                raise ValueError
        elif kind in ("float", "float?"):
            val = float(raw)
        else:
            val = str(raw).strip()
            if not val:
                raise ValueError
    except (TypeError, ValueError):
        raise SettingsError(f"{spec.label}: {raw!r} is not a valid {kind.rstrip('?')}")
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if spec.min is not None and val < spec.min:
            raise SettingsError(f"{spec.label} must be at least {spec.min:g}")
        if spec.max is not None and val > spec.max:
            raise SettingsError(f"{spec.label} must be at most {spec.max:g}")
    return val


_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def all_settings(db: Session, cfg) -> Dict[str, Any]:
    """Every setting, stored value or default. Cached until the next write."""
    global _cache
    with _lock:
        if _cache is not None:
            return dict(_cache)
    stored = {s.key: s.value for s in db.scalars(select(Setting))}
    out: Dict[str, Any] = {}
    for key, spec in SPECS.items():
        if key in stored:
            try:
                out[key] = _parse(key, stored[key])
                continue
            except SettingsError:
                pass                     # a hand-edited bad row falls back to the default
        out[key] = spec.default(cfg)
        if spec.kind == "float" and out[key] is not None:
            out[key] = float(out[key])
        if spec.kind == "int" and out[key] is not None:
            out[key] = int(out[key])
    with _lock:
        _cache = dict(out)
    return out


def get(db: Session, cfg, key: str) -> Any:
    return all_settings(db, cfg)[key]


def update(db: Session, cfg, changes: Dict[str, Any], actor_id: Optional[int]) -> Dict[str, Any]:
    """Validate every change first, then write them all. Returns {key: (old, new)}."""
    unknown = sorted(set(changes) - set(SPECS))
    if unknown:
        raise SettingsError(f"unknown setting(s): {', '.join(unknown)}")
    parsed = {k: _parse(k, v) for k, v in changes.items()}

    current = all_settings(db, cfg)
    merged = {**current, **parsed}
    if merged["late_window_min"] < merged["present_window_min"]:
        raise SettingsError("The late window must end at or after the present window.")
    if merged["face_review_threshold"] >= merged["face_match_threshold"]:
        raise SettingsError("The review threshold must be below the match threshold.")

    diff: Dict[str, Any] = {}
    rows = {s.key: s for s in db.scalars(select(Setting).where(Setting.key.in_(list(parsed))))}
    for key, val in parsed.items():
        if current.get(key) == val:
            continue
        text = "" if val is None else (str(val).lower() if isinstance(val, bool) else str(val))
        row = rows.get(key)
        if row is None:
            db.add(Setting(key=key, value=text, updated_by_id=actor_id, updated_at=utcnow()))
        else:
            row.value = text
            row.updated_by_id = actor_id
            row.updated_at = utcnow()
        diff[key] = (current.get(key), val)
    db.flush()
    invalidate()
    return diff


def describe() -> list[dict]:
    """Field metadata for the admin settings form."""
    return [
        {"key": k, "kind": s.kind, "label": s.label, "help": s.help, "min": s.min, "max": s.max,
         "group": s.group}
        for k, s in SPECS.items()
    ]
