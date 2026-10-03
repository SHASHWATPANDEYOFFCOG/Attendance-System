"""Part A step A4: derive match_threshold / review_threshold / dup_threshold from YOUR faces.

Threshold choice is the single highest-leverage decision in this build, and it is data, not
opinion. The values shipped in configs/default.yaml are the build spec's placeholders and are
marked UNVALIDATED; this script is how you replace them.

It uses **your own enrolled identities**, not LFW or any public benchmark, because the operating
point that matters is the one on your cameras, your lighting and your population.

    # 1. lay out reference images, one folder per person, >= 2 images each
    #      data/enroll/<person>/*.jpg
    # 2. synthesise the occluded copies (masks / sunglasses / caps)
    python tools/roc.py --images data/enroll --out var/roc

Outputs a genuine/impostor score distribution, TAR at FAR = 1e-3 and 1e-4 for the clean, masked
and sunglasses subsets, and a recommended threshold triple to paste into the config.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from occlubio import load_config
from occlubio.data import OcclusionAugmentor
from occlubio.pipeline.aligner import norm_crop
from occlubio.pipeline.face_analyzer import FaceAnalyzer
from occlubio.pipeline.quality import FaceQualityGate
from occlubio.utils import get_logger, l2_normalize

log = get_logger("roc")
_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# The occlusion conditions reported separately, per the build spec.
CONDITIONS = ("clean", "mask", "sunglasses")


def collect(root: Path) -> Dict[str, List[Path]]:
    people: Dict[str, List[Path]] = defaultdict(list)
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() in _IMG_EXT and p.parent != root:
            people[p.parent.name].append(p)
    return dict(people)


def embed_all(images: Dict[str, List[Path]], cfg, aug: OcclusionAugmentor
              ) -> Dict[str, Dict[str, List[np.ndarray]]]:
    """Return {condition: {person: [embeddings]}} for clean and each occluded variant."""
    analyzer = FaceAnalyzer(
        model_name=cfg.detection.model_name, providers=list(cfg.device.providers),
        ctx_id=cfg.device.ctx_id, det_size=tuple(cfg.detection.det_size),
        score_thresh=cfg.detection.score_thresh, min_face=cfg.detection.min_face,
    )
    rec = analyzer.app.models.get("recognition")
    if rec is None:
        raise SystemExit("buffalo_l loaded without a recognition head — cannot score.")
    gate = FaceQualityGate(cfg)

    out: Dict[str, Dict[str, List[np.ndarray]]] = {c: defaultdict(list) for c in CONDITIONS}
    dropped = 0

    for person, paths in images.items():
        for path in paths:
            img = cv2.imread(str(path))
            if img is None:
                continue
            faces = analyzer.analyze(img)
            if len(faces) != 1:
                dropped += 1
                continue
            chip = norm_crop(img, faces[0].kps)
            passed, q = gate.passes(chip, faces[0].det_score)
            if not passed:
                dropped += 1
                continue

            for cond in CONDITIONS:
                variant = chip if cond == "clean" else aug.apply(chip, cond)
                emb = l2_normalize(np.asarray(rec.get_feat(variant)).ravel())
                out[cond][person].append(emb)

    log.info("embedded %d identities (%d image(s) dropped by the quality gate)",
             len(images), dropped)
    return {c: dict(v) for c, v in out.items()}


def score_pairs(by_person: Dict[str, List[np.ndarray]]) -> Tuple[np.ndarray, np.ndarray]:
    """All genuine and impostor cosine similarities. Vectors are unit-length, so dot == cosine."""
    genuine, impostor = [], []
    people = sorted(by_person)
    for i, a in enumerate(people):
        va = by_person[a]
        for x in range(len(va)):
            for y in range(x + 1, len(va)):
                genuine.append(float(va[x] @ va[y]))
        for b in people[i + 1:]:
            for ea in va:
                for eb in by_person[b]:
                    impostor.append(float(ea @ eb))
    return np.array(genuine), np.array(impostor)


def threshold_at_far(impostor: np.ndarray, far: float) -> float:
    """Lowest score at which the impostor false-accept rate is <= far."""
    if impostor.size == 0:
        return float("nan")
    return float(np.quantile(impostor, 1.0 - far))


def tar_at(genuine: np.ndarray, thresh: float) -> float:
    if genuine.size == 0 or not np.isfinite(thresh):
        return float("nan")
    return float((genuine >= thresh).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="root/<person>/<image>")
    ap.add_argument("--out", default="var/roc")
    ap.add_argument("--config", default=None)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    cfg = load_config(args.config)
    root = Path(args.images)
    if not root.exists():
        raise SystemExit(f"no such directory: {root}")

    people = collect(root)
    usable = {k: v for k, v in people.items() if len(v) >= 2}
    if len(usable) < 2:
        raise SystemExit(
            f"Need >= 2 identities with >= 2 images each; found {len(usable)}. "
            f"Impostor pairs cannot be formed otherwise, and without impostor scores there is "
            f"no FAR to choose a threshold at."
        )
    log.info("using %d identities: %s", len(usable), ", ".join(sorted(usable)))

    aug = OcclusionAugmentor(seed=args.seed)
    embeddings = embed_all(usable, cfg, aug)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"identities": sorted(usable), "conditions": {}}

    print("\n" + "=" * 78)
    print(f"{'condition':<12}{'genuine':>9}{'impostor':>10}{'g.mean':>9}{'i.mean':>9}"
          f"{'TAR@1e-3':>10}{'TAR@1e-4':>10}")
    print("=" * 78)

    thresholds: Dict[str, float] = {}
    for cond in CONDITIONS:
        g, i = score_pairs(embeddings[cond])
        t3, t4 = threshold_at_far(i, 1e-3), threshold_at_far(i, 1e-4)
        thresholds[cond] = t3
        report["conditions"][cond] = {
            "n_genuine": int(g.size), "n_impostor": int(i.size),
            "genuine_mean": float(g.mean()) if g.size else None,
            "genuine_p05": float(np.quantile(g, 0.05)) if g.size else None,
            "impostor_mean": float(i.mean()) if i.size else None,
            "impostor_max": float(i.max()) if i.size else None,
            "threshold_at_far_1e3": t3, "threshold_at_far_1e4": t4,
            "tar_at_far_1e3": tar_at(g, t3), "tar_at_far_1e4": tar_at(g, t4),
        }
        print(f"{cond:<12}{g.size:>9}{i.size:>10}"
              f"{(g.mean() if g.size else float('nan')):>9.3f}"
              f"{(i.mean() if i.size else float('nan')):>9.3f}"
              f"{tar_at(g, t3):>10.3f}{tar_at(g, t4):>10.3f}")
    print("=" * 78)

    # match_threshold at FAR=1e-3 on CLEAN pairs: the operating point for an unambiguous mark.
    match = thresholds["clean"]
    # review_threshold where genuine masked scores start overlapping impostors: the 5th
    # percentile of masked genuine scores. Between the two is the review band.
    g_mask, _ = score_pairs(embeddings["mask"])
    review = float(np.quantile(g_mask, 0.05)) if g_mask.size else match * 0.7
    review = min(review, match - 0.02)
    # dup_threshold must sit well above match: a same-person pair should clear it comfortably.
    g_clean, _ = score_pairs(embeddings["clean"])
    dup = float(np.quantile(g_clean, 0.10)) if g_clean.size else match + 0.15
    dup = max(dup, match + 0.05)

    report["recommended"] = {"match_threshold": round(match, 3),
                             "review_threshold": round(review, 3),
                             "dup_threshold": round(dup, 3)}

    print("\nPaste into configs/default.yaml under `gallery:` and delete the UNVALIDATED note:\n")
    print(f"  match_threshold:  {match:.3f}   # TAR {tar_at(g_clean, match):.3f} at FAR 1e-3, "
          f"clean, {len(usable)} identities")
    print(f"  review_threshold: {review:.3f}   # 5th pct of genuine MASKED scores")
    print(f"  dup_threshold:    {dup:.3f}   # 10th pct of genuine clean scores")

    if len(usable) < 10:
        print(f"\n  !! Only {len(usable)} identities. A FAR of 1e-4 needs >= 10,000 impostor "
              f"pairs to be meaningful; you have {report['conditions']['clean']['n_impostor']}. "
              f"Treat these numbers as indicative and re-run as enrolment grows.")

    (out_dir / "roc_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _try_plot(embeddings, out_dir)
    print(f"\nWritten: {out_dir / 'roc_report.json'}")


def _try_plot(embeddings, out_dir: Path) -> None:
    """Plot the distributions if matplotlib is installed; the numbers stand without it."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.info("matplotlib not installed - skipping the plot (pip install -e '.[plot]')")
        return

    fig, axes = plt.subplots(1, len(CONDITIONS), figsize=(4.6 * len(CONDITIONS), 3.6), sharey=True)
    for ax, cond in zip(np.atleast_1d(axes), CONDITIONS):
        g, i = score_pairs(embeddings[cond])
        if g.size:
            ax.hist(g, bins=40, alpha=.65, label="genuine", color="#2E6B4F")
        if i.size:
            ax.hist(i, bins=40, alpha=.65, label="impostor", color="#9A3B2E")
        ax.set_title(cond)
        ax.set_xlabel("cosine similarity")
        ax.legend(fontsize=8)
    plt.tight_layout()
    path = out_dir / "score_distributions.png"
    plt.savefig(path, dpi=130)
    log.info("plot written -> %s", path)


if __name__ == "__main__":
    main()
