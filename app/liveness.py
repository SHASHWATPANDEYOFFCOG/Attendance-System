"""Server-side liveness: a random head-movement challenge verified from facial landmarks.

How it works: the server issues a short, random, single-use sequence of poses ("front", then
e.g. "right", "left"). The browser shows the instructions and captures one frame per step. The
server — never the browser — measures each frame's head pose from the five landmarks the detector
already produces and checks that the head really moved as instructed, in that order.

What it stops: a printed photo, or a photo shown on another phone. A flat image keeps the same
nose-to-eyes geometry however it is tilted, so it cannot produce a convincing left turn followed by
a right turn; and because the order is random and the challenge expires in 90 seconds, a
pre-recorded clip of the student turning one way does not answer it.

What it does NOT stop on its own: a live video call or a deepfake following the instructions in
real time. That needs a presentation-attack-detection model (antispoof.onnx_path); when one is
configured, every frame is also checked by it.

Pose measures (in image coordinates, frames are NOT mirrored — the browser draws the raw camera
frame, only the on-screen preview is mirrored):
    yaw   = (nose.x - eyes_mid.x) / eye_distance      > 0 when the student turns to THEIR left
    pitch = (nose.y - eyes_mid.y) / (mouth_mid.y - eyes_mid.y), compared with their own front
            frame: smaller when looking up, larger when looking down.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import timedelta
from typing import List, Optional, Sequence

import cv2
import numpy as np
from sqlalchemy.orm import Session

from app.models import LivenessChallenge, utcnow

CHALLENGE_TTL = timedelta(seconds=90)

FRONT_MAX_YAW = 0.12        # |yaw| below this counts as facing the camera
TURN_MIN_YAW = 0.15         # a deliberate "slight" turn
TURN_MAX_YAW = 0.38         # beyond this the quality gate and alignment degrade (matches enroll.py)
PITCH_DELTA = 0.07          # change in the pitch ratio relative to the student's own front frame

POSE_TEXT = {
    "front": "Look straight at the camera",
    "left": "Turn your head slightly to your LEFT",
    "right": "Turn your head slightly to your RIGHT",
    "up": "Tilt your head slightly UP",
    "down": "Tilt your head slightly DOWN",
}


@dataclass
class Pose:
    yaw: float
    pitch: float


def pose_of(kps: np.ndarray) -> Pose:
    k = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
    left_eye, right_eye, nose = k[0], k[1], k[2]
    eye_mid = (left_eye + right_eye) / 2.0
    eye_dist = float(np.linalg.norm(right_eye - left_eye)) or 1e-6
    yaw = float((nose[0] - eye_mid[0]) / eye_dist)
    if len(k) >= 5:
        mouth_mid = (k[3] + k[4]) / 2.0
        span = float(mouth_mid[1] - eye_mid[1]) or 1e-6
        pitch = float((nose[1] - eye_mid[1]) / span)
    else:
        pitch = 0.5
    return Pose(yaw=yaw, pitch=pitch)


def pose_matches(label: str, p: Pose, front: Optional[Pose]) -> Optional[str]:
    """None when the frame shows the requested pose, else a message the student can act on."""
    if label == "front":
        return None if abs(p.yaw) < FRONT_MAX_YAW else "Face the camera straight on."
    if label in ("left", "right"):
        want = 1.0 if label == "left" else -1.0
        if p.yaw * want < TURN_MIN_YAW:
            return f"Turn your head a little to your {label.upper()}."
        if abs(p.yaw) > TURN_MAX_YAW:
            return "That turn is too far — keep both eyes visible."
        return None
    if label in ("up", "down"):
        base = front.pitch if front else 0.5
        delta = p.pitch - base
        if label == "up" and delta > -PITCH_DELTA:
            return "Tilt your chin up a little."
        if label == "down" and delta < PITCH_DELTA:
            return "Tilt your chin down a little."
        return None
    return "Unknown pose."


def decode(data: bytes) -> Optional[np.ndarray]:
    if not data:
        return None
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def issue(db: Session, user_id: int, purpose: str, session_id: Optional[int] = None) -> LivenessChallenge:
    if purpose == "enroll":
        turns = ["left", "right", "up", "down"]
        random.SystemRandom().shuffle(turns)
        steps = ["front", *turns]
    else:
        pair = ["left", "right"]
        random.SystemRandom().shuffle(pair)
        steps = ["front", *pair]
    ch = LivenessChallenge(user_id=user_id, purpose=purpose, steps=json.dumps(steps),
                           session_id=session_id, expires_at=utcnow() + CHALLENGE_TTL)
    db.add(ch)
    db.commit()
    return ch


class LivenessError(Exception):
    def __init__(self, message: str, *, step: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.step = step


def consume(db: Session, challenge_id: int, user_id: int, purpose: str,
            session_id: Optional[int] = None) -> List[str]:
    """Validate and burn a challenge. Returns its steps. Single use, short-lived, user-bound."""
    ch = db.get(LivenessChallenge, challenge_id)
    if ch is None or ch.user_id != user_id or ch.purpose != purpose:
        raise LivenessError("This face check is not valid. Start again.")
    if session_id is not None and ch.session_id != session_id:
        raise LivenessError("This face check was issued for a different lecture.")
    if ch.used_at is not None:
        raise LivenessError("This face check was already used. Start again.")
    if ch.expires_at < utcnow():
        raise LivenessError("The face check timed out. Start again and follow the prompts.")
    ch.used_at = utcnow()
    db.commit()
    return json.loads(ch.steps)


def verify_sequence(steps: Sequence[str], poses: Sequence[Pose]) -> None:
    """Raise LivenessError unless each frame shows its step's pose, in order."""
    if len(poses) != len(steps):
        raise LivenessError(f"Expected {len(steps)} photos for this check, got {len(poses)}.")
    front = poses[0] if steps and steps[0] == "front" else None
    for i, (label, pose) in enumerate(zip(steps, poses)):
        problem = pose_matches(label, pose, front)
        if problem:
            raise LivenessError(f"Step {i + 1} ({POSE_TEXT[label].lower()}): {problem}", step=i)
    # A flat photo can be rotated to fake one direction, but its yaw cannot swing both ways.
    yaws = [p.yaw for p in poses]
    if "left" in steps and "right" in steps and (max(yaws) - min(yaws)) < 2 * TURN_MIN_YAW:
        raise LivenessError("The head movement was too small to confirm a live person.")
