"""Process-wide handle on the occlubio pipeline stages.

Constructing a FaceAnalyzer costs ~5 s and a few hundred MB, so it is built once and shared. The
stages are used individually rather than through `RecognitionEngine.process_frame`, for two
reasons that matter to attendance:

* `process_frame` fuses embeddings across a track buffer before searching. That is good for a
  single best-guess identity, but it makes consecutive frames statistically dependent — and the
  confirmation state machine's whole premise is N *independent* agreeing frames. We search on
  each frame's own embedding.
* `gallery.identify()` collapses anything below `match_threshold` to "unknown", discarding the
  score. The state machine needs the raw top-1 similarity to distinguish the review band from a
  genuine non-match, so we call `gallery.search()` and threshold ourselves.

Nothing in occlubio/ is modified; this module only composes it.
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np

from occlubio.pipeline.aligner import norm_crop
from occlubio.pipeline.antispoof import AntiSpoof
from occlubio.pipeline.face_analyzer import FaceAnalyzer, FaceResult
from occlubio.pipeline.occlusion import OcclusionEstimator
from occlubio.pipeline.quality import FaceQualityGate
from occlubio.utils import get_logger, l2_normalize

log = get_logger("app.pipeline")

_lock = threading.Lock()
_instance: Optional["PipelineService"] = None


class PipelineService:
    """Detect / align / quality / occlusion / anti-spoof / embed, shared across threads."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.analyzer = FaceAnalyzer(
            model_name=cfg.detection.model_name,
            providers=list(cfg.device.providers),
            ctx_id=cfg.device.ctx_id,
            det_size=tuple(cfg.detection.det_size),
            score_thresh=cfg.detection.score_thresh,
            min_face=cfg.detection.min_face,
            detection_only=bool(getattr(cfg.recognition, "custom_onnx", None)),
        )
        self.quality = FaceQualityGate(cfg)
        self.occlusion = OcclusionEstimator(cfg.occlusion.enabled)
        self.antispoof = AntiSpoof(cfg)
        self._custom = None
        if getattr(cfg.recognition, "custom_onnx", None):
            from occlubio.pipeline.recognizer import CustomRecognizer
            self._custom = CustomRecognizer(cfg.recognition.custom_onnx,
                                            providers=list(cfg.device.providers))
        # onnxruntime sessions are not guaranteed re-entrant across threads.
        self._infer_lock = threading.Lock()

    # ------------------------------------------------------------ properties

    @property
    def antispoof_available(self) -> bool:
        """True only when real PAD weights are loaded and will actually be run.

        When this is False, `AntiSpoof.check()` returns live=True for everything — including a
        phone screen held up to the camera. See PRIVACY.md and cfg.attendance.antispoof_mode.
        """
        return bool(self.antispoof.enabled and self.antispoof.session is not None)

    # --------------------------------------------------------------- stages

    def detect(self, frame: np.ndarray) -> List[FaceResult]:
        with self._infer_lock:
            return self.analyzer.analyze(frame)

    def align(self, frame: np.ndarray, face: FaceResult) -> np.ndarray:
        return norm_crop(frame, face.kps)

    def assess(self, chip: np.ndarray, det_score: float) -> Tuple[bool, float, dict, dict]:
        """Quality gate + occlusion estimate + anti-spoof for one aligned chip."""
        passed, quality = self.quality.passes(chip, det_score)
        occ = self.occlusion.estimate(chip)
        spoof = self.antispoof.check(chip)
        return passed, quality, occ, spoof

    def embed(self, frame: np.ndarray, face: FaceResult, chip: np.ndarray) -> np.ndarray:
        """Return the L2-normalised 512-d template for one face.

        Normalisation is applied unconditionally here: IndexFlatIP over unit vectors is cosine
        similarity, and skipping it would silently invalidate every threshold in the config.
        """
        if self._custom is not None:
            return l2_normalize(self._custom.embed(chip))
        if face.embedding is not None:
            return l2_normalize(face.embedding)
        with self._infer_lock:
            rec = self.analyzer.app.models.get("recognition")
            if rec is None:
                raise RuntimeError(
                    "No recognition model available. buffalo_l was loaded detection-only — "
                    "set recognition.custom_onnx or clear it in configs/default.yaml."
                )
            return l2_normalize(np.asarray(rec.get_feat(chip)).ravel())


def get_pipeline(cfg) -> PipelineService:
    """Lazily build the shared pipeline. Thread-safe."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = PipelineService(cfg)
    return _instance


def reset_pipeline() -> None:
    """Drop the shared instance (tests)."""
    global _instance
    with _lock:
        _instance = None
