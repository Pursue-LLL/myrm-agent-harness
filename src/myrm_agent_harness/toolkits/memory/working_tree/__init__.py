"""Tree-structured working memory toolkit (ReTree implementation).

Provides EvidenceTree, EvidenceNode, FastContradictionDetector, and TreeRepairEngine
for self-correcting long-horizon search and research agents.
"""

from .detector import FastContradictionDetector
from .engine import TreeRepairEngine
from .models import (
    BoundedSummary,
    ConflictType,
    ConflictVerdict,
    EvidenceNode,
    EvidenceNodeStatus,
    EvidenceSource,
    RevisionRecord,
    TreeRepairResult,
)
from .tree import EvidenceTree

__all__ = [
    "BoundedSummary",
    "ConflictType",
    "ConflictVerdict",
    "EvidenceNode",
    "EvidenceNodeStatus",
    "EvidenceSource",
    "EvidenceTree",
    "FastContradictionDetector",
    "RevisionRecord",
    "TreeRepairEngine",
    "TreeRepairResult",
]
