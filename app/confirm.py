"""Identity confirmation state machine.

This module is the entire basis on which anyone should trust an attendance mark. One frame is a
coin flip under occlusion, motion blur or bad light, so nobody is ever marked present on a single
frame: an identity must be agreed by `confirm_frames` separate observations, inside
`confirm_window_s`, with a median score at or above `match_threshold`, at least one frame through
the quality gate, anti-spoof clean, and the evidence spread over `min_distinct_windows` distinct
time buckets spanning `min_span_seconds` (so a briefly-held photo cannot confirm).

The module is deliberately **pure**: it performs no I/O, reads no clock and touches no database.
Every timestamp is supplied by the caller. That is what makes it testable without a camera or a
model, which is how `tests/test_confirm.py` exercises it.
"""
from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, List, Optional


class TrackState(str, Enum):
    """Lifecycle of a single tracked face."""

    UNSEEN = "unseen"
    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    AMBIGUOUS = "ambiguous"
    DISCARDED = "discarded"


class EventKind(str, Enum):
    """Outcomes a track can emit. These map 1:1 onto SSE event names."""

    CANDIDATE = "candidate"
    CHECKIN = "checkin"
    AMBIGUOUS = "ambiguous"
    UNKNOWN_FACE = "unknown_face"
    SPOOF_SUSPECTED = "spoof_suspected"
    DISCARDED = "discarded"


@dataclass(frozen=True)
class Observation:
    """One processed frame's verdict for one tracked face.

    Args:
        ts: seconds, caller-supplied and monotonic within a track.
        identity: top-1 gallery label, or None when the gallery is empty.
        score: cosine similarity of the top-1 hit (raw — NOT thresholded).
        quality: FIQA score from the quality gate.
        quality_passed: whether `quality` cleared `quality.min_score`.
        live: anti-spoof verdict. True when PAD is disabled — see `antispoof_evaluated`.
        antispoof_evaluated: False when no PAD weights are loaded, so `live` is meaningless.
        occluded_ratio: from the occlusion estimator; recorded, never used to reject.
    """

    ts: float
    identity: Optional[str]
    score: float
    quality: float = 1.0
    quality_passed: bool = True
    live: bool = True
    antispoof_evaluated: bool = False
    occluded_ratio: float = 0.0


@dataclass
class Evidence:
    """Why a decision was reached — persisted onto the sighting row, shown in the review queue."""

    identity: Optional[str]
    frames_matched: int
    median_confidence: float
    max_confidence: float
    best_quality: float
    first_ts: float
    last_ts: float
    distinct_windows: int
    span_seconds: float
    mean_occluded_ratio: float
    antispoof_evaluated: bool
    needs_review: bool = False
    review_reason: Optional[str] = None


@dataclass
class Decision:
    """An event emitted by a track. `evidence` is None only for pure lifecycle events."""

    kind: EventKind
    track_id: int
    state: TrackState
    evidence: Optional[Evidence] = None
    detail: str = ""


@dataclass
class _Window:
    """Rolling evidence for one track."""

    obs: Deque[Observation] = field(default_factory=lambda: deque(maxlen=256))


class TrackConfirmer:
    """Accumulates observations for one track and decides when it may be confirmed."""

    def __init__(self, track_id: int, cfg) -> None:
        self.track_id = track_id
        self.state = TrackState.UNSEEN
        self._w = _Window()
        self._first_ts: Optional[float] = None
        self._last_ts: Optional[float] = None
        self._unknown_since: Optional[float] = None
        self._emitted_unknown = False
        self._emitted_candidate = False
        self.confirmed_identity: Optional[str] = None

        a = cfg.attendance
        g = cfg.gallery
        self.match_threshold = float(g.match_threshold)
        self.review_threshold = float(g.review_threshold)
        self.confirm_frames = int(a.confirm_frames)
        self.confirm_window_s = float(a.confirm_window_s)
        self.min_distinct_windows = int(a.min_distinct_windows)
        self.min_span_seconds = float(a.min_span_seconds)
        self.ambiguous_flip_limit = int(a.ambiguous_flip_limit)
        self.unknown_after_s = float(a.unknown_after_s)
        self.track_idle_timeout_s = float(a.track_idle_timeout_s)

    # ------------------------------------------------------------------ api

    def observe(self, obs: Observation) -> Optional[Decision]:
        """Feed one processed frame. Returns a Decision when the track changes meaningfully."""
        if self.state in (TrackState.CONFIRMED, TrackState.DISCARDED, TrackState.AMBIGUOUS):
            return None

        self._first_ts = obs.ts if self._first_ts is None else self._first_ts
        self._last_ts = obs.ts
        self._w.obs.append(obs)

        # Below the review floor: this is an unknown face, not a weak match.
        if obs.identity is None or obs.score < self.review_threshold:
            self._unknown_since = self._unknown_since if self._unknown_since is not None else obs.ts
            if (not self._emitted_unknown
                    and obs.ts - self._unknown_since >= self.unknown_after_s
                    and self.state == TrackState.UNSEEN):
                self._emitted_unknown = True
                return Decision(
                    EventKind.UNKNOWN_FACE, self.track_id, self.state,
                    self._evidence_for(None, list(self._w.obs)),
                    "no gallery match above review_threshold",
                )
            return None

        self._unknown_since = None
        if self.state == TrackState.UNSEEN:
            self.state = TrackState.CANDIDATE

        recent = self._recent(obs.ts)
        agreeing_id = self._majority_identity(recent)
        if agreeing_id is None:
            return None
        agreeing = [o for o in recent if o.identity == agreeing_id]

        if self._flips(recent) >= self.ambiguous_flip_limit:
            self.state = TrackState.AMBIGUOUS
            ev = self._evidence_for(agreeing_id, agreeing)
            ev.needs_review = True
            ev.review_reason = "identity alternated between candidates within the track"
            return Decision(EventKind.AMBIGUOUS, self.track_id, self.state, ev,
                            "identity flip-flop")

        ok, reason = self._can_confirm(agreeing)
        if ok:
            self.state = TrackState.CONFIRMED
            self.confirmed_identity = agreeing_id
            return Decision(EventKind.CHECKIN, self.track_id, self.state,
                            self._evidence_for(agreeing_id, agreeing), "confirmed")

        # A spoof verdict is never silently dropped — it becomes a review item.
        if reason == "antispoof":
            self.state = TrackState.AMBIGUOUS
            ev = self._evidence_for(agreeing_id, agreeing)
            ev.needs_review = True
            ev.review_reason = "anti-spoof flagged a presentation attack"
            return Decision(EventKind.SPOOF_SUSPECTED, self.track_id, self.state, ev, reason)

        if not self._emitted_candidate:
            self._emitted_candidate = True
            return Decision(EventKind.CANDIDATE, self.track_id, self.state,
                            self._evidence_for(agreeing_id, agreeing), reason)
        return None

    def tick(self, now: float) -> Optional[Decision]:
        """Advance wall time with no observation — closes idle tracks."""
        if self.state in (TrackState.CONFIRMED, TrackState.DISCARDED, TrackState.AMBIGUOUS):
            return None
        if self._last_ts is None or now - self._last_ts < self.track_idle_timeout_s:
            return None

        was = self.state
        self.state = TrackState.DISCARDED
        if was != TrackState.CANDIDATE:
            return Decision(EventKind.DISCARDED, self.track_id, self.state, None, "idle")

        # A candidate that vanished before confirming is weak evidence. It is surfaced for review,
        # never converted into a mark and never used to imply absence.
        recent = list(self._w.obs)
        ident = self._majority_identity(recent)
        ev = self._evidence_for(ident, [o for o in recent if o.identity == ident])
        ev.needs_review = True
        ev.review_reason = "track lost before confirmation"
        return Decision(EventKind.DISCARDED, self.track_id, self.state, ev,
                        "candidate lost before confirmation")

    # -------------------------------------------------------------- internal

    def _recent(self, now: float) -> List[Observation]:
        return [o for o in self._w.obs if now - o.ts <= self.confirm_window_s]

    @staticmethod
    def _majority_identity(obs: List[Observation]) -> Optional[str]:
        counts: Dict[str, int] = {}
        for o in obs:
            if o.identity:
                counts[o.identity] = counts.get(o.identity, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _flips(obs: List[Observation]) -> int:
        idents = [o.identity for o in obs if o.identity]
        return sum(1 for a, b in zip(idents, idents[1:]) if a != b)

    def _windows_and_span(self, obs: List[Observation]) -> tuple[int, float]:
        """Bucket observations into time slices to prove the face persisted, not flashed."""
        if not obs:
            return 0, 0.0
        ts = sorted(o.ts for o in obs)
        span = ts[-1] - ts[0]
        bucket = max(self.min_span_seconds / max(self.min_distinct_windows, 1), 1e-6)
        return len({int(t // bucket) for t in ts}), span

    def _can_confirm(self, agreeing: List[Observation]) -> tuple[bool, str]:
        if len(agreeing) < self.confirm_frames:
            return False, f"{len(agreeing)}/{self.confirm_frames} agreeing frames"
        if any(o.antispoof_evaluated and not o.live for o in agreeing):
            return False, "antispoof"
        if not any(o.quality_passed for o in agreeing):
            return False, "no frame cleared the quality gate"
        med = statistics.median(o.score for o in agreeing)
        if med < self.match_threshold:
            return False, f"median score {med:.3f} < match_threshold {self.match_threshold:.3f}"
        n_win, span = self._windows_and_span(agreeing)
        if n_win < self.min_distinct_windows or span < self.min_span_seconds:
            return False, (f"evidence spans {span:.1f}s over {n_win} window(s); "
                           f"need {self.min_span_seconds:.1f}s over {self.min_distinct_windows}")
        return True, "ok"

    def _evidence_for(self, identity: Optional[str], obs: List[Observation]) -> Evidence:
        if not obs:
            return Evidence(identity, 0, 0.0, 0.0, 0.0, self._first_ts or 0.0,
                            self._last_ts or 0.0, 0, 0.0, 0.0, False)
        scores = [o.score for o in obs]
        n_win, span = self._windows_and_span(obs)
        return Evidence(
            identity=identity,
            frames_matched=len(obs),
            median_confidence=float(statistics.median(scores)),
            max_confidence=float(max(scores)),
            best_quality=float(max(o.quality for o in obs)),
            first_ts=float(min(o.ts for o in obs)),
            last_ts=float(max(o.ts for o in obs)),
            distinct_windows=n_win,
            span_seconds=float(span),
            mean_occluded_ratio=float(sum(o.occluded_ratio for o in obs) / len(obs)),
            antispoof_evaluated=all(o.antispoof_evaluated for o in obs),
        )


class ConfirmationManager:
    """Owns every live track for one camera, plus the per-user re-check cooldown.

    Cooldown is keyed on the *user*, not the track: someone who steps out of frame and returns
    gets a fresh track id, and must not produce a second check-in.
    """

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.recheck_cooldown_s = float(cfg.attendance.recheck_cooldown_s)
        self._tracks: Dict[int, TrackConfirmer] = {}
        self._cooldown_until: Dict[str, float] = {}

    def observe(self, track_id: int, obs: Observation) -> Optional[Decision]:
        """Route one observation to its track, applying the cooldown suppression."""
        t = self._tracks.get(track_id)
        if t is None:
            t = self._tracks[track_id] = TrackConfirmer(track_id, self.cfg)
        d = t.observe(obs)
        if d is None or d.kind is not EventKind.CHECKIN:
            return d
        ident = d.evidence.identity if d.evidence else None
        if ident and obs.ts < self._cooldown_until.get(ident, float("-inf")):
            return None                                   # loitering: already counted
        if ident:
            self._cooldown_until[ident] = obs.ts + self.recheck_cooldown_s
        return d

    def tick(self, now: float) -> List[Decision]:
        """Advance all tracks and reap finished ones."""
        out: List[Decision] = []
        for t in list(self._tracks.values()):
            d = t.tick(now)
            if d is not None:
                out.append(d)
        for tid, t in list(self._tracks.items()):
            if t.state in (TrackState.DISCARDED, TrackState.AMBIGUOUS):
                del self._tracks[tid]
        return out

    def is_confirmed(self, track_id: int) -> bool:
        """True when this track needs no further detect->embed work (the big CPU saving)."""
        t = self._tracks.get(track_id)
        return t is not None and t.state is TrackState.CONFIRMED

    def active_tracks(self) -> Dict[int, TrackConfirmer]:
        return dict(self._tracks)
