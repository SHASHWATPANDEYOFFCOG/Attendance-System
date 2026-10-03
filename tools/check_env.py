"""Part A step 0: prove the vendored pipeline imports, loads buffalo_l and runs.

Run:  .venv\\Scripts\\python.exe tools\\check_env.py
"""
from __future__ import annotations

import platform
import time

import numpy as np


def main() -> None:
    print("python      :", platform.python_version())
    print("machine     :", platform.processor() or platform.machine())

    import cv2
    import faiss
    import onnxruntime as ort

    print("opencv      :", cv2.__version__)
    print("onnxruntime :", ort.__version__, "providers:", ort.get_available_providers())
    print("faiss       :", getattr(faiss, "__version__", "n/a"))

    from occlubio import load_config
    from occlubio.pipeline.face_analyzer import FaceAnalyzer

    cfg = load_config()
    print("config      : det_size=%s score_thresh=%s match_threshold=%s min_quality=%s" % (
        cfg.detection.det_size, cfg.detection.score_thresh,
        cfg.gallery.match_threshold, cfg.quality.min_score,
    ))

    t0 = time.time()
    fa = FaceAnalyzer(
        model_name=cfg.detection.model_name,
        providers=list(cfg.device.providers),
        ctx_id=cfg.device.ctx_id,
        det_size=tuple(cfg.detection.det_size),
        score_thresh=cfg.detection.score_thresh,
        min_face=cfg.detection.min_face,
    )
    print("MODEL READY : %.1fs (first run includes the ~300MB download)" % (time.time() - t0))

    blank = np.zeros((480, 640, 3), np.uint8)
    t0 = time.time()
    faces = fa.analyze(blank)
    print("blank frame : %d faces, %.0f ms" % (len(faces), (time.time() - t0) * 1000))
    print("OK")


if __name__ == "__main__":
    main()
