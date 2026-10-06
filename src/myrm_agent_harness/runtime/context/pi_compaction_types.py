"""Type definitions for Pi Agent-style progressive context compaction,
branch summarization, and cumulative file tracker engine.

Reference: Mario Zechner Pi Agent (@earendil-works/pi-agent-core & packages/coding-agent/src/core/compaction).
Strict 0 Any, immutable frozen structures, protocol-safe cut points.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .surface_projection_types import ProjectedMessage


class CompactionTriggerKind(StrEnum):
    """Enumeration of triggers initiating context compaction."""

    THRESHOLD = "threshold"
    OVERFLOW = "overflow"
    MANUAL = "manual"
    SPLIT_TURN = "split_turn"


@dataclass(frozen=True)
class CutPointResult:
    """Protocol-safe cut point selection result."""

    first_kept_index: int
    turn_start_index: int
    is_split_turn: bool
    kept_tokens: int
    first_kept_entry_id: str


@dataclass(frozen=True)
class CumulativeFileRecord:
    """Cumulative set of files read and modified across all compaction cycles."""

    read_files: tuple[str, ...] = ()
    modified_files: tuple[str, ...] = ()

    def render_xml_block(self) -> str:
        """Render structural XML block for prompt injection."""
        lines: list[str] = []
        if self.read_files:
            lines.append("<read-files>")
            for f in sorted(self.read_files):
                lines.append(f"  <file>{f}</file>")
            lines.append("</read-files>")

        if self.modified_files:
            lines.append("<modified-files>")
            for f in sorted(self.modified_files):
                lines.append(f"  <file>{f}</file>")
            lines.append("</modified-files>")

        return "\n".join(lines)


@dataclass(frozen=True)
class RollingStructuredSummary:
    """Structured rolling summary sections preserving causality."""

    goal: str
    constraints: str
    progress_done: tuple[str, ...]
    progress_in_progress: tuple[str, ...]
    key_decisions: tuple[str, ...]
    next_steps: tuple[str, ...]
    critical_context: str
    cumulative_files: CumulativeFileRecord
    focus_directive: str = ""

    def render_markdown(self) -> str:
        """Render standardized markdown summary with XML file blocks."""
        sections = [
            "## Goal\n" + (self.goal or "N/A"),
            "## Constraints & Preferences\n" + (self.constraints or "N/A"),
            "## Progress\n"
            + "### Done\n"
            + ("\n".join(f"- {d}" for d in self.progress_done) if self.progress_done else "- None")
            + "\n### In Progress\n"
            + ("\n".join(f"- {p}" for p in self.progress_in_progress) if self.progress_in_progress else "- None"),
            "## Key Decisions\n"
            + ("\n".join(f"- {kd}" for kd in self.key_decisions) if self.key_decisions else "- None"),
            "## Next Steps\n"
            + ("\n".join(f"- {ns}" for ns in self.next_steps) if self.next_steps else "- None"),
            "## Critical Context\n" + (self.critical_context or "N/A"),
        ]
        if self.focus_directive:
            sections.append(f"## Additional Focus\n{self.focus_directive}")

        files_xml = self.cumulative_files.render_xml_block()
        if files_xml:
            sections.append(files_xml)

        return "\n\n".join(sections)


@dataclass(frozen=True)
class OverflowDetectionResult:
    """Detailed result of provider context overflow detection."""

    is_overflow: bool
    vendor: str
    matched_pattern: str
    is_silent_truncation: bool = False
    prompt_budget: int = 0
    server_tokens: int = 0
    diagnostic_hint: str = ""


@dataclass(frozen=True)
class PiCompactionConfig:
    """Configuration governing Pi-style progressive compaction."""

    context_window: int = 128000
    reserve_tokens: int = 16384
    keep_recent_tokens: int = 20000
    focus_directive: str = ""
    allow_split_turn: bool = True
    enabled: bool = True


@dataclass(frozen=True)
class PiCompactionResult:
    """Outcome of progressive compaction."""

    summary_text: str
    cut_point: CutPointResult
    cumulative_files: CumulativeFileRecord
    tokens_before: int
    tokens_after: int
    projected_messages: tuple[ProjectedMessage, ...]
    is_split_turn: bool
