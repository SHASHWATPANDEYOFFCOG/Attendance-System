"""Tests for the reconstructed occlubio/data/occlusion_aug.py.

Two things are checked. First, the module satisfies the interface the upstream
`scripts/make_occluded_dataset.py` expects, so that script runs on a fresh clone instead of
raising ModuleNotFoundError. Second, the occluders land where the upstream occlusion estimator
looks for them - the augmentor draws a mask over the lower-face band, sunglasses over the eye
band, and a cap over the forehead band, so the two modules validate each other.
"""
from __future__ import annotations

import numpy as np
import pytest

from occlubio.data import OCCLUSION_KINDS, OcclusionAugmentor
from occlubio.pipeline.occlusion import OcclusionEstimator


def synthetic_face(size: int = 112) -> np.ndarray:
    """A skin-toned chip. Not a real face - enough for the region heuristics to read as clear."""
    img = np.full((size, size, 3), (150, 175, 215), np.uint8)      # BGR, mid skin tone
    noise = np.random.default_rng(0).integers(-8, 9, img.shape, dtype=np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ interface

def test_upstream_call_signature_works():
    """`OcclusionAugmentor(occlude_prob=..., photometric_prob=...)` then `aug(crop)`."""
    aug = OcclusionAugmentor(occlude_prob=1.0, photometric_prob=0.5, seed=1)
    out = aug(synthetic_face())
    assert out.shape == (112, 112, 3)
    assert out.dtype == np.uint8


def test_make_occluded_dataset_imports():
    """The upstream script's exact import must resolve."""
    from occlubio.data import OcclusionAugmentor as Imported
    assert Imported is OcclusionAugmentor


@pytest.mark.parametrize("kind", OCCLUSION_KINDS)
def test_every_kind_renders_and_preserves_shape(kind):
    aug = OcclusionAugmentor(seed=0)
    src = synthetic_face()
    out = aug.apply(src, kind)
    assert out.shape == src.shape and out.dtype == src.dtype
    if kind != "clear":
        assert not np.array_equal(out, src), f"{kind} changed nothing"


def test_clear_is_a_passthrough():
    aug = OcclusionAugmentor(seed=0)
    src = synthetic_face()
    assert np.array_equal(aug.apply(src, "clear"), src)


def test_unknown_kind_is_rejected():
    aug = OcclusionAugmentor(seed=0)
    with pytest.raises(ValueError):
        aug.apply(synthetic_face(), "balaclava")
    with pytest.raises(ValueError):
        OcclusionAugmentor(kinds=["nonsense"])


def test_seed_makes_output_reproducible():
    src = synthetic_face()
    a = OcclusionAugmentor(seed=42)(src.copy())
    b = OcclusionAugmentor(seed=42)(src.copy())
    assert np.array_equal(a, b)


def test_works_on_non_112_crops():
    aug = OcclusionAugmentor(seed=0)
    src = synthetic_face(224)
    assert aug.apply(src, "mask").shape == (224, 224, 3)


# ------------------------------- agreement with the occlusion estimator ------

def test_mask_is_detected_as_lower_face():
    """A synthesised mask must be visible to occlusion.py's lower-band heuristic."""
    est = OcclusionEstimator(True)
    aug = OcclusionAugmentor(seed=3)
    hits = 0
    for s in range(12):
        out = OcclusionAugmentor(seed=s).apply(synthetic_face(), "mask")
        r = est.estimate(out)
        if r["type"] in ("lower_face", "heavy"):
            hits += 1
    assert hits >= 10, f"only {hits}/12 synthesised masks were detected as lower-face occlusion"


def test_masked_face_routes_to_periocular():
    """occlusion.py sets use_periocular for lower-face cover - the masked-FR path."""
    est = OcclusionEstimator(True)
    out = OcclusionAugmentor(seed=5).apply(synthetic_face(), "mask")
    assert est.estimate(out).get("use_periocular") is True


def test_sunglasses_darken_the_eye_band():
    """The estimator keys on a dark, low-skin eye band; verify the occluder produces one."""
    src = synthetic_face()
    out = OcclusionAugmentor(seed=2).apply(src, "sunglasses")
    band = (slice(40, 64), slice(16, 96))
    assert out[band].mean() < src[band].mean() - 40


def test_cap_covers_the_forehead_band():
    src = synthetic_face()
    out = OcclusionAugmentor(seed=4).apply(src, "cap")
    band = (slice(0, 38), slice(20, 92))
    assert not np.array_equal(out[band], src[band])
    assert np.array_equal(out[80:112, 20:92], src[80:112, 20:92]), "a cap must not touch the chin"


def test_clean_face_reads_as_clear():
    """Guards the other direction: the estimator must not flag an unoccluded chip."""
    assert OcclusionEstimator(True).estimate(synthetic_face())["type"] == "clear"


# ------------------------------------------------------------- photometric ---

def test_photometric_changes_pixels_but_not_geometry():
    aug = OcclusionAugmentor(seed=9)
    src = synthetic_face()
    out = aug.photometric(src)
    assert out.shape == src.shape
    assert not np.array_equal(out, src)


def test_occlude_prob_zero_leaves_geometry_alone():
    aug = OcclusionAugmentor(occlude_prob=0.0, photometric_prob=0.0, seed=0)
    src = synthetic_face()
    assert np.array_equal(aug(src), src)
