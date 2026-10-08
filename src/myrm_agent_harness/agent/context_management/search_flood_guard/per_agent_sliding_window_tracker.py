# [INPUT]: FloodGuardConfig, SlidingWindowBucket
# [OUTPUT]: PerAgentSlidingWindowTracker
# [POS]: agent/context_management/search_flood_guard/per_agent_sliding_window_tracker.py

"""Per-agent-context sliding window tracker managing timestamp queues and LRU eviction.

[INPUT]
- FloodGuardConfig, SlidingWindowBucket: Contract definitions.

[OUTPUT]
- PerAgentSlidingWindowTracker: Thread-safe, bounded memory tracker for per-agent rate windows.

[POS]
Sliding window rate tracking and LRU memory ceiling layer for search flood guard.
"""

from __future__ import annotations

import collections
import time
from typing import Mapping, Sequence

from .flood_guard_types import FloodGuardConfig, SlidingWindowBucket


class PerAgentSlidingWindowTracker:
    """Tracks invocation timestamps per session+subagent key with rolling windows and LRU cap."""

    def __init__(self, config: FloodGuardConfig | None = None) -> None:
        self._config = config or FloodGuardConfig()
        # OrderedDict used as LRU cache: key -> SlidingWindowBucket
        self._buckets: collections.OrderedDict[str, SlidingWindowBucket] = collections.OrderedDict()

    def format_key(self, session_id: str, subagent_id: str | None = None) -> str:
        """Constructs standardized composite tracking key isolating subagent executions."""
        agent_part = subagent_id.strip() if subagent_id and subagent_id.strip() else "main"
        return f"{session_id}:{agent_part}"

    def record_call(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> tuple[int, SlidingWindowBucket]:
        """Records a new call event within the sliding window, pruning expired events."""
        now = timestamp if timestamp is not None else time.time()
        key = self.format_key(session_id, subagent_id)

        bucket = self._get_or_create_bucket(key, now)
        # 1. Cooldown recovery: if cooldown expired, clear penalty state and obsolete timestamps
        if bucket.blocked_until > 0.0:
            if now >= bucket.blocked_until:
                bucket.blocked_until = 0.0
                bucket.timestamps.clear()

        # 2. Prune expired timestamps outside sliding window
        window_start = now - self._config.window_seconds
        bucket.timestamps = [ts for ts in bucket.timestamps if ts > window_start]

        # 3. Append current invocation
        bucket.timestamps.append(now)
        bucket.last_accessed = now

        return len(bucket.timestamps), bucket

    def get_window_count(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> int:
        """Reads current non-expired call count for the specified context without appending."""
        now = timestamp if timestamp is not None else time.time()
        key = self.format_key(session_id, subagent_id)

        if key not in self._buckets:
            return 0

        bucket = self._buckets[key]
        window_start = now - self._config.window_seconds
        valid_ts = [ts for ts in bucket.timestamps if ts > window_start]
        bucket.timestamps = valid_ts
        bucket.last_accessed = now
        self._buckets.move_to_end(key)
        return len(valid_ts)

    def set_block_cooldown(
        self,
        session_id: str,
        subagent_id: str | None,
        blocked_until: float,
    ) -> None:
        """Sets hard block expiry timestamp for the specified context key."""
        key = self.format_key(session_id, subagent_id)
        bucket = self._get_or_create_bucket(key, time.time())
        bucket.blocked_until = blocked_until

    def get_remaining_cooldown(
        self,
        session_id: str,
        subagent_id: str | None = None,
        timestamp: float | None = None,
    ) -> float:
        """Returns remaining cooldown seconds if currently hard-blocked, else 0.0."""
        now = timestamp if timestamp is not None else time.time()
        key = self.format_key(session_id, subagent_id)
        if key not in self._buckets:
            return 0.0
        bucket = self._buckets[key]
        if bucket.blocked_until > now:
            return round(bucket.blocked_until - now, 2)
        return 0.0

    def reset_bucket(self, session_id: str, subagent_id: str | None = None) -> None:
        """Clears invocation history for a specific agent context."""
        key = self.format_key(session_id, subagent_id)
        if key in self._buckets:
            del self._buckets[key]

    @property
    def tracked_keys_count(self) -> int:
        return len(self._buckets)

    def _get_or_create_bucket(self, key: str, now: float) -> SlidingWindowBucket:
        if key in self._buckets:
            bucket = self._buckets[key]
            self._buckets.move_to_end(key)
            return bucket

        # Evict oldest key if LRU ceiling exceeded
        if len(self._buckets) >= self._config.max_tracked_keys:
            self._buckets.popitem(last=False)

        bucket = SlidingWindowBucket(key=key, timestamps=[], last_accessed=now, blocked_until=0.0)
        self._buckets[key] = bucket
        return bucket
