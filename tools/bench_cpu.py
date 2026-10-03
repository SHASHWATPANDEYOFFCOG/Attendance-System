"""Part A: measure the real per-stage CPU cost of the pipeline on THIS machine.

Every number printed here is measured, not estimated. Stage costs for the two CNNs (SCRFD
detector, ArcFace embedder) are input-size-fixed, so they are valid without real faces; the
FAISS numbers use synthetic unit-norm vectors, which is exactly what real embeddings are.

Run:  .venv\\Scripts\\python.exe tools\\bench_cpu.py
"""
from __future__ import annotations

import statistics
import time
from typing import Callable, List

import cv2
import numpy as np

from occlubio import load_config
from occlubio.data import OCCLUSION_KINDS, OcclusionAugmentor
from occlubio.gallery import FaissGallery
from occlubio.pipeline.aligner import norm_crop
from occlubio.pipeline.face_analyzer import FaceAnalyzer
from occlubio.pipeline.occlusion import OcclusionEstimator
from occlubio.pipeline.quality import FaceQualityGate
from occlubio.utils import l2_normalize

WARMUP = 3
ITERS = 15


def timeit(fn: Callable[[], object], iters: int = ITERS, warmup: int = WARMUP) -> tuple[float, float]:
    """Return (median_ms, p90_ms)."""
    for _ in range(warmup):
        fn()
    samples: List[float] = []
    for _ in range(iters):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000.0)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.9) - 1]


def row(name: str, med: float, p90: float, note: str = "") -> None:
    print(f"  {name:<34} {med:8.1f} ms   p90 {p90:7.1f} ms   {note}")


def main() -> None:
    cfg = load_config()
    rng = np.random.default_rng(0)

    # A realistic-entropy frame. Detector cost is dominated by the fixed det_size CNN, but
    # noise avoids any trivial all-zero shortcut in memory bandwidth.
    frame = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
    crop = rng.integers(60, 200, (112, 112, 3), dtype=np.uint8)

    print("\n=== 1. SCRFD detection (buffalo_l det_10g) — cost vs det_size ===")
    det_costs = {}
    for size in (640, 480, 320):
        fa = FaceAnalyzer(
            model_name=cfg.detection.model_name, providers=list(cfg.device.providers),
            ctx_id=cfg.device.ctx_id, det_size=(size, size),
            score_thresh=cfg.detection.score_thresh, min_face=cfg.detection.min_face,
            detection_only=True,
        )
        med, p90 = timeit(lambda: fa.analyze(frame))
        det_costs[size] = med
        row(f"detect @ {size}x{size}", med, p90, f"{1000.0 / med:5.1f} FPS detect-only")

    print("\n=== 2. ArcFace embedding (w600k_r50) — per face ===")
    full = FaceAnalyzer(
        model_name=cfg.detection.model_name, providers=list(cfg.device.providers),
        ctx_id=cfg.device.ctx_id, det_size=tuple(cfg.detection.det_size),
        score_thresh=cfg.detection.score_thresh, min_face=cfg.detection.min_face,
    )
    rec = full.app.models.get("recognition")
    if rec is None:
        print("  !! recognition model not loaded — cannot measure embedding cost")
        emb_med = float("nan")
    else:
        emb_med, emb_p90 = timeit(lambda: rec.get_feat(crop))
        row("embed 1 face (112x112)", emb_med, emb_p90)
        feat = rec.get_feat(crop)
        v = np.asarray(feat).ravel()
        print(f"  embedding dim = {v.size}  (config says {cfg.recognition.embedding_dim})")
        n = float(np.linalg.norm(v))
        print(f"  raw L2 norm   = {n:.3f}  -> normalised norm = "
              f"{float(np.linalg.norm(l2_normalize(v))):.3f}")

    print("\n=== 3. Cheap CPU stages (per face) ===")
    kps = np.array([[38, 45], [74, 45], [56, 68], [40, 88], [72, 88]], np.float32)
    med, p90 = timeit(lambda: norm_crop(frame, kps))
    row("align (similarity transform)", med, p90)

    qg = FaceQualityGate(cfg)
    med, p90 = timeit(lambda: qg.passes(crop, 0.9))
    row("quality gate (FIQA proxy)", med, p90)

    oe = OcclusionEstimator(True)
    med, p90 = timeit(lambda: oe.estimate(crop))
    row("occlusion estimate", med, p90)

    print("\n=== 4. FAISS IndexFlatIP 1:N search ===")
    for n_ids in (100, 1200, 5000):
        g = FaissGallery(dim=cfg.recognition.embedding_dim)
        embs = l2_normalize(rng.normal(size=(n_ids, cfg.recognition.embedding_dim)).astype(np.float32))
        g.add_many(embs, [f"id{i}" for i in range(n_ids)])
        q = l2_normalize(rng.normal(size=cfg.recognition.embedding_dim).astype(np.float32))
        med, p90 = timeit(lambda: g.search(q, top_k=cfg.gallery.top_k), iters=50, warmup=10)
        row(f"search over {n_ids:>5} identities", med, p90)

    print("\n=== 5. Occlusion augmentor (restored module) ===")
    aug = OcclusionAugmentor(seed=0)
    for kind in OCCLUSION_KINDS:
        out = aug.apply(crop, kind)
        assert out.shape == crop.shape, kind
    med, p90 = timeit(lambda: aug(crop))
    row("augment 1 crop (random kind)", med, p90, f"kinds={len(OCCLUSION_KINDS)}")

    print("\n=== 6. Frame budget for a live worker (CPU-only, this machine) ===")
    d640, d480, d320 = det_costs[640], det_costs[480], det_costs[320]
    print(f"  Detection is {d640 / max(emb_med, 1e-6):.1f}x the cost of one embedding, so"
          f" detect_every_n_frames is the dominant knob.\n")
    print(f"  {'det_size':>9} {'detect':>9} {'+1 face':>9} {'stride=1':>10} {'stride=3':>10} {'stride=5':>10}")
    for size, d in ((640, d640), (480, d480), (320, d320)):
        one = d + emb_med
        print(f"  {size:>9} {d:>8.0f}ms {one:>8.0f}ms "
              f"{1000.0 / one:>9.1f}f {1000.0 / (d / 3 + emb_med):>9.1f}f "
              f"{1000.0 / (d / 5 + emb_med):>9.1f}f")
    print("\n  (stride=N == cfg.attendance.detect_every_n_frames; embedding still runs on every"
          "\n   processed frame for unconfirmed tracks, which is why the gain saturates.)")


if __name__ == "__main__":
    main()
