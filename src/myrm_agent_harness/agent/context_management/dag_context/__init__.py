# [INPUT]: None
# [OUTPUT]: AssertionReconcileEngine, AssertionStatus, ContextAssertion, DagContextBudgetConfig, DagContextSuite, DagNodeLevel, ExactPageRecallConduit, HierarchicalDagContextEngineAndAssertionReconcileRecallSuite, HierarchicalDagFolder, HierarchicalDagNode, PageRecallResult, TurnRecord, VramBudgetEvaluation, VramPerformanceBudgetGuard
# [POS]: agent/context_management/dag_context/__init__.py

"""Hierarchical DAG context engine, assertion reconciliation, and exact page recall package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- AssertionReconcileEngine: Tracks assertion states, supercedes obsolete decisions, and eliminates contradictions.
- AssertionStatus: Lifecycle state machine for decisions (ACTIVE, SUPERSEDED, REVOKED).
- ContextAssertion: Granular architectural or business decision with conflict lineage.
- DagContextBudgetConfig: Configuration governing VRAM budget limits, fold thresholds, and recall.
- DagContextSuite: Convenient short-hand alias for developer ergonomics.
- DagNodeLevel: Hierarchy rank in the directed acyclic graph (RAW, PAGE_SUMMARY, ROOT_SKELETON).
- ExactPageRecallConduit: Serves exact historical turn pages without flooding main prompt context.
- HierarchicalDagContextEngineAndAssertionReconcileRecallSuite: Unified facade coordinating DAG context.
- HierarchicalDagFolder: Fold turns into Level-1 page summary nodes and Level-2 root skeleton nodes.
- HierarchicalDagNode: Directed graph node encapsulating folded summary and lineage pointers.
- PageRecallResult: Result of an on-demand exact page recall query by the agent.
- TurnRecord: Canonical representation of a conversation turn.
- VramBudgetEvaluation: Telemetry assessment of prompt token budget saturation.
- VramPerformanceBudgetGuard: Enforces local GPU memory safety preventing TTFT degradation.

[POS]
Package entry point for Item 312 HierarchicalDagContextEngineAndAssertionReconcileRecallSuite.
"""

from .assertion_reconcile_engine import AssertionReconcileEngine
from .dag_context_suite import (
    DagContextSuite,
    HierarchicalDagContextEngineAndAssertionReconcileRecallSuite,
)
from .dag_types import (
    AssertionStatus,
    ContextAssertion,
    DagContextBudgetConfig,
    DagNodeLevel,
    HierarchicalDagNode,
    PageRecallResult,
    TurnRecord,
)
from .exact_page_recall_conduit import ExactPageRecallConduit
from .hierarchical_dag_folder import HierarchicalDagFolder
from .vram_performance_budget_guard import (
    VramBudgetEvaluation,
    VramPerformanceBudgetGuard,
)

__all__ = [
    "AssertionReconcileEngine",
    "AssertionStatus",
    "ContextAssertion",
    "DagContextBudgetConfig",
    "DagContextSuite",
    "DagNodeLevel",
    "ExactPageRecallConduit",
    "HierarchicalDagContextEngineAndAssertionReconcileRecallSuite",
    "HierarchicalDagFolder",
    "HierarchicalDagNode",
    "PageRecallResult",
    "TurnRecord",
    "VramBudgetEvaluation",
    "VramPerformanceBudgetGuard",
]
