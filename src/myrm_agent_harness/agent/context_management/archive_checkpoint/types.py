"""Archive checkpoint DTOs and constants."""

from __future__ import annotations

from dataclasses import dataclass

ARCHIVE_CHECKPOINT_EVENT_TYPE = "archive_checkpoint"
ARCHIVE_CHECKPOINT_METADATA_KEY = "archive_path"


@dataclass(frozen=True, slots=True)
class ArchiveCheckpointRecord:
    """Persisted archive summary checkpoint."""

    memory_id: str
    tool_name: str
    archive_path: str
    summary: str
    chat_id: str
    tool_call_id: str | None = None
