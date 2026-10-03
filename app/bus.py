"""In-process event bus, fanning worker events out to SSE clients.

Camera workers run on their own threads; SSE subscribers are asyncio tasks. Publishing therefore
has to cross a thread boundary, which `publish_threadsafe` does via `call_soon_threadsafe`.

The bus is deliberately **lossy for slow clients and authoritative for nobody**. A subscriber
whose queue is full drops events rather than stalling the worker, and every SSE client re-syncs
from the database on connect and reconnect. A missed event must never mean a missed record —
the events are a live convenience, the database is the truth.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from occlubio.utils import get_logger

log = get_logger("app.bus")

MAX_QUEUE = 256


@dataclass
class Event:
    """One SSE event. `kind` matches the SSE event name the dashboard listens for."""

    kind: str
    payload: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[int] = None
    camera_id: Optional[int] = None
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    #: Set for personal events (notifications). Delivered ONLY to that user's own stream.
    user_id: Optional[int] = None

    def to_sse(self) -> str:
        body = json.dumps({"at": self.at, "session_id": self.session_id,
                           "camera_id": self.camera_id, **self.payload}, default=str)
        return f"event: {self.kind}\ndata: {body}\n\n"


class EventBus:
    def __init__(self) -> None:
        self._subs: Set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._recent: List[Event] = []          # small ring, for late joiners' context

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once from FastAPI startup so worker threads know where to hand events."""
        self._loop = loop

    # ----------------------------------------------------------- subscribing

    def subscribe(self, session_id: Optional[int] = None,
                  user_id: Optional[int] = None) -> asyncio.Queue:
        """`user_id` set: a personal stream receiving only that user's own events.
        Unset: a staff session stream, which never receives anyone's personal events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        q._session_filter = session_id            # type: ignore[attr-defined]
        q._user_filter = user_id                  # type: ignore[attr-defined]
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs.discard(q)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    # ------------------------------------------------------------ publishing

    def publish(self, event: Event) -> None:
        """Publish from the event loop's own thread."""
        self._remember(event)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            owner = getattr(q, "_user_filter", None)
            if owner is not None or event.user_id is not None:
                # Personal events go to their owner's stream and nowhere else, and a personal
                # stream carries nothing but its owner's events.
                if owner != event.user_id:
                    continue
            wanted = getattr(q, "_session_filter", None)
            if wanted is not None and event.session_id is not None and event.session_id != wanted:
                continue
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled browser tab must never back-pressure a camera.
                log.debug("dropping event for a full subscriber queue")

    def publish_threadsafe(self, event: Event) -> None:
        """Publish from a worker thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            self._remember(event)
            return
        try:
            loop.call_soon_threadsafe(self.publish, event)
        except RuntimeError:
            self._remember(event)

    def _remember(self, event: Event) -> None:
        with self._lock:
            self._recent.append(event)
            del self._recent[:-64]

    def recent(self, session_id: Optional[int] = None) -> List[Event]:
        with self._lock:
            items = list(self._recent)
        if session_id is None:
            return items
        return [e for e in items if e.session_id in (None, session_id)]


bus = EventBus()


def emit(kind: str, payload: Dict[str, Any], *, session_id: Optional[int] = None,
         camera_id: Optional[int] = None, user_id: Optional[int] = None,
         threadsafe: bool = True) -> Event:
    """Convenience publisher used by the worker and the API."""
    ev = Event(kind=kind, payload=payload, session_id=session_id, camera_id=camera_id,
               user_id=user_id)
    if threadsafe:
        bus.publish_threadsafe(ev)
    else:
        bus.publish(ev)
    return ev
