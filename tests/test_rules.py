"""compute_attendance — pure, fixture-driven, no model download and no database."""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.rules import (
    AttendanceRecord,
    CameraMode,
    SessionSpec,
    SightingSpec,
    Status,
    attendance_percentage,
    compute_attendance,
)

ALICE, BOB, CARA = 1, 2, 3


def session(t0, mode=CameraMode.KIOSK, grace=10, min_presence=1500) -> SessionSpec:
    return SessionSpec(
        id=1,
        scheduled_start=t0,
        scheduled_end=t0 + timedelta(minutes=50),
        mode=mode,
        grace_minutes=grace,
        min_presence_seconds=min_presence,
    )


def sight(t0, user, start_min, end_min, **kw) -> SightingSpec:
    base = dict(frames_matched=8, median_confidence=0.62, best_quality=0.7,
                mean_occluded_ratio=0.1, confirmed=True)
    base.update(kw)
    return SightingSpec(
        user_id=user,
        first_seen=t0 + timedelta(minutes=start_min),
        last_seen=t0 + timedelta(minutes=end_min),
        **base,
    )


def only(records, user) -> AttendanceRecord:
    return next(r for r in records if r.user_id == user)


# ------------------------------------------------------------------ kiosk mode

def test_kiosk_on_time_is_present(cfg, t0):
    recs = compute_attendance(session(t0), [ALICE], [sight(t0, ALICE, 2, 2)], cfg)
    assert only(recs, ALICE).status is Status.PRESENT


def test_kiosk_after_grace_is_late(cfg, t0):
    recs = compute_attendance(session(t0), [ALICE], [sight(t0, ALICE, 15, 15)], cfg)
    assert only(recs, ALICE).status is Status.LATE


def test_kiosk_exactly_at_grace_boundary_is_still_present(cfg, t0):
    recs = compute_attendance(session(t0), [ALICE], [sight(t0, ALICE, 10, 10)], cfg)
    assert only(recs, ALICE).status is Status.PRESENT


# ------------------------------------------------------------------- room mode

def test_room_full_attendance_is_present(cfg, t0):
    s = session(t0, CameraMode.ROOM)
    recs = compute_attendance(s, [ALICE], [sight(t0, ALICE, 0, 45)], cfg)
    r = only(recs, ALICE)
    assert r.status is Status.PRESENT
    assert r.total_visible_s == pytest.approx(45 * 60)


def test_room_insufficient_presence_is_partial(cfg, t0):
    s = session(t0, CameraMode.ROOM)
    recs = compute_attendance(s, [ALICE], [sight(t0, ALICE, 0, 10)], cfg)
    assert only(recs, ALICE).status is Status.PARTIAL


def test_room_leaving_before_end_grace_is_left_early(cfg, t0):
    s = session(t0, CameraMode.ROOM)
    recs = compute_attendance(s, [ALICE], [sight(t0, ALICE, 0, 30)], cfg)
    assert only(recs, ALICE).status is Status.LEFT_EARLY


def test_room_overlapping_sightings_are_not_double_counted(cfg, t0):
    """Two concurrent tracks of the same person must not inflate visible time."""
    s = session(t0, CameraMode.ROOM)
    sightings = [sight(t0, ALICE, 0, 30), sight(t0, ALICE, 10, 40)]
    r = only(compute_attendance(s, [ALICE], sightings, cfg), ALICE)
    assert r.total_visible_s == pytest.approx(40 * 60)   # union, not 30+30 minutes


def test_room_disjoint_sightings_sum(cfg, t0):
    s = session(t0, CameraMode.ROOM)
    sightings = [sight(t0, ALICE, 0, 10), sight(t0, ALICE, 30, 45)]
    r = only(compute_attendance(s, [ALICE], sightings, cfg), ALICE)
    assert r.total_visible_s == pytest.approx((10 + 15) * 60)


# --------------------------------------------------------------------- absence

def test_rostered_and_never_seen_is_absent(cfg, t0):
    recs = compute_attendance(session(t0), [ALICE, BOB], [sight(t0, ALICE, 1, 1)], cfg)
    assert only(recs, BOB).status is Status.ABSENT
    assert only(recs, BOB).needs_review is False


def test_weak_evidence_is_reviewed_never_marked_absent(cfg, t0):
    """The single most important rule in the file."""
    weak = sight(t0, BOB, 5, 5, confirmed=False, needs_review=True,
                 review_reason="track lost before confirmation")
    recs = compute_attendance(session(t0), [ALICE, BOB], [sight(t0, ALICE, 1, 1), weak], cfg)
    r = only(recs, BOB)
    assert r.status is Status.NEEDS_REVIEW
    assert r.status is not Status.ABSENT
    assert "track lost" in (r.review_reason or "")


def test_ambiguous_sighting_does_not_mark_present(cfg, t0):
    amb = sight(t0, ALICE, 2, 2, confirmed=False, needs_review=True,
                review_reason="identity alternated between candidates")
    r = only(compute_attendance(session(t0), [ALICE], [amb], cfg), ALICE)
    assert r.status is Status.NEEDS_REVIEW


def test_unrostered_sighting_is_ignored_by_the_rules(cfg, t0):
    recs = compute_attendance(session(t0), [ALICE], [sight(t0, CARA, 1, 1)], cfg)
    assert [r.user_id for r in recs] == [ALICE]
    assert only(recs, ALICE).status is Status.ABSENT


# ----------------------------------------------------------------- review flags

def test_fully_occluded_evidence_flags_review_but_keeps_status(cfg, t0):
    heavy = cfg.attendance.heavy_occlusion_ratio + 0.2
    recs = compute_attendance(session(t0), [ALICE],
                              [sight(t0, ALICE, 1, 1, mean_occluded_ratio=heavy)], cfg)
    r = only(recs, ALICE)
    assert r.status is Status.PRESENT
    assert r.needs_review is True
    assert "occluded" in (r.review_reason or "")


def test_missing_pad_alone_does_not_flag_every_record(cfg, t0):
    """With no PAD weights every sighting has antispoof_evaluated=False. That is a system
    banner, not a per-record review item — otherwise the queue is 100% noise."""
    recs = compute_attendance(session(t0), [ALICE],
                              [sight(t0, ALICE, 1, 1, antispoof_evaluated=False)], cfg)
    assert only(recs, ALICE).needs_review is False


# ------------------------------------------------------------------ determinism

def test_recompute_is_deterministic(cfg, t0):
    s = session(t0, CameraMode.ROOM)
    sightings = [sight(t0, ALICE, 0, 45), sight(t0, BOB, 0, 5)]
    a = compute_attendance(s, [ALICE, BOB, CARA], sightings, cfg)
    b = compute_attendance(s, [ALICE, BOB, CARA], sightings, cfg)
    assert [(r.user_id, r.status, r.total_visible_s) for r in a] == \
           [(r.user_id, r.status, r.total_visible_s) for r in b]


def test_attendance_percentage_counts_present_and_late_only(cfg, t0):
    s = session(t0)
    sightings = [sight(t0, ALICE, 1, 1), sight(t0, BOB, 20, 20)]   # present + late
    recs = compute_attendance(s, [ALICE, BOB, CARA], sightings, cfg)   # CARA absent
    assert attendance_percentage(recs) == pytest.approx(200.0 / 3)


def test_compute_attendance_reads_no_clock(cfg, t0):
    """A session entirely in the future must still compute, proving no now() is consulted."""
    future = SessionSpec(
        id=9,
        scheduled_start=t0.replace(year=2099),
        scheduled_end=t0.replace(year=2099) + timedelta(minutes=50),
    )
    recs = compute_attendance(future, [ALICE], [], cfg)
    assert only(recs, ALICE).status is Status.ABSENT
