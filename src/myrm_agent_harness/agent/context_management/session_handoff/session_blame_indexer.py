"""Indexer mapping source code lines back to originating session turns and prompt intents."""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional

from .session_handoff_types import LineBlameEntry, LineBlameLookupResult


class SessionBlameIndexer:
    """Maintains reverse provenance mapping from code file lines to agent sessions."""

    def __init__(self) -> None:
        self._entries_by_file: Dict[str, List[LineBlameEntry]] = {}

    def record_code_generation(
        self,
        file_path: str,
        start_line: int,
        end_line: int,
        session_id: str,
        turn_id: int,
        prompt_intent: str,
        timestamp_iso: str,
    ) -> LineBlameEntry:
        """Register a range of lines produced by a specific session turn."""
        if start_line > end_line or start_line <= 0:
            raise ValueError(f"Invalid line range: {start_line}-{end_line}")

        intent_digest = hashlib.sha256(prompt_intent.strip().encode("utf-8")).hexdigest()[:12]
        entry = LineBlameEntry(
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            session_id=session_id,
            turn_id=turn_id,
            prompt_intent_digest=intent_digest,
            timestamp_iso=timestamp_iso,
        )

        if file_path not in self._entries_by_file:
            self._entries_by_file[file_path] = []

        # Overwrite or append entries (latest wins on overlap)
        self._entries_by_file[file_path].append(entry)
        return entry

    def blame_line(self, file_path: str, line_number: int) -> LineBlameLookupResult:
        """Lookup the originating session and turn for a given line of code."""
        entries = self._entries_by_file.get(file_path, [])
        # Search in reverse order to find latest modification first
        for entry in reversed(entries):
            if entry.start_line <= line_number <= entry.end_line:
                return LineBlameLookupResult(
                    file_path=file_path,
                    line_number=line_number,
                    found=True,
                    entry=entry,
                )

        return LineBlameLookupResult(
            file_path=file_path,
            line_number=line_number,
            found=False,
            entry=None,
        )

    def get_file_blame_entries(self, file_path: str) -> List[LineBlameEntry]:
        """Return all blame entries recorded for a file."""
        return list(self._entries_by_file.get(file_path, []))
