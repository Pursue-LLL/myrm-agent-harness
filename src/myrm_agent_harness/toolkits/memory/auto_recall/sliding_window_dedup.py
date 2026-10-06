# [POS] toolkits/memory/auto_recall/sliding_window_dedup.py
# [INPUT] types.RecallCandidate
# [OUTPUT] SlidingWindowDedupGate

"""Sliding window deduplication gate to suppress redundant memory injection across turns."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .types import RecallCandidate


@dataclass
class _TurnInjectionRecord:
    """Records the memory IDs injected during a specific turn."""

    turn_index: int
    injected_ids: set[str] = field(default_factory=set)


class SlidingWindowDedupGate:
    """Maintains a rolling window of recent turns to suppress duplicate memory recalls."""

    def __init__(self, window_turns: int = 5) -> None:
        self._window_turns = max(1, window_turns)
        # Maps session_id -> deque of recent turn records
        self._sessions: dict[str, deque[_TurnInjectionRecord]] = {}

    def filter_unseen(
        self,
        session_id: str,
        candidates: list[RecallCandidate],
    ) -> list[RecallCandidate]:
        """Filter out candidates whose memory_id was already injected within the recent window."""
        if not candidates or session_id not in self._sessions:
            return candidates

        recently_injected = self.get_recent_injected(session_id)
        if not recently_injected:
            return candidates

        return [c for c in candidates if c.memory_id not in recently_injected]

    def record_injected(
        self,
        session_id: str,
        injected_ids: list[str],
        turn_index: int,
    ) -> None:
        """Record the memory IDs injected in the given turn, evicting records outside window."""
        if session_id not in self._sessions:
            self._sessions[session_id] = deque(maxlen=self._window_turns)

        window_queue = self._sessions[session_id]
        window_queue.append(_TurnInjectionRecord(turn_index=turn_index, injected_ids=set(injected_ids)))

    def get_recent_injected(self, session_id: str) -> set[str]:
        """Return the unified set of all memory IDs injected across the active sliding window."""
        window_queue = self._sessions.get(session_id)
        if not window_queue:
            return set()

        aggregated: set[str] = set()
        for rec in window_queue:
            aggregated.update(rec.injected_ids)
        return aggregated

    def clear_session(self, session_id: str) -> None:
        """Purge sliding window state for a specific session upon session termination."""
        self._sessions.pop(session_id, None)

    def get_session_stats(self, session_id: str) -> dict[str, int]:
        """Return audit stats for the current session window."""
        window_queue = self._sessions.get(session_id)
        if not window_queue:
            return {"active_window_turns": 0, "total_suppressed_id_count": 0}

        return {
            "active_window_turns": len(window_queue),
            "total_suppressed_id_count": len(self.get_recent_injected(session_id)),
        }
