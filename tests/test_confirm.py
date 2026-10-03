"""Confirmation state machine — no camera, no model, no clock.

These are the tests that justify trusting an attendance mark.
"""
from __future__ import annotations

import pytest

from app.confirm import (
    ConfirmationManager,
    EventKind,
    Observation,
    TrackConfirmer,
    TrackState,
)


def obs(ts: float, ident="alice", score=0.72, **kw) -> Observation:
    base = dict(quality=0.8, quality_passed=True, live=True, antispoof_evaluated=False)
    base.update(kw)
    return Observation(ts=ts, identity=ident, score=score, **base)


def feed(tc: TrackConfirmer, n: int, *, step=0.4, start=0.0, **kw):
    """Feed n observations and return every emitted decision."""
    out = []
    for i in range(n):
        d = tc.observe(obs(start + i * step, **kw))
        if d is not None:
            out.append(d)
    return out


# --------------------------------------------------------------- confirmation

def test_confirms_at_exactly_confirm_frames(cfg):
    tc = TrackConfirmer(1, cfg)
    n = cfg.attendance.confirm_frames
    decisions = feed(tc, n)
    kinds = [d.kind for d in decisions]
    assert EventKind.CHECKIN in kinds, kinds
    assert tc.state is TrackState.CONFIRMED
    ev = decisions[-1].evidence
    assert ev.identity == "alice"
    assert ev.frames_matched >= n
    assert ev.median_confidence >= cfg.gallery.match_threshold


def test_refuses_at_one_frame_short(cfg):
    tc = TrackConfirmer(1, cfg)
    decisions = feed(tc, cfg.attendance.confirm_frames - 1)
    assert EventKind.CHECKIN not in [d.kind for d in decisions]
    assert tc.state is TrackState.CANDIDATE


def test_never_confirms_on_a_single_frame(cfg):
    tc = TrackConfirmer(1, cfg)
    d = tc.observe(obs(0.0, score=0.99))
    assert d is None or d.kind is not EventKind.CHECKIN
    assert tc.state is TrackState.CANDIDATE


def test_refuses_when_quality_gate_never_passes(cfg):
    tc = TrackConfirmer(1, cfg)
    decisions = feed(tc, cfg.attendance.confirm_frames + 3, quality_passed=False, quality=0.05)
    assert EventKind.CHECKIN not in [d.kind for d in decisions]
    assert tc.state is TrackState.CANDIDATE


def test_refuses_when_median_score_below_match_threshold(cfg):
    """Scores in the review band accumulate as a CANDIDATE but must never confirm."""
    band = (cfg.gallery.review_threshold + cfg.gallery.match_threshold) / 2
    tc = TrackConfirmer(1, cfg)
    decisions = feed(tc, cfg.attendance.confirm_frames + 3, score=band)
    assert EventKind.CHECKIN not in [d.kind for d in decisions]
    assert EventKind.CANDIDATE in [d.kind for d in decisions]


def test_refuses_on_antispoof_fail_and_raises_review(cfg):
    tc = TrackConfirmer(1, cfg)
    decisions = feed(tc, cfg.attendance.confirm_frames + 2,
                     live=False, antispoof_evaluated=True)
    kinds = [d.kind for d in decisions]
    assert EventKind.CHECKIN not in kinds
    assert EventKind.SPOOF_SUSPECTED in kinds
    spoof = next(d for d in decisions if d.kind is EventKind.SPOOF_SUSPECTED)
    assert spoof.evidence.needs_review is True


def test_briefly_held_photo_cannot_confirm(cfg):
    """Enough frames, but crammed into a single instant: fails the span/window requirement."""
    tc = TrackConfirmer(1, cfg)
    decisions = feed(tc, cfg.attendance.confirm_frames + 4, step=0.01)
    assert EventKind.CHECKIN not in [d.kind for d in decisions]


# ------------------------------------------------------------------ ambiguity

def test_flip_flop_becomes_ambiguous_not_a_guess(cfg):
    tc = TrackConfirmer(1, cfg)
    tc.observe(obs(0.0, "alice"))
    tc.observe(obs(0.4, "bob"))
    d = tc.observe(obs(0.8, "alice"))
    assert d is not None and d.kind is EventKind.AMBIGUOUS
    assert tc.state is TrackState.AMBIGUOUS
    assert d.evidence.needs_review is True
    # An ambiguous track is closed: further frames change nothing.
    assert tc.observe(obs(1.2, "alice")) is None


# -------------------------------------------------------------------- unknown

def test_unknown_raised_after_timeout(cfg):
    tc = TrackConfirmer(1, cfg)
    low = cfg.gallery.review_threshold - 0.1
    assert tc.observe(obs(0.0, "alice", score=low)) is None
    d = tc.observe(obs(cfg.attendance.unknown_after_s + 0.1, "alice", score=low))
    assert d is not None and d.kind is EventKind.UNKNOWN_FACE
    assert d.evidence.identity is None


def test_unknown_not_raised_before_timeout(cfg):
    tc = TrackConfirmer(1, cfg)
    low = cfg.gallery.review_threshold - 0.1
    tc.observe(obs(0.0, "alice", score=low))
    d = tc.observe(obs(cfg.attendance.unknown_after_s - 0.5, "alice", score=low))
    assert d is None


# ------------------------------------------------------------------- lifecycle

def test_candidate_lost_before_confirmation_is_reviewed_never_marked(cfg):
    tc = TrackConfirmer(1, cfg)
    feed(tc, cfg.attendance.confirm_frames - 1)
    d = tc.tick(100.0)
    assert d is not None and d.kind is EventKind.DISCARDED
    assert tc.state is TrackState.DISCARDED
    assert d.evidence is not None and d.evidence.needs_review is True


def test_tick_does_not_close_a_live_track(cfg):
    tc = TrackConfirmer(1, cfg)
    feed(tc, 2)
    assert tc.tick(1.0) is None


# -------------------------------------------------------------------- cooldown

def test_cooldown_suppresses_duplicate_checkins(cfg):
    """Someone loitering in the doorway produces one check-in, not three hundred."""
    mgr = ConfirmationManager(cfg)
    n = cfg.attendance.confirm_frames

    first = [mgr.observe(1, obs(i * 0.4)) for i in range(n)]
    assert any(d and d.kind is EventKind.CHECKIN for d in first)

    # Same person, brand-new track id, still inside the cooldown window.
    second = [mgr.observe(2, obs(10.0 + i * 0.4)) for i in range(n)]
    assert not any(d and d.kind is EventKind.CHECKIN for d in second)


def test_checkin_allowed_again_after_cooldown_expires(cfg):
    mgr = ConfirmationManager(cfg)
    n = cfg.attendance.confirm_frames
    for i in range(n):
        mgr.observe(1, obs(i * 0.4))

    later = cfg.attendance.recheck_cooldown_s + 60.0
    out = [mgr.observe(2, obs(later + i * 0.4)) for i in range(n)]
    assert any(d and d.kind is EventKind.CHECKIN for d in out)


def test_confirmed_track_is_skipped_for_reembedding(cfg):
    """The largest CPU saving available: stop embedding a track once it is confirmed."""
    mgr = ConfirmationManager(cfg)
    for i in range(cfg.attendance.confirm_frames):
        mgr.observe(7, obs(i * 0.4))
    assert mgr.is_confirmed(7) is True
    assert mgr.is_confirmed(8) is False


def test_two_people_confirm_independently(cfg):
    mgr = ConfirmationManager(cfg)
    n = cfg.attendance.confirm_frames
    got = []
    for i in range(n):
        got.append(mgr.observe(1, obs(i * 0.4, "alice")))
        got.append(mgr.observe(2, obs(i * 0.4, "bob")))
    names = {d.evidence.identity for d in got if d and d.kind is EventKind.CHECKIN}
    assert names == {"alice", "bob"}


@pytest.mark.parametrize("field_name", ["confirm_frames", "confirm_window_s",
                                        "min_distinct_windows", "min_span_seconds",
                                        "recheck_cooldown_s", "unknown_after_s"])
def test_every_knob_comes_from_config_not_code(cfg, field_name):
    assert hasattr(cfg.attendance, field_name), f"{field_name} must live in configs/default.yaml"
