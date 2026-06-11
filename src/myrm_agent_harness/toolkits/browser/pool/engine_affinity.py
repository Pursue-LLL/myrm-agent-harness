"""Domain-level engine affinity memory.

Remembers which browser engine worked for a given domain so subsequent
sessions skip the probe-and-upgrade cycle.  Storage is a lightweight JSON
file under ``MYRM_DATA_DIR`` with in-memory LRU caching.

Write path:  BrowserSession records ``domain → engine`` after a successful
             engine upgrade (e.g. Chromium → CAMOUFOX).
Read path:   BrowserSession queries the store before ``navigate()`` and
             overrides ``_engine_preference`` if a hit is found.
Invalidation: entries expire after ``_DEFAULT_TTL_DAYS``; a failed
              navigation with the remembered engine clears the entry.

[INPUT]
- .config::BrowserEngine (POS: browser engine enum)

[OUTPUT]
- get_engine_affinity_store: module-level singleton accessor
- EngineAffinityStore: domain → engine memory with TTL and LRU caching

[POS]
Domain-level engine affinity memory for the browser pool.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import BrowserEngine

logger = logging.getLogger(__name__)

_DEFAULT_TTL_DAYS = 7
_TTL_SECONDS = _DEFAULT_TTL_DAYS * 86400
_MAX_ENTRIES = 500


def _store_path() -> str:
    data_dir = os.environ.get("MYRM_DATA_DIR", os.path.expanduser("~/.myrm"))
    return os.path.join(data_dir, "browser", "engine_affinity.json")


class EngineAffinityStore:
    """In-memory + file-backed domain→engine affinity cache."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}
        self._dirty = False
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = _store_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw: dict[str, list[object]] = json.load(f)
            now = time.time()
            for domain, entry in raw.items():
                if isinstance(entry, list) and len(entry) == 2:
                    engine_val, ts = str(entry[0]), float(entry[1])
                    if now - ts < _TTL_SECONDS:
                        self._cache[domain] = (engine_val, ts)
        except Exception:
            logger.debug("Failed to load engine affinity store, starting fresh")

    def get(self, domain: str) -> BrowserEngine | None:
        """Return remembered engine for *domain*, or ``None``."""
        from .config import BrowserEngine

        self._ensure_loaded()
        entry = self._cache.get(domain)
        if entry is None:
            return None
        engine_val, ts = entry
        if time.time() - ts >= _TTL_SECONDS:
            del self._cache[domain]
            self._dirty = True
            return None
        try:
            return BrowserEngine(engine_val)
        except ValueError:
            del self._cache[domain]
            self._dirty = True
            return None

    def record(self, domain: str, engine: BrowserEngine) -> None:
        """Remember that *domain* requires *engine*."""
        self._ensure_loaded()
        self._cache[domain] = (engine.value, time.time())
        self._dirty = True
        if len(self._cache) > _MAX_ENTRIES:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]
        self._flush()

    def clear(self, domain: str) -> None:
        """Remove affinity for *domain* (e.g. after the remembered engine also fails)."""
        self._ensure_loaded()
        if domain in self._cache:
            del self._cache[domain]
            self._dirty = True
            self._flush()

    def _flush(self) -> None:
        if not self._dirty:
            return
        self._dirty = False
        path = _store_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {d: [e, t] for d, (e, t) in self._cache.items()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
        except Exception:
            logger.debug("Failed to persist engine affinity store", exc_info=True)


_global_store: EngineAffinityStore | None = None


def get_engine_affinity_store() -> EngineAffinityStore:
    """Return the module-level singleton store instance."""
    global _global_store  # noqa: PLW0603
    if _global_store is None:
        _global_store = EngineAffinityStore()
    return _global_store
