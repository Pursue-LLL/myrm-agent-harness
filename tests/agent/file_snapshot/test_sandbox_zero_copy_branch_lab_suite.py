"""Tests for sandbox zero-copy branch lab suite and rollout promotions.

[INPUT]
SandboxZeroCopyBranchLabSuite, ZeroCopyBranchManager, BranchCasOverlay.

[OUTPUT]
Unit test assertions validating zero-copy fork, COW isolation, CAS deduplication,
diff generation, discard storage reclamation, and atomic promotion.

[POS]
Unit tests in tests/agent/file_snapshot/test_sandbox_zero_copy_branch_lab_suite.py.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.agent.file_snapshot import (
    BranchCasOverlay,
    BranchLabConfig,
    BranchStatus,
    BranchVerdict,
    MutationType,
    SandboxZeroCopyBranchLabSuite,
    ZeroCopyBranchManager,
)


def test_zero_copy_fork_instant_and_zero_delta() -> None:
    """Verify forking a branch takes O(1) time with strictly zero initial storage delta."""
    suite = SandboxZeroCopyBranchLabSuite()
    base_snapshot_id = "snap_baseline_commit_001"

    branch = suite.fork_branch(
        base_snapshot_id=base_snapshot_id,
        branch_name="experiment-ast-refactor",
        purpose="Testing new AST parsing engine",
        metadata={"author": "subagent-1"},
    )

    assert branch.branch_id.startswith("br_")
    assert branch.base_snapshot_id == base_snapshot_id
    assert branch.branch_name == "experiment-ast-refactor"
    assert branch.status == BranchStatus.ACTIVE
    assert branch.purpose == "Testing new AST parsing engine"
    assert branch.metadata.get("author") == "subagent-1"

    diff = suite.diff_branch(branch.branch_id)
    assert diff.total_changes == 0
    assert diff.delta_bytes_total == 0
    assert len(diff.items) == 0


def test_cow_isolation_and_cas_deduplication() -> None:
    """Verify copy-on-write isolation across branches and CAS blob deduplication."""
    overlay = BranchCasOverlay()
    manager = ZeroCopyBranchManager(overlay=overlay)
    suite = SandboxZeroCopyBranchLabSuite(manager=manager)

    br_a = suite.fork_branch("base_01", branch_name="branch-a")
    br_b = suite.fork_branch("base_01", branch_name="branch-b")

    shared_content = b"def common_algorithm():\n    return 42\n"
    unique_content = b"print('unique to branch b')\n"

    # Branch A writes shared content
    mut_a = suite.record_mutation(
        br_a.branch_id,
        file_path="src/calc.py",
        mutation_type=MutationType.ADDED,
        content=shared_content,
    )
    assert mut_a.byte_size == len(shared_content)

    # Branch B writes identical content to another path -> deduplicated in blob store
    mut_b1 = suite.record_mutation(
        br_b.branch_id,
        file_path="src/other.py",
        mutation_type=MutationType.ADDED,
        content=shared_content,
    )
    assert mut_b1.content_hash == mut_a.content_hash

    # Branch B writes unique content
    suite.record_mutation(
        br_b.branch_id,
        file_path="src/calc.py",
        mutation_type=MutationType.ADDED,
        content=unique_content,
    )

    # CAS deduplication verification: same hash has ref count 2 in overlay
    assert overlay._blob_ref_counts[mut_a.content_hash] == 2

    # Branch isolation verification
    content_a = overlay.get_file_content(br_a.branch_id, "src/calc.py")
    content_b = overlay.get_file_content(br_b.branch_id, "src/calc.py")
    assert content_a == shared_content
    assert content_b == unique_content


def test_diff_branch_accurate_summary() -> None:
    """Verify branch diff summary accurately tallies added, modified, and deleted items."""
    suite = SandboxZeroCopyBranchLabSuite()
    branch = suite.fork_branch("base_v1")

    suite.record_write_text(branch.branch_id, "new_file.txt", "hello world")
    suite.record_write_text(branch.branch_id, "existing.txt", "updated text", old_size=50)
    suite.record_mutation(
        branch.branch_id,
        file_path="obsolete.txt",
        mutation_type=MutationType.DELETED,
        old_size=120,
    )

    diff = suite.diff_branch(branch.branch_id)
    assert diff.total_changes == 3
    assert diff.files_added == 1
    assert diff.files_modified == 1
    assert diff.files_deleted == 1
    assert len(diff.items) == 3


def test_discard_branch_releases_storage_and_produces_receipt() -> None:
    """Verify discarding a branch reclaims overlay storage and issues immutable receipt."""
    suite = SandboxZeroCopyBranchLabSuite()
    branch = suite.fork_branch("base_commit_x")

    payload = b"temporary experiment artifact data " * 50
    suite.record_mutation(
        branch.branch_id,
        file_path="temp.dat",
        mutation_type=MutationType.ADDED,
        content=payload,
    )

    discard_res = suite.discard_branch(branch.branch_id, reason="Benchmark failed on regression")
    assert discard_res.success is True
    assert discard_res.bytes_reclaimed == len(payload)
    assert discard_res.reason == "Benchmark failed on regression"

    receipt = discard_res.receipt
    assert receipt.verdict == BranchVerdict.DISCARDED
    assert receipt.branch_id == branch.branch_id
    assert receipt.files_changed == 1
    assert len(receipt.immutable_hash) == 64
    assert receipt.receipt_id.startswith("rcpt_")

    # Stored descriptor is marked DISCARDED
    stored_branch = suite.get_branch(branch.branch_id)
    assert stored_branch is not None
    assert stored_branch.status == BranchStatus.DISCARDED
    assert stored_branch.closed_at is not None

    # Mutation after discard fails
    with pytest.raises(ValueError, match="is not active"):
        suite.record_write_text(branch.branch_id, "illegal.txt", "fail")


def test_promote_branch_applies_changes_and_records_receipt() -> None:
    """Verify promoting a branch applies added/modified/deleted files into target directory."""
    suite = SandboxZeroCopyBranchLabSuite()
    branch = suite.fork_branch("base_snap_stable")

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        # Pre-seed an existing file and an obsolete file
        (work_dir / "mod_target.py").write_text("v1_original", encoding="utf-8")
        (work_dir / "to_delete.txt").write_text("delete_me", encoding="utf-8")

        # Record changes in branch overlay
        suite.record_write_text(branch.branch_id, "added_file.py", "def new_feature(): pass")
        suite.record_write_text(
            branch.branch_id,
            "mod_target.py",
            "v2_improved_content",
            old_size=len("v1_original"),
        )
        suite.record_mutation(
            branch.branch_id,
            file_path="to_delete.txt",
            mutation_type=MutationType.DELETED,
            old_size=len("delete_me"),
        )

        promote_res = suite.promote_branch(
            branch.branch_id,
            target_working_dir=work_dir,
            promotion_reason="Passed all unit and regression tests",
        )

        assert promote_res.success is True
        assert promote_res.files_applied == 3
        assert promote_res.promoted_snapshot_id is not None
        assert promote_res.promoted_snapshot_id.startswith("snap_promoted_")

        # Receipt checks
        receipt = promote_res.receipt
        assert receipt.verdict == BranchVerdict.PROMOTED
        assert receipt.files_changed == 3
        assert len(receipt.immutable_hash) == 64

        # Physical filesystem verification
        assert (work_dir / "added_file.py").read_text(encoding="utf-8") == "def new_feature(): pass"
        assert (work_dir / "mod_target.py").read_text(encoding="utf-8") == "v2_improved_content"
        assert not (work_dir / "to_delete.txt").exists()

        # Descriptor status check
        stored = suite.get_branch(branch.branch_id)
        assert stored is not None
        assert stored.status == BranchStatus.PROMOTED


def test_evaluate_and_promote_best_parallel_rollout() -> None:
    """Verify parallel candidate evaluation promoting the highest score and discarding others."""
    suite = SandboxZeroCopyBranchLabSuite()
    br1 = suite.fork_branch("base_pt", branch_name="candidate-1")
    br2 = suite.fork_branch("base_pt", branch_name="candidate-2")
    br3 = suite.fork_branch("base_pt", branch_name="candidate-3")

    suite.record_write_text(br1.branch_id, "opt.py", "minor fix")
    suite.record_write_text(br2.branch_id, "opt.py", "optimal 10x vectorized algorithm")
    suite.record_write_text(br3.branch_id, "opt.py", "broken implementation")

    scores = {
        br1.branch_id: 65.0,
        br2.branch_id: 98.5,  # Winner
        br3.branch_id: 12.0,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        promoted, discards = suite.evaluate_and_promote_best(
            branch_ids=[br1.branch_id, br2.branch_id, br3.branch_id],
            evaluator_fn=lambda diff: scores.get(diff.branch_id, 0.0),
            target_working_dir=work_dir,
        )

        assert promoted is not None
        assert promoted.branch_id == br2.branch_id
        assert len(discards) == 2
        discarded_ids = {d.branch_id for d in discards}
        assert discarded_ids == {br1.branch_id, br3.branch_id}

        # Check winner applied
        assert (work_dir / "opt.py").read_text(encoding="utf-8") == "optimal 10x vectorized algorithm"


def test_capacity_and_delta_budget_guards() -> None:
    """Verify guards enforce maximum active branches and max delta byte limits."""
    config = BranchLabConfig(max_active_branches=2, max_branch_delta_bytes=100)
    suite = SandboxZeroCopyBranchLabSuite(config=config)

    b1 = suite.fork_branch("base_lim")
    b2 = suite.fork_branch("base_lim")

    # Exceeding active branches throws error
    with pytest.raises(RuntimeError, match="Active branches limit reached"):
        suite.fork_branch("base_lim")

    # Exceeding delta bytes budget throws error
    with pytest.raises(ValueError, match="Mutation exceeds branch delta storage budget"):
        suite.record_mutation(
            b1.branch_id,
            file_path="huge.bin",
            mutation_type=MutationType.ADDED,
            content=b"x" * 150,
        )

    # Discarding one branch frees an active slot
    suite.discard_branch(b2.branch_id)
    b3 = suite.fork_branch("base_lim")
    assert b3.status == BranchStatus.ACTIVE
