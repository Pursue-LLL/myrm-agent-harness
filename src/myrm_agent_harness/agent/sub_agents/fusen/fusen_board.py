"""Thread-safe in-memory Fusen Shared Sticky-Note Board engine (Item 63).

[INPUT]
- Subagent state notifications (blockers, ready-for-review signals, cache hints).

[OUTPUT]
- FusenNote records, state updates, blocker queries, and auto-expiration cleanup.

[POS]
- Harness shared state board eliminating LLM token overhead in multi-agent swarm coordination.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Final

from .types import (
    FusenBlockerSummary,
    FusenCategory,
    FusenNote,
    NoteStatus,
)

logger: Final = logging.getLogger(__name__)


class FusenSharedBoard:
    """Decentralized, lightweight in-memory shared state board for agent teams."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._notes: dict[str, FusenNote] = {}

    def clear(self) -> None:
        """Reset the shared sticky-note board."""
        with self._lock:
            self._notes.clear()

    def post_note(
        self,
        note_id: str,
        session_id: str,
        author_agent_id: str,
        category: FusenCategory,
        tag: str,
        content: str = "",
        metadata: dict[str, str] | None = None,
        ttl_seconds: float | None = None,
    ) -> FusenNote:
        """Post a new lightweight sticky note to the shared board."""
        now = time.time()
        note = FusenNote(
            note_id=note_id,
            session_id=session_id,
            author_agent_id=author_agent_id,
            category=category,
            tag=tag,
            content=content,
            metadata=dict(metadata) if metadata else {},
            status=NoteStatus.ACTIVE,
            resolution_note=None,
            ttl_seconds=ttl_seconds,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._notes[note_id] = note
            logger.info(
                "Agent '%s' posted Fusen note %s [%s] '%s'",
                author_agent_id,
                note_id,
                category.value,
                tag,
            )
            return note

    def resolve_note(
        self,
        note_id: str,
        resolution_note: str = "",
    ) -> FusenNote:
        """Mark an active sticky note as resolved (e.g. blocker cleared, PR reviewed)."""
        with self._lock:
            note = self._notes.get(note_id)
            if note is None:
                msg = f"Fusen note '{note_id}' not found."
                raise KeyError(msg)

            note.status = NoteStatus.RESOLVED
            note.resolution_note = resolution_note
            note.updated_at = time.time()
            logger.info("Fusen note %s resolved: '%s'", note_id, resolution_note)
            return note

    def get_note(self, note_id: str) -> FusenNote | None:
        """Retrieve a note by its unique identifier."""
        with self._lock:
            return self._notes.get(note_id)

    def list_notes(
        self,
        session_id: str | None = None,
        category: FusenCategory | None = None,
        tag_prefix: str | None = None,
        include_resolved: bool = False,
    ) -> list[FusenNote]:
        """Query sticky notes matching filter criteria."""
        now = time.time()
        with self._lock:
            results: list[FusenNote] = []
            for note in self._notes.values():
                # Filter out expired notes
                if note.is_expired(now):
                    continue
                # Session filter
                if session_id is not None and note.session_id != session_id:
                    continue
                # Category filter
                if category is not None and note.category != category:
                    continue
                # Status filter
                if not include_resolved and note.status != NoteStatus.ACTIVE:
                    continue
                # Tag prefix filter
                if tag_prefix is not None and not note.tag.startswith(tag_prefix):
                    continue
                results.append(note)

            return sorted(results, key=lambda n: n.created_at, reverse=True)

    def check_blockers(
        self,
        session_id: str,
        target_agent_id: str | None = None,
    ) -> FusenBlockerSummary:
        """Rapidly check active blockers in sub-millisecond time without LLM calls."""
        now = time.time()
        with self._lock:
            active_blockers: list[FusenNote] = []
            for note in self._notes.values():
                if note.session_id != session_id:
                    continue
                if note.status != NoteStatus.ACTIVE:
                    continue
                if note.is_expired(now):
                    continue
                if note.category != FusenCategory.BLOCKER:
                    continue

                # If target_agent_id is specified, check if note affects this agent or is global
                affected = note.metadata.get("target_agent_id")
                if target_agent_id and affected and affected != target_agent_id:
                    continue

                active_blockers.append(note)

            return FusenBlockerSummary(
                is_blocked=len(active_blockers) > 0,
                blocker_count=len(active_blockers),
                blockers=active_blockers,
                active_tags=[b.tag for b in active_blockers],
            )

    def cleanup_expired(self, now: float | None = None) -> int:
        """Prune all expired notes based on their individual TTLs."""
        current_time = now if now is not None else time.time()
        with self._lock:
            expired_ids = [
                note_id
                for note_id, note in self._notes.items()
                if note.is_expired(current_time)
            ]
            for nid in expired_ids:
                del self._notes[nid]

            if expired_ids:
                logger.info("Pruned %d expired Fusen sticky notes", len(expired_ids))
            return len(expired_ids)
