"""Types for append-only compaction ledger and atomic tool-pair cut-point engine.

Defines schemas for immutable log entries, compaction markers, atomic cut-point
resolutions, and assembled LLM context views.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ContextEntryRole(StrEnum):
    """Role classification for immutable context log entries."""

    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True)
class ContextLogEntry:
    """Immutable entry in the sequential context log."""

    entry_id: str
    role: ContextEntryRole
    content: str
    tool_call_id: str | None = None
    token_estimate: int = 10
    turn_id: int = 0
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CompactionEntry:
    """Immutable compaction marker appended to the log stream."""

    compaction_id: str
    summary: str
    first_kept_entry_id: str
    tokens_before: int
    tokens_after: int
    read_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    is_split_turn: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class CutPointResolution:
    """Resolution details of an atomic cut-point calculation."""

    cut_index: int
    first_kept_entry_id: str
    is_split_turn: bool
    retained_tokens: int
    adjustment_reason: str


@dataclass(frozen=True)
class CompactedContextAssembly:
    """Complete context package prepared for model inference."""

    system_prompt: str
    active_summary: str | None
    retained_entries: list[ContextLogEntry]
    total_assembled_tokens: int
    has_orphaned_tool_pairs: bool = False
