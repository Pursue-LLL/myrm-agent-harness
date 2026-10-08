# [INPUT]: AssertionReconcileEngine, AssertionStatus, ContextAssertion, DagContextBudgetConfig, DagContextSuite, DagNodeLevel, ExactPageRecallConduit, HierarchicalDagContextEngineAndAssertionReconcileRecallSuite, HierarchicalDagFolder, HierarchicalDagNode, PageRecallResult, TurnRecord, VramBudgetEvaluation, VramPerformanceBudgetGuard
# [OUTPUT]: test_dag_context_suite.py
# [POS]: tests/agent/context_management/test_dag_context_suite.py

"""Comprehensive unit tests for HierarchicalDagContextEngineAndAssertionReconcileRecallSuite.

Verifies:
1. Assertion lifecycle states (ACTIVE, SUPERSEDED, REVOKED) and automatic override conflict reconciliation.
2. Progressive hierarchical DAG folding: raw turns -> Level-1 page nodes -> Level-2 root skeleton.
3. Agent-native exact page recall and turn expansion with relevance scoring.
4. VRAM hardware-aware performance budget guard locking active prompt to 6K-8K safety watermarks.
5. End-to-end facade orchestration and active prompt context assembly.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.dag_context import (
    AssertionReconcileEngine,
    AssertionStatus,
    ContextAssertion,
    DagContextBudgetConfig,
    DagContextSuite,
    DagNodeLevel,
    ExactPageRecallConduit,
    HierarchicalDagContextEngineAndAssertionReconcileRecallSuite,
    HierarchicalDagFolder,
    HierarchicalDagNode,
    PageRecallResult,
    TurnRecord,
    VramBudgetEvaluation,
    VramPerformanceBudgetGuard,
)


def test_assertion_lifecycle_and_conflict_reconciliation() -> None:
    """Verifies that subsequent decisions supersede previous conflicting ones on the same topic."""
    engine = AssertionReconcileEngine()

    # Turn 200: Use SQLite
    a1 = engine.register_assertion(
        assertion_id="dec-001",
        topic="database",
        statement="Use SQLite in WAL mode for persistent session state.",
        origin_turn_id="turn-200",
    )
    assert a1.status == AssertionStatus.ACTIVE
    assert len(engine.get_active_assertions()) == 1

    # Turn 800: Reverse decision to PostgreSQL
    a2 = engine.register_assertion(
        assertion_id="dec-002",
        topic="database",
        statement="Standardize on PostgreSQL for high-concurrency multi-agent clustering.",
        origin_turn_id="turn-800",
    )
    assert a2.status == AssertionStatus.ACTIVE

    # Check that previous decision was automatically superseded
    superseded = engine.get_superseded_assertions()
    assert len(superseded) == 1
    assert superseded[0].assertion_id == "dec-001"
    assert superseded[0].status == AssertionStatus.SUPERSEDED
    assert superseded[0].superseded_by == "dec-002"

    # Only active decision is present in active assertions and rendered prompt
    active = engine.get_active_assertions()
    assert len(active) == 1
    assert active[0].assertion_id == "dec-002"

    md = engine.render_active_assertions_markdown()
    assert "PostgreSQL" in md
    assert "SQLite" not in md  # Obsolete conflict completely purged from active prompt!

    # Test explicit revocation
    revoked = engine.revoke_assertion("dec-002")
    assert revoked is True
    assert len(engine.get_active_assertions()) == 0


def test_hierarchical_dag_progressive_folding() -> None:
    """Verifies two-tier progressive folding into Level-1 page summaries and Level-2 root skeleton."""
    config = DagContextBudgetConfig(
        page_fold_turn_threshold=4,
        max_page_nodes_before_root_fold=2,
        recent_turns_unconditionally_kept=2,
    )
    folder = HierarchicalDagFolder(config=config)

    # Append 5 turns: threshold (4) + keep (2) = 6 not yet reached -> no page node
    for i in range(1, 6):
        folder.append_turn(
            TurnRecord(
                turn_id=f"t{i}",
                role="user" if i % 2 == 1 else "assistant",
                content=f"Message turn number {i} discussing architecture components.",
            )
        )
    assert len(folder.get_page_nodes()) == 0
    assert len(folder.get_active_unfolded_turns()) == 5

    # Append 6th turn: now 6 turns -> folds first 4 turns into Page-1, keeping t5..t6 unfolded
    folder.append_turn(
        TurnRecord(turn_id="t6", role="assistant", content="Turn 6 concluding first phase.")
    )
    pages = folder.get_page_nodes()
    assert len(pages) == 1
    p1 = pages[0]
    assert p1.node_id == "page-1"
    assert p1.level == DagNodeLevel.PAGE_SUMMARY
    assert p1.turn_range == ("t1", "t4")
    assert len(folder.get_active_unfolded_turns()) == 2  # t5, t6 remain unfolded

    # Append 4 more turns (t7..t10): total 10 turns -> folds t5..t8 into Page-2
    for i in range(7, 11):
        folder.append_turn(
            TurnRecord(turn_id=f"t{i}", role="user", content=f"Turn {i} content in second batch.")
        )
    assert len(folder.get_page_nodes()) == 2
    # Since max_page_nodes_before_root_fold = 2, Level-2 root skeleton is synthesized!
    root = folder.get_root_node()
    assert root is not None
    assert root.node_id == "dag-root"
    assert root.level == DagNodeLevel.ROOT_SKELETON
    assert "page-1" in root.content
    assert "page-2" in root.content


def test_exact_page_recall_and_turn_expansion() -> None:
    """Verifies on-demand agent drill-down tools without prompt bloat."""
    config = DagContextBudgetConfig(
        page_fold_turn_threshold=3,
        recent_turns_unconditionally_kept=1,
    )
    folder = HierarchicalDagFolder(config=config)

    # Append 4 turns -> folds t1..t3 into page-1
    turns = [
        TurnRecord(turn_id="t1", role="user", content="Deploy FastAPI server with SSL certificate."),
        TurnRecord(turn_id="t2", role="assistant", content="Generating certbot certificate on /etc/letsencrypt."),
        TurnRecord(turn_id="t3", role="user", content="Encountered error: Port 443 already in use by nginx."),
        TurnRecord(turn_id="t4", role="assistant", content="Stopped nginx and restarted FastAPI successfully."),
    ]
    for t in turns:
        folder.append_turn(t)

    conduit = ExactPageRecallConduit(folder)

    # 1. Recall page with query
    recall_res = conduit.recall_page("page-1", query="letsencrypt Port 443")
    assert recall_res is not None
    assert recall_res.page_id == "page-1"
    assert "Port 443 already in use" in recall_res.content
    assert recall_res.relevance_score > 0.5

    # 2. Recall nonexistent page
    assert conduit.recall_page("page-999") is None

    # 3. Expand single turn
    t3_record = conduit.expand_turn("t3")
    assert t3_record is not None
    assert "Port 443" in t3_record.content

    # 4. Tool specifications
    specs = conduit.generate_tool_specifications()
    assert len(specs) == 2
    names = [s["function"]["name"] for s in specs]
    assert "session_page_recall" in names
    assert "session_turn_expand" in names


def test_vram_performance_budget_guard() -> None:
    """Verifies hardware budget monitoring and safety ceiling alerts for local GPUs."""
    config = DagContextBudgetConfig(
        target_prompt_token_budget=200,
        vram_budget_lock=True,
    )
    guard = VramPerformanceBudgetGuard(config=config)

    small_turns = [
        TurnRecord(turn_id="t1", role="user", content="Hello", token_estimate=20),
    ]
    eval_healthy = guard.evaluate_active_prompt(
        active_turns=small_turns,
        active_pages=(),
        base_prompt_tokens=50,
    )
    assert eval_healthy.total_active_tokens == 70
    assert eval_healthy.is_budget_exceeded is False
    assert eval_healthy.recommended_action == "healthy_within_vram_budget"

    # Large turn overflowing budget
    large_turns = [
        TurnRecord(turn_id="t2", role="assistant", content="Big response", token_estimate=300),
    ]
    eval_overflow = guard.evaluate_active_prompt(
        active_turns=large_turns,
        active_pages=(),
        base_prompt_tokens=50,
    )
    assert eval_overflow.total_active_tokens == 350
    assert eval_overflow.is_budget_exceeded is True
    assert eval_overflow.recommended_action == "fold_older_turns_to_pages"


def test_full_dag_context_suite_facade() -> None:
    """Verifies end-to-end integration across the comprehensive DagContextSuite facade."""
    suite = HierarchicalDagContextEngineAndAssertionReconcileRecallSuite(
        config=DagContextBudgetConfig(
            page_fold_turn_threshold=3,
            max_page_nodes_before_root_fold=2,
            recent_turns_unconditionally_kept=1,
        )
    )
    assert DagContextSuite is HierarchicalDagContextEngineAndAssertionReconcileRecallSuite

    # 1. Register conflicting decisions
    suite.register_decision_assertion("dec-1", "framework", "Use React with Redux", origin_turn_id="t1")
    suite.register_decision_assertion("dec-2", "framework", "Migrate to SvelteKit with stores", origin_turn_id="t5")

    # 2. Record turns
    for i in range(1, 6):
        suite.record_turn(
            turn_id=f"t{i}",
            role="user" if i % 2 == 1 else "assistant",
            content=f"Engineering dialogue message {i}.",
        )

    # 3. Compile prompt context
    compiled = suite.compile_active_prompt_context()
    assert "SvelteKit" in compiled
    assert "React with Redux" not in compiled  # Conflict purged!
    assert "page-1" in compiled  # Page folded
    assert "t5" in compiled  # Recent turn preserved

    # 4. Recall tool specs
    tools = suite.get_recall_tool_specs()
    assert len(tools) == 2

    # 5. Evaluate budget
    vram_eval = suite.evaluate_vram_budget(base_prompt_tokens=500)
    assert vram_eval.total_active_tokens > 500
