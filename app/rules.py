"""Attendance derivation — one pure function.

`compute_attendance` performs no I/O, touches no database, reads no clock and holds no global
state. Everything it needs arrives as arguments, and the same inputs always produce the same
records. That is what makes `POST /api/sessions/{id}/recompute` meaningful: attendance rows are
derived data that can be thrown away and rebuilt from the immutable sighting log at any time.

The governing bias: **weak evidence never auto-marks someone absent.** A wrong `absent` costs a
student a grade or a worker a day's pay; a `needs_review` row costs faculty thirty seconds. Only
a complete absence of any sighting produces `absent`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple


class CameraMode(str, Enum):
    KIOSK = "kiosk"
    ROOM = "room"


class Status(str, Enum):
    PRESENT = "present"
    LATE = "late"
    PARTIAL = "partial"
    LEFT_EARLY = "left_early"
    ABSENT = "absent"
    NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class SessionSpec:
    """Everything the rules need to know about a session. All datetimes are UTC."""

    id: int
    scheduled_start: datetime
    scheduled_end: datetime
    mode: CameraMode = CameraMode.KIOSK
    grace_minutes: int = 10
    min_presence_seconds: int = 1500


@dataclass(frozen=True)
class SightingSpec:
    """One immutable observation window for one user, as written by the worker."""

    user_id: int
    first_seen: datetime
    last_seen: datetime
    frames_matched: int = 0
    median_confidence: float = 0.0
    best_quality: float = 0.0
    mean_occluded_ratio: float = 0.0
    confirmed: bool = True
    antispoof_evaluated: bool = False
    needs_review: bool = False
    review_reason: Optional[str] = None


@dataclass
class AttendanceRecord:
    """Derived attendance for one rostered user. Never the only copy of a fact."""

    user_id: int
    session_id: int
    status: Status
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    total_visible_s: float = 0.0
    avg_confidence: float = 0.0
    frames_matched: int = 0
    needs_review: bool = False
    review_reason: Optional[str] = None
    evidence: List[str] = field(default_factory=list)


def _merge_intervals(spans: Sequence[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    """Union overlapping windows so concurrent tracks cannot double-count visible time."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: s[0])
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def compute_attendance(
    session: SessionSpec,
    roster: Iterable[int],
    sightings: Iterable[SightingSpec],
    cfg,
) -> List[AttendanceRecord]:
    """Derive one AttendanceRecord per rostered user.

    Args:
        session: the session being computed, with UTC scheduled bounds.
        roster: user ids expected in this session.
        sightings: immutable sightings; may include users not on the roster (ignored here and
            surfaced separately as unscheduled sightings).
        cfg: loaded config namespace; `cfg.attendance` and `cfg.gallery` are read.

    Returns:
        One record per rostered user, ordered by user id.

    Note on anti-spoof: when no PAD weights are loaded, `antispoof_evaluated` is False on every
    sighting. Flagging every record `needs_review` in that case would drown the queue and tell
    faculty nothing, so the missing-PAD condition is reported once as a system-level banner
    (see B9 / `app/api.py::system_status`) rather than per record. A sighting is only flagged
    here when PAD actually ran and was not satisfied.
    """
    a = cfg.attendance
    heavy = float(getattr(a, "heavy_occlusion_ratio", 0.6))
    grace = timedelta(minutes=int(session.grace_minutes))
    late_after = session.scheduled_start + grace
    early_before = session.scheduled_end - grace

    by_user: dict[int, List[SightingSpec]] = {}
    for s in sightings:
        by_user.setdefault(s.user_id, []).append(s)

    records: List[AttendanceRecord] = []
    for user_id in sorted(set(roster)):
        mine = sorted(by_user.get(user_id, []), key=lambda s: s.first_seen)
        rec = AttendanceRecord(user_id=user_id, session_id=session.id, status=Status.ABSENT)

        if not mine:
            rec.evidence.append("no sighting recorded for this session")
            records.append(rec)
            continue

        confirmed = [s for s in mine if s.confirmed and not s.needs_review]
        rec.first_seen = min(s.first_seen for s in mine)
        rec.last_seen = max(s.last_seen for s in mine)
        rec.frames_matched = sum(s.frames_matched for s in mine)

        # Sightings exist but none of them survived confirmation. That is not evidence of
        # absence — it is an unresolved question, and a human answers it.
        if not confirmed:
            reasons = sorted({s.review_reason for s in mine if s.review_reason})
            rec.status = Status.NEEDS_REVIEW
            rec.needs_review = True
            rec.review_reason = "; ".join(reasons) or "seen, but never confirmed"
            rec.avg_confidence = _weighted_conf(mine)
            rec.total_visible_s = _visible_seconds(mine)
            rec.evidence.append(f"{len(mine)} unconfirmed sighting(s)")
            records.append(rec)
            continue

        rec.avg_confidence = _weighted_conf(confirmed)
        rec.total_visible_s = _visible_seconds(confirmed)
        first_confirmed = min(s.first_seen for s in confirmed)
        last_confirmed = max(s.last_seen for s in confirmed)

        if session.mode is CameraMode.KIOSK:
            rec.status = Status.LATE if first_confirmed > late_after else Status.PRESENT
            rec.evidence.append(
                f"first confirmed check-in {first_confirmed.isoformat()} "
                f"({'after' if first_confirmed > late_after else 'within'} grace)"
            )
        else:
            if rec.total_visible_s < float(session.min_presence_seconds):
                rec.status = Status.PARTIAL
                rec.evidence.append(
                    f"visible {rec.total_visible_s:.0f}s < required {session.min_presence_seconds}s"
                )
            elif last_confirmed < early_before:
                rec.status = Status.LEFT_EARLY
                rec.evidence.append(f"last seen {last_confirmed.isoformat()}, before {early_before.isoformat()}")
            else:
                rec.status = Status.PRESENT
                rec.evidence.append(f"visible {rec.total_visible_s:.0f}s")

        # Flags that do not change the status but do earn a second look.
        if all(s.mean_occluded_ratio >= heavy for s in confirmed):
            rec.needs_review = True
            rec.review_reason = "every matched frame was heavily occluded"
        elif rec.avg_confidence < float(cfg.gallery.match_threshold):
            rec.needs_review = True
            rec.review_reason = "confidence fell below match_threshold after aggregation"
        elif any(s.antispoof_evaluated and s.needs_review for s in mine):
            rec.needs_review = True
            rec.review_reason = "anti-spoof was inconclusive on at least one sighting"

        records.append(rec)

    return records


def _visible_seconds(sightings: Sequence[SightingSpec]) -> float:
    spans = _merge_intervals([(s.first_seen, s.last_seen) for s in sightings])
    return float(sum((e - s).total_seconds() for s, e in spans))


def _weighted_conf(sightings: Sequence[SightingSpec]) -> float:
    """Frame-count-weighted mean confidence: a 40-frame sighting outweighs a 3-frame one."""
    total = sum(max(s.frames_matched, 1) for s in sightings)
    if not total:
        return 0.0
    return float(sum(s.median_confidence * max(s.frames_matched, 1) for s in sightings) / total)


def attendance_percentage(records: Sequence[AttendanceRecord]) -> float:
    """Share of records counting toward the minimum-attendance rule.

    `present` and `late` count; `partial`, `left_early`, `absent` and `needs_review` do not.
    """
    if not records:
        return 0.0
    counted = sum(1 for r in records if r.status in (Status.PRESENT, Status.LATE))
    return 100.0 * counted / len(records)
