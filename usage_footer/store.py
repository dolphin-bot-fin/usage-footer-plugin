"""TTL cache + background refresher. The reply path reads only cached state (lock-
guarded, microseconds); one daemon thread refreshes each enabled provider on its
own interval. Any exception in a fetch is contained per-provider.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from .providers import fetch_provider

logger = logging.getLogger(__name__)

DEFAULT_TTL = 60.0  # seconds between refresh cycles (footer shows minute-scale data)
MIN_TTL = 15.0
MAX_TTL = 900.0


class UsageStore:
    """Thread-safe {provider: snapshot} cache with a daemon refresher."""

    def __init__(self, ttl: float = DEFAULT_TTL):
        self._ttl = self._clamp_ttl(ttl)
        self._lock = threading.Lock()
        self._snapshots: dict[str, Any] = {}
        self._stamps: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @staticmethod
    def _clamp_ttl(ttl: Any) -> float:
        try:
            return max(MIN_TTL, min(MAX_TTL, float(ttl)))
        except (TypeError, ValueError):
            return DEFAULT_TTL

    # -- read path (called from the footer renderer) --------------------------

    def get(self, provider: str) -> Optional[Any]:
        with self._lock:
            return self._snapshots.get(provider)

    def all_snapshots(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._snapshots)

    def age_seconds(self, provider: str) -> Optional[float]:
        with self._lock:
            stamp = self._stamps.get(provider)
        return time.monotonic() - stamp if stamp is not None else None

    # -- lifecycle -------------------------------------------------------------

    def start(self, enabled: list[str], ttl: Any = None) -> None:
        """Start the refresher for the given providers. Safe to call twice (no-op)."""
        if not enabled or (self._thread is not None and self._thread.is_alive()):
            return
        if ttl is not None:
            self._ttl = self._clamp_ttl(ttl)
        self._stop.clear()
        thread = threading.Thread(target=self._run, args=(tuple(enabled),),
                                  name="usage-footer-refresher", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        with self._lock:
            self._snapshots.clear()
            self._stamps.clear()

    # -- refresher thread --------------------------------------------------------

    def _run(self, enabled: tuple[str, ...]) -> None:
        # Stagger first fetches slightly so several providers don't burst at once.
        for index, name in enumerate(enabled):
            if self._stop.is_set():
                return
            self._refresh_one(name)
            if index < len(enabled) - 1:
                self._stop.wait(0.5)
        while not self._stop.wait(self._ttl):
            for name in enabled:
                if self._stop.is_set():
                    return
                self._refresh_one(name)

    def _refresh_one(self, name: str) -> None:
        try:
            snap = fetch_provider(name)
        except Exception:
            snap = None
        if snap is None:
            # Keep the previous snapshot (if any) so a transient blip doesn't blank the
            # footer; a provider with no data yet simply stays absent.
            return
        with self._lock:
            self._snapshots[name] = snap
            self._stamps[name] = time.monotonic()


_STORE: Optional[UsageStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> UsageStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = UsageStore()
        return _STORE
