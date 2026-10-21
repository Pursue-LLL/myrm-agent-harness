"""Thread-safe ring buffer for streaming subagent live transcripts.

[INPUT]
- types.SupervisionTranscriptEntry

[OUTPUT]
- SubagentTranscriptBuffer

[POS]
myrm_agent_harness/agent/sub_agents/supervision_hub/transcript_buffer.py
"""

from __future__ import annotations

import collections
import threading
from datetime import UTC, datetime
from typing import Literal

from myrm_agent_harness.agent.sub_agents.supervision_hub.types import (
    SupervisionTranscriptEntry,
)


class SubagentTranscriptBuffer:
    """Thread-safe bounded ring buffer holding live execution traces for a single subagent."""

    def __init__(self, task_id: str, max_entries: int = 100) -> None:
        self.task_id: str = task_id
        self.max_entries: int = max_entries
        self._entries: collections.deque[SupervisionTranscriptEntry] = collections.deque(
            maxlen=max_entries
        )
        self._lock: threading.Lock = threading.Lock()
        self._counter: int = 0

    def append_entry(
        self,
        tool_name: str,
        input_summary: str,
        output_summary: str,
        level: Literal["info", "warn", "error"] = "info",
        duration_ms: int | None = None,
    ) -> SupervisionTranscriptEntry:
        """Append a new transcript entry in thread-safe fashion."""
        with self._lock:
            self._counter += 1
            entry = SupervisionTranscriptEntry(
                entry_id=f"{self.task_id}-tr-{self._counter}",
                timestamp=datetime.now(UTC).isoformat(),
                tool_name=tool_name,
                input_summary=input_summary[:500],
                output_summary=output_summary[:1000],
                level=level,
                duration_ms=duration_ms,
            )
            self._entries.append(entry)
            return entry

    def get_entries(self, limit: int | None = None) -> list[SupervisionTranscriptEntry]:
        """Return a snapshot copy of current transcript entries."""
        with self._lock:
            snapshot = list(self._entries)
            if limit is not None and limit > 0:
                return snapshot[-limit:]
            return snapshot

    def clear(self) -> None:
        """Clear all entries in the buffer."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
