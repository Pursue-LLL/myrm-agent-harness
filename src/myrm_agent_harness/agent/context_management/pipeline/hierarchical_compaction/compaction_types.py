# ============================================================================
# Hierarchical Four-Stage Context Compaction Types (Item 154)
# Strict typed contracts for 4-stage context compaction: tool result trimming,
# segmented history summary, core asset protection invariants, and view derivation.
# ============================================================================

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CompactionStage(StrEnum):
    """Execution stages of the hierarchical compaction pipeline."""

    STAGE_1_TOOL_TRIM = "stage_1_tool_trim"
    STAGE_2_SEGMENTED_HISTORY = "stage_2_segmented_history"
    STAGE_3_CORE_ASSET_PROTECTION = "stage_3_core_asset_protection"
    STAGE_4_VIEW_DERIVATION = "stage_4_view_derivation"


class MessageRole(StrEnum):
    """Semantic role of conversation messages."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class HierarchicalCompactionConfig:
    """Config governing four-stage budget allocation and invariants."""

    max_context_chars: int = 12000
    tool_result_budget_chars: int = 600
    tool_result_head_lines: int = 5
    tool_result_tail_lines: int = 5
    keep_recent_turns: int = 3
    protect_system_prompts: bool = True
    protect_pending_goals: bool = True


@dataclass(slots=True)
class PipelineMessage:
    """Message entity moving through the compaction pipeline."""

    message_id: str
    role: MessageRole
    content: str
    tool_name: str | None = None
    is_pinned: bool = False
    is_system: bool = False
    is_goal_state: bool = False

    def clone(self) -> PipelineMessage:
        """Deep clones the message to ensure immutability of underlying storage."""
        return PipelineMessage(
            message_id=self.message_id,
            role=self.role,
            content=self.content,
            tool_name=self.tool_name,
            is_pinned=self.is_pinned,
            is_system=self.is_system,
            is_goal_state=self.is_goal_state,
        )

    def to_dict(self) -> dict[str, str | bool | None]:
        """Serializes pipeline message to dictionary."""
        return {
            "message_id": self.message_id,
            "role": str(self.role),
            "content": self.content,
            "tool_name": self.tool_name,
            "is_pinned": self.is_pinned,
            "is_system": self.is_system,
            "is_goal_state": self.is_goal_state,
        }


@dataclass(slots=True)
class TrimmedToolResult:
    """Audit entry recording a trimmed tool execution output."""

    message_id: str
    tool_name: str
    original_chars: int
    trimmed_chars: int
    restore_hint: str

    def to_dict(self) -> dict[str, str | int]:
        """Serializes trimmed tool entry to dictionary."""
        return {
            "message_id": self.message_id,
            "tool_name": self.tool_name,
            "original_chars": self.original_chars,
            "trimmed_chars": self.trimmed_chars,
            "restore_hint": self.restore_hint,
        }


@dataclass(slots=True)
class CompactionMetrics:
    """Telemetry metrics tracking compression ratio and applied stages."""

    initial_chars: int
    final_chars: int
    chars_saved: int
    reduction_ratio: float
    stages_applied: list[CompactionStage] = field(default_factory=list)
    trimmed_tools_count: int = 0
    compressed_turns_count: int = 0

    def to_dict(self) -> dict[str, int | float | list[str]]:
        """Serializes metrics to dictionary."""
        return {
            "initial_chars": self.initial_chars,
            "final_chars": self.final_chars,
            "chars_saved": self.chars_saved,
            "reduction_ratio": self.reduction_ratio,
            "stages_applied": [str(s) for s in self.stages_applied],
            "trimmed_tools_count": self.trimmed_tools_count,
            "compressed_turns_count": self.compressed_turns_count,
        }


@dataclass(slots=True)
class DerivedContextView:
    """Memory-only derived context view feedable to LLM without touching disk storage."""

    derived_messages: list[PipelineMessage]
    metrics: CompactionMetrics
    summary_block: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serializes derived view to dictionary."""
        return {
            "derived_messages": [m.to_dict() for m in self.derived_messages],
            "metrics": self.metrics.to_dict(),
            "summary_block": self.summary_block,
        }
