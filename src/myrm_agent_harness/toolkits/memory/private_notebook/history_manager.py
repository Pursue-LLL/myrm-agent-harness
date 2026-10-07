"""[POS]: src/myrm_agent_harness/toolkits/memory/private_notebook/history_manager.py
[INPUT]: Context window identifiers, turn contents, author roles, and history queries.
[OUTPUT]: HistoryContextManager indexing and retrieving archived cross-context execution logs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from .models import HistoryContextItem, HistoryEntryItem


class HistoryContextManager:
    """Thread-safe catalog indexing multi-window historical agent interactions and tool invocations."""

    def __init__(self) -> None:
        self._lock = Lock()
        # context_id -> HistoryContextItem
        self._contexts: dict[str, HistoryContextItem] = {}
        # context_id -> list of HistoryEntryItem
        self._entries: dict[str, list[HistoryEntryItem]] = {}

    def record_entry(
        self,
        context_id: str,
        role: str,
        content: str,
        *,
        context_title: str | None = None,
    ) -> HistoryEntryItem:
        """Appends a new turn message into the specified context window history."""
        with self._lock:
            if context_id not in self._contexts:
                self._contexts[context_id] = HistoryContextItem(
                    context_id=context_id,
                    title=context_title or f"Context {context_id}",
                    turn_count=0,
                    created_at=datetime.now(UTC),
                )
                self._entries[context_id] = []

            turn_idx = len(self._entries[context_id])
            entry = HistoryEntryItem(
                context_id=context_id,
                turn_index=turn_idx,
                role=role,
                content=content,
                created_at=datetime.now(UTC),
            )
            self._entries[context_id].append(entry)

            # Update turn count on context summary
            ctx = self._contexts[context_id]
            self._contexts[context_id] = HistoryContextItem(
                context_id=ctx.context_id,
                title=ctx.title,
                turn_count=turn_idx + 1,
                created_at=ctx.created_at,
            )
            return entry

    def list_contexts(self) -> list[HistoryContextItem]:
        """Lists all archived historical context windows in reverse chronological order."""
        with self._lock:
            contexts = list(self._contexts.values())
            contexts.sort(key=lambda c: c.created_at, reverse=True)
            return contexts

    def list_entries(self, context_id: str) -> list[HistoryEntryItem]:
        """Lists all chronological turns recorded under a specific context window."""
        with self._lock:
            return list(self._entries.get(context_id, []))

    def read_entry(self, context_id: str, turn_index: int) -> HistoryEntryItem | None:
        """Retrieves a specific historical turn entry by context ID and turn index."""
        with self._lock:
            turns = self._entries.get(context_id, [])
            if 0 <= turn_index < len(turns):
                return turns[turn_index]
            return None

    def search_history(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[HistoryEntryItem]:
        """Performs case-insensitive token search across all archived historical context entries."""
        terms = [t.lower() for t in query.strip().split() if t.strip()]
        if not terms:
            return []

        hits: list[tuple[int, HistoryEntryItem]] = []
        with self._lock:
            for turns in self._entries.values():
                for entry in turns:
                    content_lower = entry.content.lower()
                    matches = sum(1 for term in terms if term in content_lower)
                    if matches > 0:
                        hits.append((matches, entry))

        # Sort by match frequency, then recency
        hits.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [entry for _, entry in hits[:max_results]]
