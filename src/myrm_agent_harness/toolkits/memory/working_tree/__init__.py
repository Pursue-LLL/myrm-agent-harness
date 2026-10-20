"""Tree-structured working memory toolkit (ReTree implementation).

[INPUT]
- toolkits.memory.working_tree.detector::FastContradictionDetector
  (POS: 快速矛盾检测层)
- toolkits.memory.working_tree.engine::TreeRepairEngine
  (POS: 证据树修复引擎层)
- toolkits.memory.working_tree.models::BoundedSummary, ConflictType, ConflictVerdict,
  EvidenceNode, EvidenceNodeStatus, EvidenceSource, RevisionRecord, TreeRepairResult
  (POS: 证据树数据模型层)
- toolkits.memory.working_tree.tree::EvidenceTree (POS: 证据树结构层)

[OUTPUT]
- EvidenceTree, EvidenceNode, FastContradictionDetector, TreeRepairEngine and models
  for self-correcting long-horizon search and research agents

[POS]
Public surface of the working-tree memory toolkit. Keeps intermediate research state in a
bounded tree so contradictions can be detected and repaired without replaying history.
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
