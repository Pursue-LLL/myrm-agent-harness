"""Long-session automatic rolling archive engine.

Partitions long-running conversations into sealed historical volumes with
distilled milestone summaries, relieving executing stacks of excessive turn
payloads while preserving long-term episodic continuity.

[OUTPUT]
- LongSessionRollingArchiver: Automatic multi-volume archiver for extended sessions.

[INPUT]
- __future__
- asyncio
- time
- uuid

[OUTPUT]
- LongSessionRollingArchiver

[POS]
Long-session automatic rolling archive engine.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from myrm_agent_harness.runtime.survival.desktop_watchdog_types import (
    ArchiveVolume,
    SessionTurn,
)

_DEFAULT_MAX_TURNS_PER_VOLUME: int = 100
_DEFAULT_ARCHIVE_TRIGGER_THRESHOLD: int = 120


class LongSessionRollingArchiver:
    """Partitions and archives extended conversations into compact historical volumes."""

    def __init__(
        self,
        *,
        max_turns_per_volume: int = _DEFAULT_MAX_TURNS_PER_VOLUME,
        trigger_threshold: int = _DEFAULT_ARCHIVE_TRIGGER_THRESHOLD,
    ) -> None:
        self.max_turns_per_volume: int = max(10, max_turns_per_volume)
        self.trigger_threshold: int = max(
            self.max_turns_per_volume + 1, trigger_threshold
        )
        self._volumes: dict[str, list[ArchiveVolume]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    @staticmethod
    def _synthesize_milestone_summary(turns: list[SessionTurn]) -> str:
        """Distill key decisions, queries, and final responses into a milestone summary."""
        if not turns:
            return "No previous milestones recorded."

        first_query = turns[0].user_query
        last_turn = turns[-1]
        count = len(turns)

        return (
            f"Milestone Archive: {count} historical turns archived. "
            f"Initiated with query: '{first_query[:80]}'. "
            f"Latest settlement: '{last_turn.agent_response[:100]}'."
        )

    async def maybe_archive_session(
        self,
        session_id: str,
        turns: list[SessionTurn],
    ) -> tuple[ArchiveVolume | None, list[SessionTurn]]:
        """Evaluate if session exceeds threshold and archive oldest volume slice.

        Returns:
            tuple[ArchiveVolume | None, list[SessionTurn]]: The generated ArchiveVolume
            (or None if not triggered) and the remaining active turns.
        """
        if len(turns) < self.trigger_threshold:
            return None, turns

        async with self._lock:
            to_archive = turns[: self.max_turns_per_volume]
            remaining = turns[self.max_turns_per_volume :]

            session_vols = self._volumes.setdefault(session_id, [])
            vol_idx = len(session_vols) + 1
            vol_id = f"vol_{session_id}_{vol_idx}_{uuid.uuid4().hex[:8]}"

            summary = self._synthesize_milestone_summary(to_archive)

            volume = ArchiveVolume(
                volume_id=vol_id,
                session_id=session_id,
                volume_index=vol_idx,
                start_turn_index=to_archive[0].turn_index,
                end_turn_index=to_archive[-1].turn_index,
                milestone_summary=summary,
                retained_turns_count=len(to_archive),
                archived_at=time.time(),
            )

            session_vols.append(volume)
            return volume, remaining

    async def list_volumes(self, session_id: str) -> list[ArchiveVolume]:
        """List sealed archive volumes for a session, oldest first."""
        async with self._lock:
            return list(self._volumes.get(session_id, []))

    async def get_volume(self, volume_id: str) -> ArchiveVolume | None:
        """Lookup an archive volume by its identifier."""
        async with self._lock:
            for vols in self._volumes.values():
                for v in vols:
                    if v.volume_id == volume_id:
                        return v
            return None
