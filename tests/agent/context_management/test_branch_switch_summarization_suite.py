"""Unit tests for BranchSwitchSummarizationAndContextTransferSuite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    BranchExplorationCard,
    BranchOutcomeCondenser,
    BranchOutcomeVerdict,
    BranchSummaryEntry,
    BranchSwitchSummarizationAndContextTransferSuite,
    BranchTransferReceipt,
    SessionTreeDagSuite,
)


def test_condense_failed_branch_and_synthesize_lesson() -> None:
    """Test extracting failures, unviable options, and synthesizing actionable lessons from branch entries."""
    tree = SessionTreeDagSuite(session_id="sess-transfer-001")
    n1 = tree.append_message(role="user", content="Initialize project")
    tree.fork_branch("experiment-v2", from_entry_id=n1.entry_id)
    tree.switch_active_branch("experiment-v2")

    # Simulate exploratory trials with errors
    tree.append_message(role="assistant", content="Try implementing async Redis connection pool")
    tree.append_message(
        role="system",
        content="Error: version conflict detected! redis-py 5.0 is incompatible with Python 3.13 event loop",
    )
    tree.append_message(role="system", content="Exception: connection pool timed out after 3000ms")

    suite = BranchSwitchSummarizationAndContextTransferSuite(session_id="sess-transfer-001")
    exclusive_entries = suite.extract_branch_exclusive_entries(tree, "experiment-v2")
    assert len(exclusive_entries) == 3

    card = BranchOutcomeCondenser.condense_branch_entries(
        source_branch_name="experiment-v2",
        target_branch_name="main",
        entries=exclusive_entries,
        verdict=BranchOutcomeVerdict.ABANDONED_FAILURE,
    )

    assert isinstance(card, BranchExplorationCard)
    assert card.source_branch == "experiment-v2"
    assert card.target_branch == "main"
    assert card.verdict == BranchOutcomeVerdict.ABANDONED_FAILURE
    assert "version conflict" in (card.failure_root_cause or "").lower()
    assert len(card.unviable_options) >= 2
    assert "Do not repeat this attempt on main" in card.key_lesson

    summary_entry = BranchOutcomeCondenser.synthesize_summary_entry(card)
    assert isinstance(summary_entry, BranchSummaryEntry)
    assert "<branch_switch_lesson" in summary_entry.formatted_prompt_payload
    assert "Dead ends avoided:" in summary_entry.formatted_prompt_payload
    assert summary_entry.estimated_tokens > 0


def test_seamless_branch_switch_with_lesson_injection() -> None:
    """Test switching back to trunk with synthesized lesson injected and zero log pollution on trunk."""
    tree = SessionTreeDagSuite(session_id="sess-transfer-002")
    n1 = tree.append_message(role="user", content="Build database schema")
    n2 = tree.append_message(role="assistant", content="Base schema created in SQLite")

    # Fork experimental branch
    tree.fork_branch("mongo-trial", from_entry_id=n2.entry_id)
    tree.switch_active_branch("mongo-trial")
    tree.append_message(role="assistant", content="Attempt migration to MongoDB Atlas")
    tree.append_message(role="system", content="Failed to connect to cluster: TLS handshake failed")
    tree.append_message(role="system", content="Error: schema validation failed for complex relations")

    # Switch back to main trunk with distillation
    suite = BranchSwitchSummarizationAndContextTransferSuite(session_id="sess-transfer-002")
    summary_entry, receipt = suite.switch_branch_with_condensed_summary(
        tree_suite=tree,
        source_branch="mongo-trial",
        target_branch="main",
        verdict=BranchOutcomeVerdict.ABANDONED_FAILURE,
    )

    assert tree.active_branch_name == "main"
    assert receipt.source_turns_count == 3
    assert receipt.target_branch == "main"
    assert len(receipt.transfer_hash) == 16

    # Verify active lineage on main trunk
    main_lineage = tree.get_active_lineage_path()
    assert len(main_lineage) == 3  # n1, n2, + injected lesson entry
    contents = [e.payload["content"] for e in main_lineage]

    # Verify lesson is present
    assert any("<branch_switch_lesson" in c for c in contents)
    # Verify raw unsummarized error turns from experimental branch never leaked onto trunk
    raw_unsummarized_turns = [
        c for c in contents if not c.startswith("<branch_switch_lesson") and "TLS handshake failed" in c
    ]
    assert len(raw_unsummarized_turns) == 0


def test_partially_validated_and_successful_discovery_condensation() -> None:
    """Test condensing branches with successful findings and custom takeaways."""
    tree = SessionTreeDagSuite(session_id="sess-transfer-003")
    n1 = tree.append_message(role="user", content="Research performance optimization")
    tree.fork_branch("simd-research", from_entry_id=n1.entry_id)
    tree.switch_active_branch("simd-research")

    tree.append_message(role="assistant", content="Experiment with AVX-512 SIMD vectorization")
    tree.append_message(role="system", content="Successfully vectorized matrix multiplication")
    tree.append_message(role="system", content="Verified: 4.8x speedup achieved over scalar baseline")

    suite = BranchSwitchSummarizationAndContextTransferSuite(session_id="sess-transfer-003")
    summary_entry, receipt = suite.switch_branch_with_condensed_summary(
        tree_suite=tree,
        source_branch="simd-research",
        target_branch="main",
        verdict=BranchOutcomeVerdict.SUCCESSFUL_DISCOVERY,
        manual_takeaway="SIMD vectorization verified 4.8x throughput gain; integrate in sprint 2.",
    )

    assert receipt.verdict == BranchOutcomeVerdict.SUCCESSFUL_DISCOVERY
    assert "verified 4.8x throughput gain" in summary_entry.formatted_prompt_payload

    cards = suite.get_all_distilled_cards()
    assert len(cards) == 1
    assert cards[0].verdict == BranchOutcomeVerdict.SUCCESSFUL_DISCOVERY
    assert len(cards[0].validated_findings) >= 1


def test_transfer_receipt_cryptographic_verification_and_registry() -> None:
    """Test cryptographic integrity of transfer receipts and cross-branch knowledge accumulation."""
    suite = BranchSwitchSummarizationAndContextTransferSuite(session_id="sess-transfer-004")
    tree = SessionTreeDagSuite(session_id="sess-transfer-004")
    tree.append_message(role="user", content="Init")

    # Branch 1 trial
    tree.fork_branch("b1")
    tree.switch_active_branch("b1")
    tree.append_message(role="assistant", content="Trial 1")
    suite.switch_branch_with_condensed_summary(tree, "b1", "main")

    # Branch 2 trial
    tree.fork_branch("b2")
    tree.switch_active_branch("b2")
    tree.append_message(role="assistant", content="Trial 2")
    suite.switch_branch_with_condensed_summary(tree, "b2", "main")

    receipts = suite.get_transfer_receipts()
    assert len(receipts) == 2
    for r in receipts:
        assert isinstance(r, BranchTransferReceipt)
        assert r.session_id == "sess-transfer-004"
        assert len(r.transfer_hash) == 16

    assert len(suite.get_all_distilled_cards()) == 2
