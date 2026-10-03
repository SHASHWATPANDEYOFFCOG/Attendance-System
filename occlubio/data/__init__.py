"""Synthetic occlusion + photometric augmentation.

Reconstructed for this project — the upstream repo's bare `data/` .gitignore pattern excluded
this package from the published tree. See occlusion_aug.py for the full note.
"""
from occlubio.data.occlusion_aug import OCCLUSION_KINDS, OcclusionAugmentor

__all__ = ["OcclusionAugmentor", "OCCLUSION_KINDS"]
