# ============================================================================
# # BranchSummaryCarrierEngine - Abandoned Branch Lessons Distiller (Item 147)
# # Extracts lessons, constraints, and failures from abandoned exploration branches,
# # carries them into fresh lightweight forks, and provides DAG tree visualizer data.
# ============================================================================

from __future__ import annotations

import re
import time
import uuid

from .branch_carrier_types import (
    AbandonedBranchLessonsSummary,
    BranchCarrierForkRequest,
    BranchCarrierForkResponse,
    TreeNodeView,
)
from .session_dag_graph import SessionDagGraph
from .session_dag_types import SessionDagNode

_FAILURE_KEYWORDS = ("error", "failed", "exception", "timeout", "rejected", "conflict", "不可行", "失败", "报错")


class BranchSummaryCarrierEngine:
    """Distills trial-and-error lessons from abandoned branches to roam into new forks."""

    def __init__(self) -> None:
        pass

    def get_nodes_in_branch(self, graph: SessionDagGraph, branch_id: str) -> list[SessionDagNode]:
        """Returns all nodes tagged under the specified branch_id sorted by creation time."""
        nodes = [n for n in graph.nodes.values() if n.branch_id == branch_id]
        nodes.sort(key=lambda n: n.created_at)
        return nodes

    def extract_abandoned_branch_lessons(
        self,
        graph: SessionDagGraph,
        branch_id: str,
        custom_reason: str = "",
    ) -> AbandonedBranchLessonsSummary:
        """Distills attempts, errors, and hard constraints from an abandoned exploration branch."""
        branch_nodes = self.get_nodes_in_branch(graph, branch_id)
        branch_name = branch_id

        attempted_approaches: list[str] = []
        discovered_constraints: list[str] = []
        reusable_facts: list[str] = []

        for node in branch_nodes:
            content = node.content.strip()
            if not content:
                continue

            # 1. Approach extraction
            if node.role in ("user", "assistant"):
                # Take first line or concise summary
                first_line = content.splitlines()[0]
                if len(first_line) > 100:
                    first_line = first_line[:97] + "..."
                if first_line not in attempted_approaches:
                    attempted_approaches.append(f"[{node.role}] {first_line}")

            # 2. Failure & constraint extraction
            lines = content.splitlines()
            for line in lines:
                lower = line.lower()
                if any(kw in lower for kw in _FAILURE_KEYWORDS):
                    clean_line = line.strip()
                    if clean_line and len(clean_line) < 160 and clean_line not in discovered_constraints:
                        discovered_constraints.append(clean_line)

            # 3. Reusable facts extraction (e.g. paths, versions)
            found_paths = re.findall(r"(/[a-zA-Z0-9_\-\.\/]+|`[^`]+`)", content)
            for path_or_sym in found_paths:
                if len(path_or_sym) > 4 and path_or_sym not in reusable_facts and len(reusable_facts) < 8:
                    reusable_facts.append(path_or_sym)

        reason = custom_reason.strip() or "方案探索受阻或未达预期，主动切分支尝试替代思路"

        # Build clean markdown carrier block
        md_lines = [
            f'<abandoned_branch_lessons source_branch="{branch_id}">',
            f"### ⚠️ 上一分支（{branch_name}）试错经验总结（轻装上阵，防止重复踩坑）：",
            f"- **放弃原因**：{reason}",
        ]
        if attempted_approaches:
            md_lines.append(f"- **已尝试方案**：{'; '.join(attempted_approaches[:4])}")
        if discovered_constraints:
            md_lines.append(f"- **已探明失败点/约束**：{'; '.join(discovered_constraints[:4])}")
        if reusable_facts:
            md_lines.append(f"- **保留已验证事实**：{', '.join(reusable_facts[:6])}")
        md_lines.append("</abandoned_branch_lessons>")

        summary_markdown = "\n".join(md_lines)

        return AbandonedBranchLessonsSummary(
            branch_id=branch_id,
            branch_name=branch_name,
            abandoned_reason=reason,
            attempted_approaches=attempted_approaches[:5],
            discovered_constraints=discovered_constraints[:5],
            reusable_facts=reusable_facts[:8],
            summary_markdown=summary_markdown,
            created_at=time.time(),
        )

    def fork_with_summary_carrier(
        self,
        graph: SessionDagGraph,
        request: BranchCarrierForkRequest,
    ) -> BranchCarrierForkResponse:
        """Forks a new branch from a historical node while carrying forward distilled lessons."""
        if request.fork_point_node_id not in graph.nodes:
            raise KeyError(f"Fork point '{request.fork_point_node_id}' does not exist in graph.")

        carrier_summary: AbandonedBranchLessonsSummary | None = None
        injected_content = request.new_prompt

        if request.extract_lessons:
            carrier_summary = self.extract_abandoned_branch_lessons(
                graph=graph,
                branch_id=request.source_branch_id,
                custom_reason=request.custom_abandoned_reason,
            )
            # Prepend lessons block to fresh prompt
            injected_content = f"{carrier_summary.summary_markdown}\n\n{request.new_prompt}"

        new_branch_id = f"branch-{uuid.uuid4().hex[:8]}"

        # Append new branched message onto the fork point node
        new_node = graph.branch_from_node(
            target_node_id=request.fork_point_node_id,
            new_content=injected_content,
            role="user",
            branch_id=new_branch_id,
            metadata={
                "branch_name": request.new_branch_name,
                "carried_lessons_from": request.source_branch_id if carrier_summary else "",
            },
        )

        return BranchCarrierForkResponse(
            new_branch_id=new_branch_id,
            fork_point_node_id=request.fork_point_node_id,
            new_active_node_id=new_node.node_id,
            carrier_summary=carrier_summary,
            injected_context_preview=injected_content[:150],
        )

    def export_tree_visualizer_view(self, graph: SessionDagGraph) -> list[TreeNodeView]:
        """Produces a flat list of node views for frontend DAG tree explorer rendering."""
        active_path_nodes = set(n.node_id for n in graph.get_linear_path())
        views: list[TreeNodeView] = []

        # Sort chronologically
        all_nodes = list(graph.nodes.values())
        all_nodes.sort(key=lambda n: n.created_at)

        for node in all_nodes:
            preview = node.content.strip().splitlines()[0] if node.content.strip() else "(empty)"
            if len(preview) > 60:
                preview = preview[:57] + "..."

            is_leaf = len(node.children_ids) == 0
            is_active = node.node_id in active_path_nodes

            views.append(
                TreeNodeView(
                    node_id=node.node_id,
                    parent_id=node.parent_id,
                    branch_id=node.branch_id,
                    role=node.role,
                    preview_text=preview,
                    is_active_path=is_active,
                    is_leaf=is_leaf,
                    children_count=len(node.children_ids),
                    created_at=node.created_at,
                )
            )

        return views
