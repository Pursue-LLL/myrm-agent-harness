"""Unit tests for BranchSwitchWorkspaceStashAndArtifactIntegritySuite."""

from __future__ import annotations

from pathlib import Path
import pytest

from myrm_agent_harness.agent.context_management import (
    BranchSwitchWorkspaceStashAndArtifactIntegritySuite,
    BranchWorkspaceSnapshot,
    FileStashKind,
    SessionTreeDagSuite,
    ShadowStashEngine,
    WorkspaceStashConflictWarning,
    WorkspaceStashReceipt,
)


def test_shadow_stash_file_capture_and_checksum_integrity(tmp_path: Path) -> None:
    """Test capturing workspace files into immutable shadow stash records with SHA-256 integrity."""
    workspace_dir = tmp_path / "sandbox_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    file_a = workspace_dir / "src" / "algorithm.py"
    file_a.parent.mkdir(parents=True, exist_ok=True)
    file_a.write_text("def solve(): return 42\n", encoding="utf-8")

    suite = BranchSwitchWorkspaceStashAndArtifactIntegritySuite(session_id="sess-stash-001")
    suite.register_modified_files(branch_name="main", relative_paths=["src/algorithm.py"])

    snapshot = suite.stash_current_branch(
        workspace_root=str(workspace_dir),
        branch_name="main",
    )

    assert not snapshot.is_pristine
    assert "src/algorithm.py" in snapshot.stashed_files
    rec = snapshot.stashed_files["src/algorithm.py"]
    assert rec.file_stash_kind == FileStashKind.MODIFIED
    assert rec.content_text == "def solve(): return 42\n"
    assert len(rec.sha256_hash) == 16
    assert snapshot.snapshot_hash != ""


def test_branch_switch_workspace_synchronization_and_exclusive_file_cleanup(tmp_path: Path) -> None:
    """Test branch switch restores target files and cleans up source branch exclusive files."""
    workspace_dir = tmp_path / "sandbox_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # 1. Main branch has base.py
    base_file = workspace_dir / "base.py"
    base_file.write_text("print('base')\n", encoding="utf-8")

    tree_suite = SessionTreeDagSuite(session_id="sess-switch-002")
    stash_suite = BranchSwitchWorkspaceStashAndArtifactIntegritySuite(session_id="sess-switch-002")
    stash_suite.register_modified_files("main", ["base.py"])
    stash_suite.stash_current_branch(str(workspace_dir), "main")

    # 2. Branch A creates experiment_a.py
    tree_suite.fork_branch(new_branch_name="branch-a")
    exp_a = workspace_dir / "experiment_a.py"
    exp_a.write_text("# experiment A logic\n", encoding="utf-8")
    stash_suite.register_modified_files("branch-a", ["base.py", "experiment_a.py"])

    # 3. Branch B creates experiment_b.py
    tree_suite.fork_branch(new_branch_name="branch-b")
    exp_b = workspace_dir / "experiment_b.py"
    exp_b.write_text("# experiment B logic\n", encoding="utf-8")
    stash_suite.register_modified_files("branch-b", ["base.py", "experiment_b.py"])
    stash_suite.stash_current_branch(str(workspace_dir), "branch-b")

    # Now we switch from branch-b to branch-a:
    # First ensure branch-a is stashed
    tree_suite.switch_active_branch("branch-a")
    stash_suite.stash_current_branch(str(workspace_dir), "branch-a")

    # Now switch from branch-a to branch-b
    target_snapshot, receipt = stash_suite.switch_branch_with_workspace_sync(
        tree_suite=tree_suite,
        workspace_root=str(workspace_dir),
        source_branch="branch-a",
        target_branch="branch-b",
    )

    assert receipt.source_branch == "branch-a"
    assert receipt.target_branch == "branch-b"
    assert (workspace_dir / "experiment_b.py").exists()
    # Source-exclusive experiment_a.py must be purged from disk
    assert not (workspace_dir / "experiment_a.py").exists()


def test_dirty_conflict_detection_and_safety_gate(tmp_path: Path) -> None:
    """Test detecting dirty conflicting modifications and blocking unsafe switch unless force=True."""
    workspace_dir = tmp_path / "sandbox_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    tree_suite = SessionTreeDagSuite(session_id="sess-conflict-003")
    tree_suite.fork_branch(new_branch_name="target-branch")
    tree_suite.fork_branch(new_branch_name="source-branch")
    tree_suite.switch_active_branch("source-branch")

    stash_suite = BranchSwitchWorkspaceStashAndArtifactIntegritySuite(session_id="sess-conflict-003")

    target_file = workspace_dir / "config.yaml"
    target_file.write_text("mode: production\n", encoding="utf-8")
    stash_suite.register_modified_files("target-branch", ["config.yaml"])
    stash_suite.stash_current_branch(str(workspace_dir), "target-branch")

    # On active source branch, external dirty modification happened
    target_file.write_text("mode: uncommitted-experimental\n", encoding="utf-8")
    stash_suite.register_modified_files("source-branch", ["config.yaml"])

    # Switching without force should detect conflict if hashes disagree
    # Here source baseline has not been captured yet, so disk differs from target and no source baseline
    with pytest.raises(RuntimeError, match="Workspace branch switch blocked by dirty conflicts"):
        stash_suite.switch_branch_with_workspace_sync(
            tree_suite=tree_suite,
            workspace_root=str(workspace_dir),
            source_branch="source-branch",
            target_branch="target-branch",
            force=False,
        )

    # Force switch succeeds and overwrites
    snap, receipt = stash_suite.switch_branch_with_workspace_sync(
        tree_suite=tree_suite,
        workspace_root=str(workspace_dir),
        source_branch="source-branch",
        target_branch="target-branch",
        force=True,
    )
    assert snap.branch_name == "target-branch"
    assert target_file.read_text(encoding="utf-8") == "mode: production\n"


def test_branch_switch_stash_receipt_audit(tmp_path: Path) -> None:
    """Test auditing synchronization receipts across multiple branch switch operations."""
    workspace_dir = tmp_path / "sandbox_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)

    tree_suite = SessionTreeDagSuite(session_id="sess-receipt-004")
    tree_suite.fork_branch(new_branch_name="feature-1")
    tree_suite.fork_branch(new_branch_name="feature-2")
    tree_suite.switch_active_branch("feature-1")

    stash_suite = BranchSwitchWorkspaceStashAndArtifactIntegritySuite(session_id="sess-receipt-004")

    f1 = workspace_dir / "f1.txt"
    f1.write_text("feature 1", encoding="utf-8")
    stash_suite.register_modified_files("feature-1", ["f1.txt"])

    stash_suite.switch_branch_with_workspace_sync(
        tree_suite=tree_suite,
        workspace_root=str(workspace_dir),
        source_branch="feature-1",
        target_branch="feature-2",
    )

    receipts = stash_suite.get_stash_receipts()
    assert len(receipts) == 1
    assert receipts[0].source_branch == "feature-1"
    assert receipts[0].target_branch == "feature-2"
    assert receipts[0].synchronization_hash != ""
