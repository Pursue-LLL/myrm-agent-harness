"""Skill Consolidation (Umbrella Merge) subsystem.

Provides automated detection and merging of fragmented skills into
class-level umbrella skills. Prevents "Agent getting dumber over time"
by reducing skill fragmentation and improving retrieval precision.

[OUTPUT]
- SkillConsolidator: Top-level orchestrator for the consolidation pipeline.
- ClusterDetector: Detects candidate skill clusters.
- ConsolidationJudge: LLM-driven merge strategy decision.
- ConsolidationExecutor: Applies consolidation actions.
- ConsolidationPlan: Pre-execution plan (for dry-run/preview).
- ConsolidationReport: Post-execution report.
- ConsolidationActionType: Action type enum.
- SkillCluster: Cluster data type.

[POS]
Skill consolidation (umbrella merge) subsystem. Top-level module with pipeline orchestrator.
"""

from .cluster_detector import ClusterDetector
from .executor import ConsolidationExecutor
from .judge import ConsolidationJudge
from .orchestrator import SkillConsolidator
from .types import (
    ConsolidationAction,
    ConsolidationActionType,
    ConsolidationPlan,
    ConsolidationReport,
    ConsolidationResult,
    SkillCluster,
)

__all__ = [
    "ClusterDetector",
    "ConsolidationAction",
    "ConsolidationActionType",
    "ConsolidationExecutor",
    "ConsolidationJudge",
    "ConsolidationPlan",
    "ConsolidationReport",
    "ConsolidationResult",
    "SkillCluster",
    "SkillConsolidator",
]
