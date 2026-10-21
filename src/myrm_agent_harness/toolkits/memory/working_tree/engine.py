"""Tree repair and backtracking pruning engine.

[INPUT]
- toolkits.memory.working_tree.tree::EvidenceTree (POS: 有向无环因果图容器)
- toolkits.memory.working_tree.models::EvidenceNode (POS: 强类型树状工作记忆原子节点)
- toolkits.memory.working_tree.models::TreeRepairResult (POS: 回溯修复与分支剪枝结果容器)
- toolkits.memory.working_tree.models::RevisionRecord (POS: 回溯修复与版本审计日志)
- toolkits.memory.working_tree.models::ConflictType (POS: 语义冲突与时态演化分类枚举)

[OUTPUT]
- TreeRepairEngine: 原子四步回溯修复、证据热替换、级联分支软剪枝与震荡阻尼引擎

[POS]
ReTree 自纠错修复引擎。执行根因定位、证据替换、摘要重编译、下游级联软剪枝与震荡死循环阻尼。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .models import (
    BoundedSummary,
    ConflictType,
    EvidenceNodeStatus,
    EvidenceSource,
    RevisionRecord,
    TreeRepairResult,
)

if TYPE_CHECKING:
    from .tree import EvidenceTree

MAX_REVISIONS_PER_NODE = 2


class TreeRepairEngine:
    """Executes atomic backtracking repair and branch pruning over an EvidenceTree."""

    def __init__(self, tree: EvidenceTree) -> None:
        self.tree = tree

    def apply_repair(
        self,
        target_node_id: str,
        new_claim: str,
        new_summary: BoundedSummary,
        new_source: EvidenceSource,
        conflict_type: ConflictType,
        reason: str,
    ) -> TreeRepairResult:
        """Apply backtracking repair on target_node_id and cascade-prune downstream dependents."""
        target_node = self.tree.get_node(target_node_id)
        if not target_node:
            return TreeRepairResult(
                target_node_id=target_node_id,
                pruned_node_ids=[],
                is_disputed=False,
                resolution_summary=f"Target node {target_node_id} not found",
            )

        now = datetime.now(UTC).isoformat()

        # Oscillation Guard: If this node has already flipped back and forth, freeze as disputed
        if target_node.revision_depth >= MAX_REVISIONS_PER_NODE:
            target_node.status = EvidenceNodeStatus.DISPUTED
            target_node.updated_at = now
            return TreeRepairResult(
                target_node_id=target_node_id,
                pruned_node_ids=[],
                is_disputed=True,
                resolution_summary=(
                    f"Oscillation guard triggered on {target_node_id} (revisions={target_node.revision_depth}). "
                    f"Preserved competing perspectives without branch pruning."
                ),
            )

        # Step 1 & 2: Log revision record and hot-replace node evidence
        revision_log = RevisionRecord(
            revision_id=str(uuid.uuid4())[:8],
            previous_summary=target_node.bounded_summary.summary,
            reason=reason,
            superseded_by_url=new_source.url or None,
            revised_at=now,
        )
        target_node.revisions.append(revision_log)
        target_node.revision_depth += 1
        target_node.claim = new_claim
        target_node.bounded_summary = new_summary
        target_node.source = new_source
        target_node.updated_at = now

        # If it is purely a temporal update, do not invalidate downstream branches
        if conflict_type == ConflictType.TEMPORAL_UPDATE:
            return TreeRepairResult(
                target_node_id=target_node_id,
                pruned_node_ids=[],
                is_disputed=False,
                resolution_summary=f"Temporal update applied to node {target_node_id}; dependents preserved.",
            )

        # Step 3 & 4: Cascade dependency pruning for direct contradictions
        downstream_ids = self.tree.get_downstream_dependents(target_node_id)
        pruned_ids: list[str] = []

        for dep_id in downstream_ids:
            dep_node = self.tree.get_node(dep_id)
            if dep_node and dep_node.status != EvidenceNodeStatus.PRUNED_INVALIDATED:
                dep_node.status = EvidenceNodeStatus.PRUNED_INVALIDATED
                dep_node.updated_at = now
                pruned_ids.append(dep_id)

        resolution = (
            f"Successfully revised node {target_node_id} (revision depth={target_node.revision_depth}) "
            f"and cascade-pruned {len(pruned_ids)} downstream invalidated nodes: {pruned_ids}"
        )

        return TreeRepairResult(
            target_node_id=target_node_id,
            pruned_node_ids=pruned_ids,
            is_disputed=False,
            resolution_summary=resolution,
        )
