"""Package facade for tool-safe compaction boundaries and file manifests transmission.

[INPUT]
- agent.context_management.tool_safe_compaction.safe_cut_point_detector::evaluate_cut_point,
  find_valid_cut_points, select_optimal_safe_cut_point (POS: Detects safe compaction boundaries ensuring
  tool_call and tool_result pairs remain intact.)
- agent.context_management.tool_safe_compaction.tool_safe_compaction_engine::ToolSafeCompactionEngine,
  extract_file_manifests (POS: Main compaction engine guaranteeing atomic tool-call safety and lossless file
  manifest survival.)
- agent.context_management.tool_safe_compaction.tool_safe_compaction_types::CutPointEvaluation,
  CutPointSafetyKind, FileManifests, MessageRole, SafeCompactionResult (POS: Data contracts for safe cut-point
  selection, file manifests extraction, and atomic tool compaction.)

[OUTPUT]
- Re-exports: CutPointEvaluation, CutPointSafetyKind, FileManifests, MessageRole, SafeCompactionResult,
  ToolSafeCompactionEngine, evaluate_cut_point, extract_file_manifests, find_valid_cut_points,
  select_optimal_safe_cut_point

[POS]
Tool-safe compaction boundary guard and file manifests transmission facade.
"""

from __future__ import annotations

from .safe_cut_point_detector import (
    evaluate_cut_point,
    find_valid_cut_points,
    select_optimal_safe_cut_point,
)
from .tool_safe_compaction_engine import (
    ToolSafeCompactionEngine,
    extract_file_manifests,
)
from .tool_safe_compaction_types import (
    CutPointEvaluation,
    CutPointSafetyKind,
    FileManifests,
    MessageRole,
    SafeCompactionResult,
)

__all__ = [
    "CutPointEvaluation",
    "CutPointSafetyKind",
    "FileManifests",
    "MessageRole",
    "SafeCompactionResult",
    "ToolSafeCompactionEngine",
    "evaluate_cut_point",
    "extract_file_manifests",
    "find_valid_cut_points",
    "select_optimal_safe_cut_point",
]
