"""Unit tests for Git Worktree Multi-Branch Parallel Session Isolation Engine.

Validates deep session-to-worktree CWD binding, adaptive worktree context restoration,
project-root hierarchy aggregation, and safe removal guards protecting dirty files.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.worktree_isolation import (
    WorktreeDescriptor,
    WorktreeHygieneStatus,
    WorktreeRemovalPolicy,
    WorktreeSessionIsolationEngine,
)


def test_worktree_registration_and_project_tree_matrix() -> None:
    """Verifies worktree registration under project root and tree matrix aggregation."""
    engine = WorktreeSessionIsolationEngine()
    project_root = "/repos/my-service"

    # Main checkout
    wt_main = WorktreeDescriptor(
        worktree_id="wt-main",
        project_root=project_root,
        worktree_path="/repos/my-service",
        branch_name="main",
        head_commit="commit-111",
        is_main_checkout=True,
    )
    # Feature worktree
    wt_feature = WorktreeDescriptor(
        worktree_id="wt-feature-login",
        project_root=project_root,
        worktree_path="/repos/my-service-worktrees/feature-login",
        branch_name="feature/login",
        head_commit="commit-222",
        is_main_checkout=False,
    )

    engine.register_worktree(wt_main)
    engine.register_worktree(wt_feature)

    worktrees = engine.get_project_worktrees(project_root)
    assert len(worktrees) == 2
    ids = {w.worktree_id for w in worktrees}
    assert "wt-main" in ids
    assert "wt-feature-login" in ids

    # Bind sessions
    engine.bind_session_to_worktree("sess-01", "wt-main")
    engine.bind_session_to_worktree("sess-02", "wt-feature-login")
    engine.bind_session_to_worktree("sess-03", "wt-feature-login")

    # Inspect tree matrix
    matrix = engine.get_project_tree_matrix(project_root)
    assert "wt-main" in matrix
    assert matrix["wt-main"][1] == ("sess-01",)
    assert "wt-feature-login" in matrix
    assert set(matrix["wt-feature-login"][1]) == {"sess-02", "sess-03"}


def test_session_deep_cwd_binding_and_adaptive_restoration() -> None:
    """Verifies that each session adaptively restores its dedicated worktree CWD."""
    engine = WorktreeSessionIsolationEngine()
    project_root = "/repos/cloud-api"

    wt_a = WorktreeDescriptor(
        worktree_id="wt-branch-a",
        project_root=project_root,
        worktree_path="/repos/cloud-api-worktrees/branch-a",
        branch_name="feature/pipeline-v2",
        head_commit="commit-aaa",
    )
    wt_b = WorktreeDescriptor(
        worktree_id="wt-branch-b",
        project_root=project_root,
        worktree_path="/repos/cloud-api-worktrees/branch-b",
        branch_name="hotfix/null-pointer",
        head_commit="commit-bbb",
    )

    engine.register_worktree(wt_a)
    engine.register_worktree(wt_b)

    # Bind two distinct sessions running concurrently
    engine.bind_session_to_worktree("session-alpha", "wt-branch-a")
    engine.bind_session_to_worktree("session-beta", "wt-branch-b")

    # Adaptive CWD restoration
    cwd_alpha = engine.resolve_session_cwd("session-alpha")
    cwd_beta = engine.resolve_session_cwd("session-beta")

    assert cwd_alpha == "/repos/cloud-api-worktrees/branch-a"
    assert cwd_beta == "/repos/cloud-api-worktrees/branch-b"
    assert cwd_alpha != cwd_beta

    # Query binding metadata
    binding_alpha = engine.get_session_binding("session-alpha")
    assert binding_alpha is not None
    assert binding_alpha.branch_name == "feature/pipeline-v2"

    # Unbound session raises KeyError
    with pytest.raises(KeyError, match="has no worktree binding"):
        engine.resolve_session_cwd("session-unknown")


def test_safe_removal_guard_blocks_dirty_worktree() -> None:
    """Verifies that worktree with uncommitted changes is blocked from removal under safe policy."""
    engine = WorktreeSessionIsolationEngine()
    project_root = "/repos/core-engine"

    wt = WorktreeDescriptor(
        worktree_id="wt-experiment",
        project_root=project_root,
        worktree_path="/repos/core-engine-worktrees/experiment",
        branch_name="test/benchmark",
        head_commit="commit-exp",
    )
    engine.register_worktree(wt)
    engine.bind_session_to_worktree("session-exp", "wt-experiment")

    # Inspect hygiene with uncommitted files
    report = engine.inspect_hygiene(
        worktree_id="wt-experiment",
        uncommitted_files=("src/main.py", "config/settings.yaml"),
        untracked_files=("scratch.log",),
    )
    assert report.status == WorktreeHygieneStatus.DIRTY_UNCOMMITTED
    assert report.is_safe_to_remove is False

    # Attempt removal with default SAFE_GUARD_BLOCK_IF_DIRTY policy -> Blocked
    res_blocked = engine.safe_remove_worktree(
        worktree_id="wt-experiment",
        hygiene_report=report,
        policy=WorktreeRemovalPolicy.SAFE_GUARD_BLOCK_IF_DIRTY,
    )
    assert res_blocked.removed is False
    assert res_blocked.is_blocked_by_dirty is True
    assert res_blocked.uncommitted_count == 2
    assert res_blocked.untracked_count == 1
    assert "Force purge required" in res_blocked.message

    # Verify worktree and session binding still exist
    assert engine.get_worktree("wt-experiment") is not None
    assert engine.get_session_binding("session-exp") is not None

    # Now override with FORCE_PURGE_OVERRIDE policy -> Allowed
    res_purged = engine.safe_remove_worktree(
        worktree_id="wt-experiment",
        hygiene_report=report,
        policy=WorktreeRemovalPolicy.FORCE_PURGE_OVERRIDE,
    )
    assert res_purged.removed is True
    assert res_purged.is_blocked_by_dirty is False
    assert "force purged" in res_purged.message

    # Verify worktree and binding are cleanly removed
    assert engine.get_worktree("wt-experiment") is None
    assert engine.get_session_binding("session-exp") is None


def test_main_checkout_removal_prevention_and_clean_removal() -> None:
    """Verifies that main checkout cannot be removed and clean worktrees are safely dismantled."""
    engine = WorktreeSessionIsolationEngine()
    project_root = "/repos/core-repo"

    wt_main = WorktreeDescriptor(
        worktree_id="wt-main",
        project_root=project_root,
        worktree_path="/repos/core-repo",
        branch_name="main",
        head_commit="commit-root",
        is_main_checkout=True,
    )
    wt_clean = WorktreeDescriptor(
        worktree_id="wt-clean-task",
        project_root=project_root,
        worktree_path="/repos/core-repo-worktrees/clean-task",
        branch_name="chore/docs",
        head_commit="commit-docs",
        is_main_checkout=False,
    )

    engine.register_worktree(wt_main)
    engine.register_worktree(wt_clean)

    # 1. Main checkout rejection
    report_main = engine.inspect_hygiene("wt-main")
    res_main = engine.safe_remove_worktree("wt-main", report_main)
    assert res_main.removed is False
    assert "Main checkout" in res_main.message

    # 2. Clean worktree dismantlement
    report_clean = engine.inspect_hygiene("wt-clean-task")
    assert report_clean.status == WorktreeHygieneStatus.CLEAN
    assert report_clean.is_safe_to_remove is True

    res_clean = engine.safe_remove_worktree("wt-clean-task", report_clean)
    assert res_clean.removed is True
    assert "safely removed" in res_clean.message
    assert engine.get_worktree("wt-clean-task") is None
