"""Package facade for hierarchical compaction.

[INPUT]
- agent.context_management.pipeline.hierarchical_compaction.compaction_types::CompactionMetrics,
  CompactionStage, DerivedContextView, HierarchicalCompactionConfig, MessageRole, PipelineMessage,
  TrimmedToolResult (POS: Types and models for compaction.)
-
  agent.context_management.pipeline.hierarchical_compaction.hierarchical_four_stage_compactor::HierarchicalFourStageCompactor
  (POS: Orchestrates four-stage hierarchical context compaction.)

[OUTPUT]
- Re-exports: CompactionMetrics, CompactionStage, DerivedContextView, HierarchicalCompactionConfig,
  HierarchicalFourStageCompactor, MessageRole, PipelineMessage, TrimmedToolResult

[POS]
Package facade for hierarchical compaction.
"""

# ============================================================================
# Hierarchical Four-Stage Context Compaction Subpackage (Item 154)
# ============================================================================

from .compaction_types import (
    CompactionMetrics,
    CompactionStage,
    DerivedContextView,
    HierarchicalCompactionConfig,
    MessageRole,
    PipelineMessage,
    TrimmedToolResult,
)
from .hierarchical_four_stage_compactor import HierarchicalFourStageCompactor

__all__ = [
    "CompactionMetrics",
    "CompactionStage",
    "DerivedContextView",
    "HierarchicalCompactionConfig",
    "HierarchicalFourStageCompactor",
    "MessageRole",
    "PipelineMessage",
    "TrimmedToolResult",
]
