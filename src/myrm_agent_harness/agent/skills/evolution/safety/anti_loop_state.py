"""Anti-loop state management for skill evolution.

Prevents redundant evolutions across three trigger types:
- TOOL_DEGRADATION: Tracks which skills have been evolved for each degraded tool
- METRIC_MONITOR: Enforces minimum data points before re-evaluation
- ANALYSIS: Tracks evolution attempts per skill to prevent infinite loops

Framework provides InMemoryAntiLoopState (default, single-instance).
Business/Plane layers can provide RedisAntiLoopState for distributed scenarios.

[INPUT]
- (none)

[OUTPUT]
- AntiLoopState: Protocol for anti-loop state storage.
- InMemoryAntiLoopState: In-memory implementation of AntiLoopState.

[POS]
Anti-loop state management for skill evolution.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Protocol

logger = logging.getLogger(__name__)

__all__ = [
    "AntiLoopState",
    "InMemoryAntiLoopState",
]


class AntiLoopState(Protocol):
    """Protocol for anti-loop state storage.

    Implementations can be in-memory (default), Redis-backed (SaaS),
    or any custom storage suitable for the deployment mode.
    """

    async def is_evolution_addressed(self, trigger_type: str, key: str, skill_id: str) -> bool:
        """Check if an evolution has already been addressed.

        Args:
            trigger_type: "tool_degradation", "metric_monitor", or "analysis"
            key: Trigger-specific key (e.g., tool_key for tool_degradation)
            skill_id: Skill identifier

        Returns:
            True if this evolution has been addressed (skip to avoid redundant work)
        """
        ...

    async def mark_evolution_addressed(
        self, trigger_type: str, key: str, skill_id: str, ttl_seconds: int | None = None
    ) -> None:
        """Mark an evolution as addressed.

        Args:
            trigger_type: "tool_degradation", "metric_monitor", or "analysis"
            key: Trigger-specific key
            skill_id: Skill identifier
            ttl_seconds: Optional TTL (seconds). After expiry, the skill can be re-evolved.
                For tool_degradation: 24h default (tool may recover and degrade again)
                For metric_monitor: no TTL (data-driven via min_selections)
                For analysis: no TTL (task-specific)
        """
        ...

    async def clear_evolution_state(self, trigger_type: str, key: str) -> None:
        """Clear all addressed skills for a specific trigger key.

        Used for tool recovery: when a degraded tool recovers (no longer problematic),
        clear its addressed set so future degradations trigger fresh evaluations.

        Args:
            trigger_type: "tool_degradation", "metric_monitor", or "analysis"
            key: Trigger-specific key (e.g., tool_key)
        """
        ...

    async def get_all_keys(self, trigger_type: str) -> set[str]:
        """Get all keys currently tracked for a trigger type.

        Used for recovery detection: compare tracked keys against current problematic list.

        Args:
            trigger_type: "tool_degradation", "metric_monitor", or "analysis"

        Returns:
            Set of all keys currently tracked
        """
        ...

    async def get_skill_evolution_attempts(self, skill_id: str) -> int:
        """Get total evolution attempts for a skill (across all trigger types).

        Used to prevent infinite evolution loops: if a skill has been evolved
        N times (e.g., 10) and still fails, stop trying.

        Args:
            skill_id: Skill identifier

        Returns:
            Total evolution attempt count
        """
        ...

    async def increment_skill_evolution_attempts(self, skill_id: str) -> int:
        """Increment evolution attempt counter for a skill.

        Args:
            skill_id: Skill identifier

        Returns:
            New attempt count
        """
        ...


class InMemoryAntiLoopState:
    """In-memory implementation of AntiLoopState.

    Default framework implementation:
    - Non-persistent (lost on restart)
    - Single-instance (not shared across processes)
    - Automatic TTL-based expiry
    - Suitable for Local/Tauri single-user scenarios

    For SaaS/multi-instance scenarios, use RedisAntiLoopState (control plane).
    """

    def __init__(self) -> None:
        """Initialize in-memory anti-loop state."""
        # trigger_type → key → skill_ids
        self._state: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

        # trigger_type → key → expire_timestamp
        self._expiry: dict[str, dict[str, float]] = defaultdict(dict)

        # skill_id → evolution_attempt_count
        self._evolution_counts: dict[str, int] = {}

        self._lock = asyncio.Lock()

    async def is_evolution_addressed(self, trigger_type: str, key: str, skill_id: str) -> bool:
        """Check if an evolution has been addressed (non-expired)."""
        async with self._lock:
            if trigger_type not in self._state:
                return False
            if key not in self._state[trigger_type]:
                return False

            # Check expiry
            if self._is_expired(trigger_type, key):
                await self._clear_evolution_state_unlocked(trigger_type, key)
                return False

            return skill_id in self._state[trigger_type][key]

    async def mark_evolution_addressed(
        self, trigger_type: str, key: str, skill_id: str, ttl_seconds: int | None = None
    ) -> None:
        """Mark an evolution as addressed (with optional TTL)."""
        async with self._lock:
            self._state[trigger_type][key].add(skill_id)

            if ttl_seconds is not None and ttl_seconds > 0:
                expire_at = time.time() + ttl_seconds
                self._expiry[trigger_type][key] = expire_at

            logger.debug(
                f"Marked evolution addressed: {trigger_type}/{key}/{skill_id}"
                + (f" (TTL={ttl_seconds}s)" if ttl_seconds else "")
            )

    async def clear_evolution_state(self, trigger_type: str, key: str) -> None:
        """Clear all addressed skills for a trigger key (with lock)."""
        async with self._lock:
            await self._clear_evolution_state_unlocked(trigger_type, key)

    async def _clear_evolution_state_unlocked(self, trigger_type: str, key: str) -> None:
        """Internal: Clear state without acquiring lock (caller holds lock)."""
        if trigger_type in self._state and key in self._state[trigger_type]:
            skill_count = len(self._state[trigger_type][key])
            del self._state[trigger_type][key]
            logger.debug(f"Cleared evolution state: {trigger_type}/{key} ({skill_count} skills)")
        if trigger_type in self._expiry and key in self._expiry[trigger_type]:
            del self._expiry[trigger_type][key]

    async def get_all_keys(self, trigger_type: str) -> set[str]:
        """Get all keys currently tracked for a trigger type."""
        async with self._lock:
            if trigger_type not in self._state:
                return set()
            return set(self._state[trigger_type].keys())

    async def get_skill_evolution_attempts(self, skill_id: str) -> int:
        """Get total evolution attempts for a skill."""
        async with self._lock:
            return self._evolution_counts.get(skill_id, 0)

    async def increment_skill_evolution_attempts(self, skill_id: str) -> int:
        """Increment evolution attempt counter."""
        async with self._lock:
            current = self._evolution_counts.get(skill_id, 0)
            new_count = current + 1
            self._evolution_counts[skill_id] = new_count
            return new_count

    def _is_expired(self, trigger_type: str, key: str) -> bool:
        """Check if a trigger key has expired (internal, caller holds lock)."""
        if trigger_type not in self._expiry:
            return False
        if key not in self._expiry[trigger_type]:
            return False
        return time.time() > self._expiry[trigger_type][key]

    async def prune_expired(self) -> int:
        """Prune all expired entries (maintenance operation).

        Returns:
            Number of keys pruned
        """
        async with self._lock:
            pruned = 0
            for trigger_type in list(self._expiry.keys()):
                for key in list(self._expiry[trigger_type].keys()):
                    if self._is_expired(trigger_type, key):
                        await self._clear_evolution_state_unlocked(trigger_type, key)
                        pruned += 1
            return pruned
