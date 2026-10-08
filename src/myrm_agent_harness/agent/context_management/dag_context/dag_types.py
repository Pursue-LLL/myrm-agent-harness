"""Domain contracts and data models for hierarchical DAG context and assertion reconciliation.

[INPUT]
- None (Self-contained domain definitions).

[OUTPUT]
- AssertionStatus: Lifecycle state machine for decisions (ACTIVE, SUPERSEDED, REVOKED).
- ContextAssertion: Granular architectural or business decision with conflict lineage.
- DagNodeLevel: Hierarchy rank in the directed acyclic graph (RAW, PAGE_SUMMARY, ROOT_SKELETON).
- HierarchicalDagNode: Directed graph node encapsulating folded summary and lineage pointers.
- DagContextBudgetConfig: Configuration governing VRAM budget limits, fold thresholds, and recall.
- PageRecallResult: Exact historical page snippet retrieved on demand.
- TurnRecord: Canonical representation of a conversation turn.

[POS]
Domain contract layer for Item 312 HierarchicalDagContextEngineAndAssertionReconcileRecallSuite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class AssertionStatus(str, Enum):
    """Lifecycle state machine governing decision assertions across long sessions."""

    ACTIVE = "active"          # Currently valid decision in effect
    SUPERSEDED = "superseded"  # Overridden/reversed by a subsequent decision
    REVOKED = "revoked"        # Explicitly cancelled without direct replacement


class DagNodeLevel(int, Enum):
    """Hierarchy rank within the contextual directed acyclic graph."""

    RAW = 0            # Level 0: Raw immutable turn records
    PAGE_SUMMARY = 1   # Level 1: Folded page node condensing a chunk of turns (e.g. 8 turns)
    ROOT_SKELETON = 2  # Level 2: Higher-order skeleton synthesizing multiple Level 1 page nodes


@dataclass(frozen=True)
class ContextAssertion:
    """Atomic decision or architectural constraint with conflict reconciliation tracking."""

    assertion_id: str
    topic: str
    statement: str
    status: AssertionStatus = AssertionStatus.ACTIVE
    origin_turn_id: str = ""
    superseded_by: str = ""
    created_at: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TurnRecord:
    """Immutable conversation turn record preserved in local archive."""

    turn_id: str
    role: str
    content: str
    timestamp: float = 0.0
    token_estimate: int = 0


@dataclass(frozen=True)
class HierarchicalDagNode:
    """DAG node representing a level-1 page summary or level-2 root skeleton."""

    node_id: str
    level: DagNodeLevel
    title: str
    content: str
    turn_range: tuple[str, str]  # (start_turn_id, end_turn_id)
    parent_ids: Sequence[str] = field(default_factory=tuple)
    child_ids: Sequence[str] = field(default_factory=tuple)
    token_count: int = 0
    created_at: float = 0.0


@dataclass(frozen=True)
class PageRecallResult:
    """Result of an on-demand exact page recall query by the agent."""

    page_id: str
    turn_range: tuple[str, str]
    title: str
    content: str
    relevance_score: float = 0.0


@dataclass(frozen=True)
class DagContextBudgetConfig:
    """Configuration governing VRAM hardware performance budgets and DAG folding."""

    target_prompt_token_budget: int = 6000     # 6K-8K compact safety watermark for single GPU
    page_fold_turn_threshold: int = 8          # Turns per Level-1 page summary node
    max_page_nodes_before_root_fold: int = 4   # When Level-1 nodes exceed this, synthesize Level-2
    recent_turns_unconditionally_kept: int = 4 # Keep latest turns raw in active prompt
    vram_budget_lock: bool = True
