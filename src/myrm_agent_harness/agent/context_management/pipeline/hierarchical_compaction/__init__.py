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
