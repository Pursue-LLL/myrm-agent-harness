"""Types and data contracts for tool-safe compaction boundaries and file manifests transmission.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- MessageRole: Allowed message role names in chat sequences.
- CutPointSafetyKind: Safety evaluation classification for a candidate compaction cut point.
- FileManifests: Immutable records of read and modified file paths touched in compressed turns.
- CutPointEvaluation: Detailed inspection result of a single cut point index.
- SafeCompactionResult: Final compacted context package with preserved tail and file manifests.

[POS]
Data contracts for safe cut-point selection, file manifests extraction, and atomic tool compaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MessageRole(str, Enum):
    """Allowed message role names in chat sequences."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class CutPointSafetyKind(str, Enum):
    """Safety evaluation classification for a candidate compaction cut point."""

    SAFE_USER_TURN = "safe_user_turn"  # Cut at the start of a user message
    SAFE_ASSISTANT_CLEAN = "safe_assistant_clean"  # Cut at assistant message without dangling tool calls
    UNSAFE_TOOL_RESULT = "unsafe_tool_result"  # Invalid cut: would separate tool_call from tool_result
    UNSAFE_ORPHAN_CALL = "unsafe_orphan_call"  # Invalid cut: tool_call left with no tool_result
    OUT_OF_BOUNDS = "out_of_bounds"


@dataclass(frozen=True, slots=True)
class FileManifests:
    """Immutable records of read and modified file paths touched in compressed turns.

    Preserves awareness of workspace state across dozens of compaction cycles,
    preventing file re-read loops and conflicting overwrites.
    """

    read_files: tuple[str, ...] = field(default_factory=tuple)
    modified_files: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_touched_files(self) -> int:
        """Count total unique files involved in either read or write operations."""
        return len(set(self.read_files) | set(self.modified_files))


@dataclass(frozen=True, slots=True)
class CutPointEvaluation:
    """Detailed inspection result of a single cut point index."""

    index: int
    safety: CutPointSafetyKind
    is_valid: bool
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SafeCompactionResult:
    """Final compacted context package with preserved tail and file manifests.

    Guarantees 100% validity for model API invocations by strictly adhering
    to atomic tool call boundaries.
    """

    cut_point_index: int
    compressed_messages_count: int
    preserved_messages_count: int
    file_manifests: FileManifests
    compaction_summary: str
    compacted_context: tuple[dict[str, str], ...]
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
