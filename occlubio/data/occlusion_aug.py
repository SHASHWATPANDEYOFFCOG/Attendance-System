"""Synthetic occlusion + photometric augmentation for aligned face crops.

RESTORED MODULE — READ THIS BEFORE ASSUMING IT IS UPSTREAM CODE
--------------------------------------------------------------
`occlubio/data/` is referenced by the upstream README (roadmap phase P3) and imported by
`scripts/make_occluded_dataset.py`, but it is **absent from the published repository**: the
upstream `.gitignore` contains a bare `data/` pattern, which git applies at *every* directory
level, so the package was silently never committed. Cloning the repo and running
`make_occluded_dataset.py` therefore fails with `ModuleNotFoundError: No module named
'occlubio.data'`.

This file is a reconstruction written for this project, not upstream code. It restores the
documented interface (`OcclusionAugmentor(occlude_prob, photometric_prob)`, callable on a crop)
so the upstream script runs unmodified, and adds a labelled `apply()` path so an evaluation set
can be sliced by occlusion type — required to report TAR separately for clean / masked /
sunglasses subsets.

The occluder geometry is deliberately aligned with the detection bands hard-coded in
`occlubio/pipeline/occlusion.py` (eye band rows 40:64, lower band rows 70:112, forehead band
rows 0:38 on a 112x112 crop), so the heuristic occlusion estimator can be validated against
known ground truth.

Augmentations follow OCCLUSION_ROBUST_FR_ARCHITECTURE.md §1.8 "Step 2 — Occlusion-aware
student": masks, synthetic sunglasses/cap/scarf overlays, random erasing, motion blur, low-light
gamma/noise, JPEG, downscale-to-surveillance-resolution.
"""
from __future__ import annotations

from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

__all__ = ["OcclusionAugmentor", "OCCLUSION_KINDS"]

#: Occlusion types this augmentor can synthesise. "clear" is a no-op passthrough.
OCCLUSION_KINDS: Tuple[str, ...] = (
    "clear",
    "mask",
    "sunglasses",
    "cap",
    "scarf",
    "random_erase",
)

# Reference crop geometry. Coordinates below are expressed against this and scaled to the
# actual crop size, so the augmentor works on any square-ish aligned chip.
_REF = 112.0

# Plausible colours (BGR) for each occluder, sampled uniformly.
_MASK_COLORS = ((228, 224, 216), (176, 148, 108), (60, 60, 62), (196, 208, 210))
_GLASS_COLORS = ((28, 26, 24), (44, 38, 36), (18, 18, 20))
_CAP_COLORS = ((40, 42, 48), (120, 70, 46), (32, 60, 96), (150, 150, 150))
_SCARF_COLORS = ((70, 60, 130), (48, 72, 56), (30, 30, 34), (140, 120, 90))


def _s(v: float, size: int) -> int:
    """Scale a reference-space coordinate to the actual crop size."""
    return int(round(v / _REF * size))


class OcclusionAugmentor:
    """Applies synthetic occluders and photometric degradation to aligned face crops.

    Args:
        occlude_prob: probability that an occluder is drawn on a given call.
        photometric_prob: probability that photometric degradation is applied.
        kinds: occlusion types to sample from; defaults to everything except ``"clear"``.
        seed: optional RNG seed for reproducible evaluation sets.
    """

    def __init__(
        self,
        occlude_prob: float = 1.0,
        photometric_prob: float = 0.5,
        kinds: Optional[Sequence[str]] = None,
        seed: Optional[int] = None,
    ) -> None:
        self.occlude_prob = float(occlude_prob)
        self.photometric_prob = float(photometric_prob)
        bad = set(kinds or ()) - set(OCCLUSION_KINDS)
        if bad:
            raise ValueError(f"unknown occlusion kinds: {sorted(bad)}")
        self.kinds: Tuple[str, ...] = tuple(kinds) if kinds else tuple(
            k for k in OCCLUSION_KINDS if k != "clear"
        )
        self.rng = np.random.default_rng(seed)

    # ---------------------------------------------------------------- public

    def __call__(self, crop: np.ndarray) -> np.ndarray:
        """Randomly occlude and degrade a crop (the interface upstream scripts expect)."""
        out = crop
        if self.rng.random() < self.occlude_prob:
            kind = str(self.rng.choice(self.kinds))
            out = self.apply(out, kind)
        if self.rng.random() < self.photometric_prob:
            out = self.photometric(out)
        return out

    def apply(self, crop: np.ndarray, kind: str) -> np.ndarray:
        """Apply one named occluder. Deterministic in type, randomised in appearance."""
        if kind not in OCCLUSION_KINDS:
            raise ValueError(f"unknown occlusion kind: {kind!r}")
        if kind == "clear":
            return crop.copy()
        return getattr(self, f"_draw_{kind}")(crop.copy())

    def photometric(self, crop: np.ndarray) -> np.ndarray:
        """Low-light gamma, sensor noise, motion blur, JPEG and downscale artefacts."""
        out = crop.astype(np.float32)

        # Low-light / over-exposure gamma shift.
        gamma = float(self.rng.uniform(0.55, 1.7))
        out = 255.0 * np.power(np.clip(out / 255.0, 0, 1), gamma)

        # Sensor noise.
        if self.rng.random() < 0.6:
            out += self.rng.normal(0.0, float(self.rng.uniform(2.0, 10.0)), out.shape)

        out = np.clip(out, 0, 255).astype(np.uint8)

        # Directional motion blur.
        if self.rng.random() < 0.4:
            k = int(self.rng.integers(3, 8))
            kern = np.zeros((k, k), np.float32)
            if self.rng.random() < 0.5:
                kern[k // 2, :] = 1.0 / k
            else:
                kern[:, k // 2] = 1.0 / k
            out = cv2.filter2D(out, -1, kern)

        # Downscale to surveillance resolution and back.
        if self.rng.random() < 0.5:
            h, w = out.shape[:2]
            f = float(self.rng.uniform(0.35, 0.75))
            small = cv2.resize(out, (max(8, int(w * f)), max(8, int(h * f))), interpolation=cv2.INTER_AREA)
            out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

        # JPEG recompression.
        if self.rng.random() < 0.5:
            q = int(self.rng.integers(25, 75))
            ok, enc = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), q])
            if ok:
                out = cv2.imdecode(enc, cv2.IMREAD_COLOR)

        return out

    # ------------------------------------------------------------- occluders

    def _draw_mask(self, img: np.ndarray) -> np.ndarray:
        """Surgical/cloth mask over the lower face (nose bridge down past the chin)."""
        h, w = img.shape[:2]
        color = tuple(int(c) for c in _MASK_COLORS[self.rng.integers(len(_MASK_COLORS))])
        top = _s(self.rng.uniform(58, 68), h)          # just below the eyes
        poly = np.array([
            [_s(10, w), top + _s(8, h)],
            [_s(38, w), top - _s(6, h)],               # nose-bridge peak
            [_s(56, w), top - _s(9, h)],
            [_s(74, w), top - _s(6, h)],
            [_s(102, w), top + _s(8, h)],
            [_s(102, w), h],
            [_s(10, w), h],
        ], np.int32)
        cv2.fillPoly(img, [poly], color, lineType=cv2.LINE_AA)
        # Ear loops + a pleat line so the texture is not perfectly flat.
        cv2.line(img, (_s(10, w), top + _s(10, h)), (0, top + _s(2, h)), color, max(1, _s(3, w)), cv2.LINE_AA)
        cv2.line(img, (_s(102, w), top + _s(10, h)), (w, top + _s(2, h)), color, max(1, _s(3, w)), cv2.LINE_AA)
        shade = tuple(max(0, c - 22) for c in color)
        cv2.line(img, (_s(14, w), top + _s(26, h)), (_s(98, w), top + _s(26, h)), shade, max(1, _s(2, w)), cv2.LINE_AA)
        return img

    def _draw_sunglasses(self, img: np.ndarray) -> np.ndarray:
        """Dark glasses across the eye band (rows ~40:64 in reference space)."""
        h, w = img.shape[:2]
        color = tuple(int(c) for c in _GLASS_COLORS[self.rng.integers(len(_GLASS_COLORS))])
        cy = _s(self.rng.uniform(48, 54), h)
        lens_w, lens_h = _s(30, w), _s(15, h)
        for cx in (_s(34, w), _s(78, w)):
            cv2.ellipse(img, (cx, cy), (lens_w // 2, lens_h), 0, 0, 360, color, -1, cv2.LINE_AA)
        cv2.line(img, (_s(34, w), cy), (_s(78, w), cy), color, max(2, _s(4, h)), cv2.LINE_AA)   # bridge
        cv2.line(img, (_s(19, w), cy), (0, cy - _s(4, h)), color, max(1, _s(3, h)), cv2.LINE_AA)  # temples
        cv2.line(img, (_s(93, w), cy), (w, cy - _s(4, h)), color, max(1, _s(3, h)), cv2.LINE_AA)
        return img

    def _draw_cap(self, img: np.ndarray) -> np.ndarray:
        """Cap/hood covering the forehead band, with a shadow cast below the brim."""
        h, w = img.shape[:2]
        color = tuple(int(c) for c in _CAP_COLORS[self.rng.integers(len(_CAP_COLORS))])
        brim = _s(self.rng.uniform(26, 38), h)
        cv2.rectangle(img, (0, 0), (w, brim), color, -1)
        cv2.ellipse(img, (w // 2, brim), (_s(64, w), _s(12, h)), 0, 0, 180, color, -1, cv2.LINE_AA)
        # Brim shadow — darkens the eyes without fully hiding them.
        band = img[brim:brim + _s(12, h)]
        if band.size:
            img[brim:brim + _s(12, h)] = (band.astype(np.float32) * 0.55).astype(np.uint8)
        return img

    def _draw_scarf(self, img: np.ndarray) -> np.ndarray:
        """Scarf — like a mask but higher, wider and asymmetric."""
        h, w = img.shape[:2]
        color = tuple(int(c) for c in _SCARF_COLORS[self.rng.integers(len(_SCARF_COLORS))])
        top = _s(self.rng.uniform(52, 62), h)
        tilt = _s(self.rng.uniform(-8, 8), h)
        poly = np.array([
            [0, top + tilt],
            [w, top - tilt],
            [w, h],
            [0, h],
        ], np.int32)
        cv2.fillPoly(img, [poly], color, lineType=cv2.LINE_AA)
        fold = tuple(max(0, c - 30) for c in color)
        cv2.line(img, (0, top + tilt + _s(14, h)), (w, top - tilt + _s(14, h)), fold, max(1, _s(2, h)), cv2.LINE_AA)
        return img

    def _draw_random_erase(self, img: np.ndarray) -> np.ndarray:
        """Random-erasing occluder (hand, phone, passer-by, frame edge)."""
        h, w = img.shape[:2]
        area = h * w
        for _ in range(10):
            target = area * float(self.rng.uniform(0.08, 0.30))
            ar = float(self.rng.uniform(0.4, 2.5))
            eh, ew = int(round(np.sqrt(target * ar))), int(round(np.sqrt(target / ar)))
            if eh < h and ew < w:
                y = int(self.rng.integers(0, h - eh))
                x = int(self.rng.integers(0, w - ew))
                patch = self.rng.integers(0, 256, size=(eh, ew, 3), dtype=np.uint8) \
                    if self.rng.random() < 0.35 \
                    else np.full((eh, ew, 3), self.rng.integers(0, 256, size=3), np.uint8)
                img[y:y + eh, x:x + ew] = patch
                break
        return img
