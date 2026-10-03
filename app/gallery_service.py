"""The FAISS index, derived from the database.

**The database is the source of truth; the index is a cache.** It is rebuilt from `enrollments`
at startup and after every enrollment, deletion or deactivation. It is never the only copy of a
template, and losing `gallery_store/` costs nothing but a rebuild.

Labels in the index are stringified `user.id`, not usernames — a username or roll number can be
edited, and a renamed person must not silently become a different identity.
"""
from __future__ import annotations

import threading
from typing import List, Optional, Tuple

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import decrypt_embedding
from app.models import Enrollment
from occlubio.gallery import FaissGallery
from occlubio.utils import get_logger

log = get_logger("app.gallery")

_lock = threading.RLock()
_gallery: Optional[FaissGallery] = None


def rebuild_index(db: Session, cfg) -> FaissGallery:
    """Rebuild the whole index from active enrollments. Cheap: 1200 ids is milliseconds."""
    global _gallery
    dim = int(cfg.recognition.embedding_dim)
    rows: List[Enrollment] = list(
        db.scalars(select(Enrollment).where(Enrollment.is_active.is_(True)))
    )

    g = FaissGallery(dim=dim)
    if rows:
        vectors, labels, metas = [], [], []
        for e in rows:
            try:
                vectors.append(decrypt_embedding(e.embedding_encrypted, dim))
            except (RuntimeError, ValueError) as exc:
                # One unreadable row must not take the whole gallery down with it.
                log.error("skipping enrollment %d for user %d: %s", e.id, e.user_id, exc)
                continue
            labels.append(str(e.user_id))
            metas.append({"enrollment_id": e.id, "n_images": e.n_images,
                          "mean_quality": e.mean_quality})
        if vectors:
            g.add_many(np.stack(vectors), labels, metas)

    with _lock:
        _gallery = g
    log.info("FAISS index rebuilt from DB: %d template(s)", len(g))
    return g


def get_gallery(db: Session, cfg) -> FaissGallery:
    """Return the live index, building it on first use."""
    global _gallery
    with _lock:
        if _gallery is not None:
            return _gallery
    return rebuild_index(db, cfg)


def invalidate() -> None:
    """Force the next `get_gallery` to rebuild (tests, and after bulk changes)."""
    global _gallery
    with _lock:
        _gallery = None


def search_top1(gallery: FaissGallery, emb: np.ndarray) -> Tuple[Optional[int], float]:
    """Return (user_id, raw cosine score) for the best hit, without applying any threshold.

    Thresholding is the state machine's job — it needs to tell "below match but above review"
    (a candidate) apart from "below review" (an unknown face), and `gallery.identify()` throws
    that distinction away.
    """
    hits = gallery.search(emb, top_k=1)
    if not hits:
        return None, 0.0
    label, score, _meta = hits[0]
    try:
        return int(label), float(score)
    except (TypeError, ValueError):
        return None, float(score)
