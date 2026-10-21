"""[INPUT] DispatchJournalEntry parameters and dispatch transaction identifiers.
[OUTPUT] DurableDispatchJournal ledger managing append-only deterministic sequence logs.
[POS] Ledger storage engine for Hermes Fabric remote dispatch journals.
"""

from __future__ import annotations

import hashlib
import logging

from .types import DispatchJournalEntry, JournalEntryType

logger = logging.getLogger(__name__)


class DurableDispatchJournal:
    """In-memory append-only journal store with monotonically increasing sequence numbers.

    Provides deterministic auditing and crash-recovery ledger for coordinator and peer nodes.
    """

    def __init__(self) -> None:
        self._journals: dict[str, list[DispatchJournalEntry]] = {}

    def append_entry(
        self,
        dispatch_id: str,
        entry_type: JournalEntryType,
        payload_data: str = "",
        metadata: dict[str, str] | None = None,
    ) -> DispatchJournalEntry:
        """Append a new monotonic sequence entry to the target dispatch journal."""
        if dispatch_id not in self._journals:
            self._journals[dispatch_id] = []

        seq = len(self._journals[dispatch_id]) + 1
        digest = hashlib.sha256(payload_data.encode("utf-8")).hexdigest()

        entry = DispatchJournalEntry(
            dispatch_id=dispatch_id,
            seq=seq,
            entry_type=entry_type,
            payload_hash=digest,
            metadata=metadata or {},
        )
        self._journals[dispatch_id].append(entry)
        logger.debug(
            "Appended journal entry %s seq=%d for dispatch %s",
            entry_type.value,
            seq,
            dispatch_id,
        )
        return entry

    def get_journal(self, dispatch_id: str) -> list[DispatchJournalEntry]:
        """Retrieve full ordered journal entries for a given dispatch transaction."""
        return list(self._journals.get(dispatch_id, []))

    def get_latest_entry(self, dispatch_id: str) -> DispatchJournalEntry | None:
        """Fetch the latest committed journal record for state inspection."""
        entries = self._journals.get(dispatch_id, [])
        if entries:
            return entries[-1]
        return None

    def list_all_dispatches(self) -> list[str]:
        """List all dispatch identifiers recorded in the ledger."""
        return list(self._journals.keys())

    def clear_dispatch(self, dispatch_id: str) -> bool:
        """Purge records for a settled dispatch transaction."""
        if dispatch_id in self._journals:
            del self._journals[dispatch_id]
            return True
        return False
