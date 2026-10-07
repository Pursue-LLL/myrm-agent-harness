"""Strongly typed contracts for Auto-Compact Fallback Buffer and Team Notebook Suite (Item 223).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- BufferWatermarkState: Operational state indicating distance to physical context boundary.
- BufferWatermarkSnapshot: Real-time token headroom and fallback trigger decision.
- TeamNotebookEntry: Atomic progress note authored by an individual agent worker or subagent.
- TeamNotebookSnapshot: Consolidated multi-agent workspace scratchpad for seamless task handoff.
- CompactionConsequenceAlert: Transparent user banner notifying irreversible compaction details.
- FallbackBufferConfig: Tunable buffer sizes, physical window limits, and fallback prompt templates.

[POS]
- Implements OpenAI Codex auto_compact_fallback_buffer_tokens guard preventing fatal context OOMs
- while facilitating multi-agent task relay through shared workspace scratchpad notes.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class BufferWatermarkState(str, enum.Enum):
    """Headroom proximity to physical context limit."""

    SAFE = "safe"
    WARNING_APPROACHING = "warning_approaching"
    FALLBACK_TRIGGERED = "fallback_triggered"
    CRITICAL_EXHAUSTED = "critical_exhausted"


@dataclass(frozen=True, slots=True)
class BufferWatermarkSnapshot:
    """Headroom telemetry assessing physical context limit vs. reserved fallback safety buffer."""

    current_tokens: int
    context_window_limit: int
    fallback_buffer_tokens: int
    safe_ceiling_tokens: int
    watermark_state: BufferWatermarkState
    utilization_ratio: float
    remaining_buffer_tokens: int

    def to_dict(self) -> dict[str, object]:
        """Serializes watermark snapshot to dictionary."""
        return {
            "current_tokens": self.current_tokens,
            "context_window_limit": self.context_window_limit,
            "fallback_buffer_tokens": self.fallback_buffer_tokens,
            "safe_ceiling_tokens": self.safe_ceiling_tokens,
            "watermark_state": self.watermark_state.value,
            "utilization_ratio": self.utilization_ratio,
            "remaining_buffer_tokens": self.remaining_buffer_tokens,
        }


@dataclass(slots=True)
class TeamNotebookEntry:
    """Atomic task checkpoint written by a subagent for sequential multi-agent handoff."""

    note_id: str
    session_id: str
    agent_role: str
    section_title: str
    content: str
    subtask_index: int = 0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """Serializes notebook entry to dictionary."""
        return {
            "note_id": self.note_id,
            "session_id": self.session_id,
            "agent_role": self.agent_role,
            "section_title": self.section_title,
            "content": self.content,
            "subtask_index": self.subtask_index,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TeamNotebookSnapshot:
    """Compiled view of the team scratchpad allowing subsequent workers to pick up instantly."""

    session_id: str
    total_notes: int
    compiled_markdown: str
    last_updated_by: str

    def to_dict(self) -> dict[str, object]:
        """Serializes team notebook snapshot to dictionary."""
        return {
            "session_id": self.session_id,
            "total_notes": self.total_notes,
            "compiled_markdown": self.compiled_markdown,
            "last_updated_by": self.last_updated_by,
        }


@dataclass(frozen=True, slots=True)
class CompactionConsequenceAlert:
    """Human-in-the-loop notification detailing compaction consequences and archive refs."""

    alert_id: str
    session_id: str
    trigger_tokens: int
    compacted_turn_range: str
    preserved_decision_summary: str
    archived_ledger_ref: str
    user_banner_text: str

    def to_dict(self) -> dict[str, object]:
        """Serializes compaction alert to dictionary."""
        return {
            "alert_id": self.alert_id,
            "session_id": self.session_id,
            "trigger_tokens": self.trigger_tokens,
            "compacted_turn_range": self.compacted_turn_range,
            "preserved_decision_summary": self.preserved_decision_summary,
            "archived_ledger_ref": self.archived_ledger_ref,
            "user_banner_text": self.user_banner_text,
        }


@dataclass(frozen=True, slots=True)
class FallbackBufferConfig:
    """Tunable thresholds for auto-compact reserve buffer and team notebook management."""

    context_window_limit: int = 128000
    fallback_buffer_tokens: int = 8000
    warning_threshold_ratio: float = 0.85
    default_fallback_prompt: str = (
        "You are performing an emergency fallback compaction. "
        "Extract core conclusions, discard raw outputs, and preserve key file references."
    )
