"""Comprehensive facade suite for hierarchical DAG context, assertion reconciliation, and exact page recall.

[INPUT]
- ContextAssertion, TurnRecord, HierarchicalDagNode, PageRecallResult, DagContextBudgetConfig, VramBudgetEvaluation: Contracts.
- AssertionReconcileEngine, HierarchicalDagFolder, ExactPageRecallConduit, VramPerformanceBudgetGuard: Underlying engines.

[OUTPUT]
- HierarchicalDagContextEngineAndAssertionReconcileRecallSuite: Primary facade for Item 312.
- DagContextSuite: Convenient alias.

[POS]
Main entry point coordinating DAG progressive folding, conflict-free assertions, and on-demand agent page recall.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence

from .assertion_reconcile_engine import AssertionReconcileEngine
from .dag_types import (
    ContextAssertion,
    DagContextBudgetConfig,
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


class HierarchicalDagContextEngineAndAssertionReconcileRecallSuite:
    """Unified facade managing hierarchical DAG context folding, assertion reconciliation, and recall tools."""

    def __init__(self, config: DagContextBudgetConfig | None = None) -> None:
        self._config = config or DagContextBudgetConfig()
        self._assertion_engine = AssertionReconcileEngine()
        self._folder = HierarchicalDagFolder(self._config)
        self._conduit = ExactPageRecallConduit(self._folder)
        self._budget_guard = VramPerformanceBudgetGuard(self._config)

    @property
    def config(self) -> DagContextBudgetConfig:
        """The configuration in effect."""
        return self._config

    def record_turn(
        self,
        turn_id: str,
        role: str,
        content: str,
        timestamp: float | None = None,
        token_estimate: int | None = None,
    ) -> TurnRecord:
        """Record an immutable turn and update progressive DAG folding."""
        now = timestamp if timestamp is not None else time.time()
        tokens = token_estimate if token_estimate is not None else len(content.split())
        record = TurnRecord(
            turn_id=turn_id,
            role=role,
            content=content,
            timestamp=now,
            token_estimate=tokens,
        )
        self._folder.append_turn(record)
        return record

    def register_decision_assertion(
        self,
        assertion_id: str,
        topic: str,
        statement: str,
        origin_turn_id: str = "",
    ) -> ContextAssertion:
        """Register a decision assertion, automatically superseding previous conflicting decisions on this topic."""
        return self._assertion_engine.register_assertion(
            assertion_id=assertion_id,
            topic=topic,
            statement=statement,
            origin_turn_id=origin_turn_id,
        )

    def revoke_decision(self, assertion_id: str) -> bool:
        """Revoke a previously active decision."""
        return self._assertion_engine.revoke_assertion(assertion_id)

    def get_active_assertions(self) -> Sequence[ContextAssertion]:
        """Return all currently active non-conflicting assertions."""
        return self._assertion_engine.get_active_assertions()

    def get_superseded_assertions(self) -> Sequence[ContextAssertion]:
        """Return all superseded assertions."""
        return self._assertion_engine.get_superseded_assertions()

    def recall_page(self, page_id: str, query: str = "") -> PageRecallResult | None:
        """Recall exact transcript of a historical folded page."""
        return self._conduit.recall_page(page_id=page_id, query=query)

    def expand_turn(self, turn_id: str) -> TurnRecord | None:
        """Expand exact verbatim content of a specific historical turn."""
        return self._conduit.expand_turn(turn_id=turn_id)

    def get_recall_tool_specs(self) -> Sequence[Mapping[str, object]]:
        """Return OpenAI-compatible tool specifications for agent page recall."""
        return self._conduit.generate_tool_specifications()

    def evaluate_vram_budget(self, base_prompt_tokens: int = 1000) -> VramBudgetEvaluation:
        """Evaluate active prompt size against consumer GPU performance budgets."""
        return self._budget_guard.evaluate_active_prompt(
            active_turns=self._folder.get_active_unfolded_turns(),
            active_pages=self._folder.get_page_nodes(),
            root_skeleton=self._folder.get_root_node(),
            base_prompt_tokens=base_prompt_tokens,
        )

    def compile_active_prompt_context(self) -> str:
        """Assemble a complete active context injection block including DAG skeleton and reconciled assertions."""
        sections: list[str] = []

        # 1. Reconciled active assertions
        assertions_md = self._assertion_engine.render_active_assertions_markdown()
        if assertions_md:
            sections.append(assertions_md)

        # 2. Level-2 root skeleton if synthesized
        root = self._folder.get_root_node()
        if root:
            sections.append(root.content)

        # 3. Level-1 page summaries
        pages = self._folder.get_page_nodes()
        if pages:
            page_blocks: list[str] = ["### 📄 [Folded History Pages]"]
            for p in pages:
                page_blocks.append(f"#### {p.title} (Use `session_page_recall('{p.node_id}')` to expand):\n{p.content}")
            sections.append("\n".join(page_blocks))

        # 4. Recent unfolded turns
        unfolded = self._folder.get_active_unfolded_turns()
        if unfolded:
            turn_blocks: list[str] = ["### 💬 [Recent Active Dialogue]"]
            for t in unfolded:
                turn_blocks.append(f"- **Turn {t.turn_id} ({t.role.upper()})**: {t.content}")
            sections.append("\n".join(turn_blocks))

        return "\n\n".join(sections).strip()


DagContextSuite = HierarchicalDagContextEngineAndAssertionReconcileRecallSuite
