# ============================================================================
# # Branch Summary Carrier & DAG Tree Explorer Types (Item 147)
# # Strict typed contracts for extracting abandoned branch lessons,
# # tree topology visualization, and cross-branch experience roaming.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class AbandonedBranchLessonsSummary:
    """Structured distillation of an abandoned branch's failures, constraints, and learnings."""

    branch_id: str
    branch_name: str
    abandoned_reason: str
    attempted_approaches: list[str] = field(default_factory=list)
    discovered_constraints: list[str] = field(default_factory=list)
    reusable_facts: list[str] = field(default_factory=list)
    summary_markdown: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | float | list[str]]:
        """Serializes lesson summary to standard dictionary."""
        return {
            "branch_id": self.branch_id,
            "branch_name": self.branch_name,
            "abandoned_reason": self.abandoned_reason,
            "attempted_approaches": list(self.attempted_approaches),
            "discovered_constraints": list(self.discovered_constraints),
            "reusable_facts": list(self.reusable_facts),
            "summary_markdown": self.summary_markdown,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class BranchCarrierForkRequest:
    """Request payload to fork a new branch while carrying forward abandoned lessons."""

    source_branch_id: str
    fork_point_node_id: str
    new_branch_name: str
    new_prompt: str
    extract_lessons: bool = True
    custom_abandoned_reason: str = ""


@dataclass(slots=True)
class BranchCarrierForkResponse:
    """Result payload after forking a branch with summary carrier injected."""

    new_branch_id: str
    fork_point_node_id: str
    new_active_node_id: str
    carrier_summary: AbandonedBranchLessonsSummary | None
    injected_context_preview: str


@dataclass(slots=True)
class TreeNodeView:
    """Visualization-ready node for Git DAG style tree drawers in WebUI / Desktop."""

    node_id: str
    parent_id: str | None
    branch_id: str
    role: str
    preview_text: str
    is_active_path: bool
    is_leaf: bool
    children_count: int
    created_at: float
