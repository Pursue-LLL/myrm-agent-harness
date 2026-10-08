"""Unit tests for SessionTreeBranchPruneAndStorageGCSuite."""

from __future__ import annotations

from pathlib import Path
import pytest

from myrm_agent_harness.agent.context_management import (
    GcSafetyRule,
    PrunedBranchReport,
    SessionTreeBranchPruneAndStorageGCSuite,
    SessionTreeDagSuite,
    SessionTreeGcEngine,
    StorageGcReceipt,
)


def test_identify_prunable_branches_and_safety_exclusion() -> None:
    """Test discovering prunable exploration branches while safeguarding active and root branches."""
    suite = SessionTreeDagSuite(session_id="sess-gc-001")
    suite.append_message("user", "Hello")

    # Create several exploration branches
    suite.fork_branch("experiment-alpha")
    suite.fork_branch("experiment-beta")
    suite.fork_branch("dead-branch-gamma")

    # Set active branch to experiment-alpha
    suite.switch_active_branch("experiment-alpha")

    gc_suite = SessionTreeBranchPruneAndStorageGCSuite(tree_suite=suite)
    prunable = gc_suite.identify_prunable_branches()

    # Active branch (experiment-alpha) and protected root (main) must NOT be in prunable list
    assert "main" not in prunable
    assert "experiment-alpha" not in prunable
    assert "experiment-beta" in prunable
    assert "dead-branch-gamma" in prunable

    # Attempting to prune active branch directly must raise ValueError
    with pytest.raises(ValueError, match="Cannot prune active exploration branch"):
        SessionTreeGcEngine.execute_prune_and_squash(
            tree_suite=suite,
            branches_to_prune=["experiment-alpha"],
        )

    # Attempting to prune main root branch directly must raise ValueError
    with pytest.raises(ValueError, match="Cannot prune root protected branch"):
        SessionTreeGcEngine.execute_prune_and_squash(
            tree_suite=suite,
            branches_to_prune=["main"],
        )


def test_exclusive_entry_purging_and_permanent_summary_preservation() -> None:
    """Test purging exclusive branch nodes while enforcing permanent summary preservation."""
    suite = SessionTreeDagSuite(session_id="sess-gc-002")
    msg1 = suite.append_message("user", "Initial prompt on main")

    # Fork dead branch and add isolated trial messages
    suite.fork_branch("dead-branch-1")
    suite.switch_active_branch("dead-branch-1")
    dead_msg1 = suite.append_message("assistant", "Dead trial 1")
    dead_msg2 = suite.append_message("assistant", "Dead trial 2")

    # Switch back to main
    suite.switch_active_branch("main")

    gc_suite = SessionTreeBranchPruneAndStorageGCSuite(tree_suite=suite, require_summary_anchor=True)

    # 1. Prune without summary anchor should fail when require_summary_anchor=True
    with pytest.raises(RuntimeError, match="has no permanent summary anchor in main lineage"):
        gc_suite.prune_branch("dead-branch-1", force=False)

    # 2. Deposit summary anchor on main representing the lesson learned
    suite.append_message(
        "system",
        "<branch_switch_lesson source_branch=\"dead-branch-1\">Tried approach A, failed due to timeout.</branch_switch_lesson>",
    )

    # Now prune should succeed with anchor verified
    report, receipt = gc_suite.prune_branch("dead-branch-1", force=False)
    assert report.had_summary_anchor is True
    assert report.purged_entries_count == 2
    assert "dead-branch-1" not in [b.branch_name for b in suite.list_branches()]

    # Main messages remain intact
    all_entries = suite.get_storage().get_all_entries()
    entry_ids = [e.entry_id for e in all_entries]
    assert dead_msg1.entry_id not in entry_ids
    assert dead_msg2.entry_id not in entry_ids
    assert msg1.entry_id in entry_ids


def test_physical_storage_compaction_and_file_squash(tmp_path: Path) -> None:
    """Test on-disk JSONL file physical compaction and byte size shrinkage."""
    log_file = tmp_path / "session_history.jsonl"
    suite = SessionTreeDagSuite(session_id="sess-gc-003", persistence_file_path=str(log_file))

    suite.append_message("user", "Base prompt")
    suite.fork_branch("temp-experiment")
    suite.switch_active_branch("temp-experiment")

    # Add 10 bulky trial entries on temp branch
    for i in range(10):
        suite.append_message("assistant", f"Bulky intermediate log dump {i} " + "X" * 100)

    # Switch back to main
    suite.switch_active_branch("main")
    suite.append_message("assistant", "Proceeding on main cleanly")

    before_size = log_file.stat().st_size
    assert before_size > 1000

    gc_suite = SessionTreeBranchPruneAndStorageGCSuite(tree_suite=suite)
    receipt = gc_suite.prune_all_dead_branches(force=True)

    after_size = log_file.stat().st_size
    assert receipt.purged_entries_count == 10
    assert after_size < before_size
    assert receipt.freed_storage_bytes > 0
    assert "temp-experiment" in receipt.pruned_branches

    # Read lines from compacted file directly to verify valid JSON
    storage = suite.get_storage()
    lines = storage.get_raw_jsonl_lines()
    assert len(lines) == 2  # Only the 2 main branch messages remain


def test_storage_gc_receipt_audit_integrity() -> None:
    """Test cryptographic compaction receipt audit trail and multi-cycle receipts."""
    suite = SessionTreeDagSuite(session_id="sess-gc-004")
    suite.append_message("user", "Task kickoff")

    suite.fork_branch("exp-1")
    suite.switch_active_branch("exp-1")
    suite.append_message("assistant", "Exp 1 work")
    suite.switch_active_branch("main")

    suite.fork_branch("exp-2")
    suite.switch_active_branch("exp-2")
    suite.append_message("assistant", "Exp 2 work")
    suite.switch_active_branch("main")

    gc_suite = SessionTreeBranchPruneAndStorageGCSuite(tree_suite=suite)
    report1, receipt1 = gc_suite.prune_branch("exp-1", force=True)
    report2, receipt2 = gc_suite.prune_branch("exp-2", force=True)

    receipts = gc_suite.get_gc_receipts()
    assert len(receipts) == 2
    assert receipts[0].receipt_id.startswith("sgc_")
    assert receipts[1].receipt_id.startswith("sgc_")
    assert receipts[0].compaction_hash != ""
    assert receipts[1].compaction_hash != ""
    assert "main" in receipts[0].retained_branches
    assert "main" in receipts[1].retained_branches
